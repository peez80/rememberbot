import re
import json
import base64
import hashlib
import secrets
import logging
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlencode

import httpx

from app.core.config import (
    OAUTH_CLIENT_ID,
    OAUTH_CLIENT_SECRET,
    OAUTH_ISSUER_URL,
    OAUTH_DISCOVERY_URL,
    OAUTH_AUTHORIZE_URL,
    OAUTH_TOKEN_URL,
    OAUTH_USERINFO_URL,
    OAUTH_SCOPE,
    OAUTH_USERNAME_CLAIM,
    OAUTH_PROVIDER_NAME,
)

logger = logging.getLogger(__name__)

class OAuthError(Exception):
    """Base exception for OAuth / OIDC communication and protocol failures."""
    pass

class OAuthConfigurationError(OAuthError):
    """Exception raised when required OAuth configuration is missing or invalid."""
    pass


class OAuthClient:
    """
    Asynchronous OpenID Connect (OIDC) & OAuth 2.0 client.
    Implements RFC 6749 (Authorization Code Grant), RFC 7636 (PKCE),
    and OIDC Discovery Specification.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        issuer_url: Optional[str] = None,
        discovery_url: Optional[str] = None,
        authorize_url: Optional[str] = None,
        token_url: Optional[str] = None,
        userinfo_url: Optional[str] = None,
        scope: Optional[str] = None,
        username_claim: Optional[str] = None,
        provider_name: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        timeout: float = 10.0,
    ):
        self.client_id = (client_id if client_id is not None else OAUTH_CLIENT_ID).strip()
        self.client_secret = (client_secret if client_secret is not None else OAUTH_CLIENT_SECRET).strip()
        self.issuer_url = (issuer_url if issuer_url is not None else OAUTH_ISSUER_URL).strip().rstrip("/")
        self.discovery_url = (discovery_url if discovery_url is not None else OAUTH_DISCOVERY_URL).strip()
        self.authorize_url = (authorize_url if authorize_url is not None else OAUTH_AUTHORIZE_URL).strip()
        self.token_url = (token_url if token_url is not None else OAUTH_TOKEN_URL).strip()
        self.userinfo_url = (userinfo_url if userinfo_url is not None else OAUTH_USERINFO_URL).strip()
        self.scope = (scope if scope is not None else OAUTH_SCOPE).strip()
        self.username_claim = (username_claim if username_claim is not None else OAUTH_USERNAME_CLAIM).strip()
        self.provider_name = (provider_name if provider_name is not None else OAUTH_PROVIDER_NAME).strip() or "SSO"
        self.transport = transport
        self.timeout = timeout
        self._discovery_config: Optional[Dict[str, Any]] = None

        if not self.client_id or not self.client_secret:
            raise OAuthConfigurationError(
                "OAuthClient erfordert nicht-leere Werte für 'client_id' und 'client_secret'."
            )

    def _create_http_client(self) -> httpx.AsyncClient:
        kwargs: Dict[str, Any] = {"timeout": self.timeout}
        if self.transport is not None:
            kwargs["transport"] = self.transport
        return httpx.AsyncClient(**kwargs)

    async def get_discovery_config(self) -> Dict[str, Any]:
        """
        Retrieves OpenID Connect Discovery configuration from the provider.
        Supports standard discovery path and fallback path for Nextcloud without URL rewriting.
        """
        if self._discovery_config:
            return self._discovery_config

        endpoints_to_try = []
        if self.discovery_url:
            endpoints_to_try.append(self.discovery_url)
        elif self.issuer_url:
            endpoints_to_try.append(f"{self.issuer_url}/.well-known/openid-configuration")
            endpoints_to_try.append(f"{self.issuer_url}/index.php/.well-known/openid-configuration")
        else:
            raise OAuthConfigurationError(
                "Weder discovery_url noch issuer_url konfiguriert für OIDC Discovery."
            )

        last_error = None
        async with self._create_http_client() as client:
            for url in endpoints_to_try:
                try:
                    resp = await client.get(url, headers={"Accept": "application/json"})
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, dict) and "authorization_endpoint" in data:
                            self._discovery_config = data
                            logger.info(f"OIDC Discovery erfolgreich geladen von '{url}'")
                            return self._discovery_config
                    else:
                        logger.warning(f"OIDC Discovery an '{url}' lieferte Status {resp.status_code}")
                except Exception as e:
                    last_error = e
                    logger.warning(f"OIDC Discovery Versuch an '{url}' fehlgeschlagen: {e}")

        logger.error(
            f"OIDC Discovery für Issuer '{self.issuer_url}' vollständig fehlgeschlagen. Letzter Fehler: {last_error}",
            exc_info=True
        )
        raise OAuthError(f"OIDC Discovery fehlgeschlagen für '{self.issuer_url}': {last_error}")

    async def get_authorization_url(self, redirect_uri: str, state: str) -> Tuple[str, str]:
        """
        Generates the authorization URL with PKCE (RFC 7636).
        Returns a tuple of (authorization_url, code_verifier).
        """
        # Determine authorization endpoint
        if self.authorize_url:
            auth_endpoint = self.authorize_url
        else:
            discovery = await self.get_discovery_config()
            auth_endpoint = discovery.get("authorization_endpoint")
            if not auth_endpoint:
                raise OAuthError("OIDC Discovery enthält keinen gültigen 'authorization_endpoint'.")

        # Generate PKCE verifier and challenge (RFC 7636 S256)
        code_verifier = secrets.token_urlsafe(64)
        hashed = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(hashed).decode("ascii").rstrip("=")

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": self.scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        separator = "&" if "?" in auth_endpoint else "?"
        full_url = f"{auth_endpoint}{separator}{urlencode(params)}"
        return full_url, code_verifier

    async def exchange_code_for_user(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: Optional[str] = None
    ) -> str:
        """
        Exchanges the authorization code for tokens and retrieves user identity claims.
        Returns the sanitized username.
        """
        # 1. Resolve endpoints
        if self.token_url:
            token_endpoint = self.token_url
        else:
            discovery = await self.get_discovery_config()
            token_endpoint = discovery.get("token_endpoint")

        if self.userinfo_url:
            userinfo_endpoint = self.userinfo_url
        else:
            discovery = await self.get_discovery_config()
            userinfo_endpoint = discovery.get("userinfo_endpoint")

        if not token_endpoint or not userinfo_endpoint:
            raise OAuthError(
                f"Ungültige Endpunkt-Konfiguration: token_endpoint={token_endpoint}, "
                f"userinfo_endpoint={userinfo_endpoint}"
            )

        # 2. Token Exchange
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        if code_verifier:
            payload["code_verifier"] = code_verifier

        async with self._create_http_client() as client:
            try:
                resp = await client.post(
                    token_endpoint,
                    data=payload,
                    headers={"Accept": "application/json"}
                )
            except Exception as e:
                logger.error(f"Netzwerkfehler beim OAuth Token-Exchange an '{token_endpoint}': {e}", exc_info=True)
                raise OAuthError(f"OAuth token exchange failed due to network error: {e}")

            if resp.status_code != 200:
                logger.error(
                    f"Token-Endpoint '{token_endpoint}' lieferte Fehler-Status {resp.status_code}: {resp.text}"
                )
                raise OAuthError(f"Token endpoint returned status {resp.status_code}")

            try:
                token_data = resp.json()
            except Exception as e:
                logger.error(f"Ungültiges JSON vom Token-Endpoint: {e}", exc_info=True)
                raise OAuthError("Token endpoint returned malformed JSON")

            access_token = token_data.get("access_token")
            if not access_token:
                logger.error("Token-Endpoint Antwort enthält keinen 'access_token'")
                raise OAuthError("OAuth token response missing access_token")

            # 3. Userinfo Call
            try:
                userinfo_resp = await client.get(
                    userinfo_endpoint,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                    }
                )
            except Exception as e:
                logger.error(f"Netzwerkfehler beim Userinfo-Abruf an '{userinfo_endpoint}': {e}", exc_info=True)
                raise OAuthError(f"Userinfo request failed due to network error: {e}")

            if userinfo_resp.status_code != 200:
                logger.error(
                    f"Userinfo-Endpoint '{userinfo_endpoint}' lieferte Fehler-Status {userinfo_resp.status_code}: {userinfo_resp.text}"
                )
                raise OAuthError(f"Userinfo endpoint returned status {userinfo_resp.status_code}")

            try:
                userinfo = userinfo_resp.json()
            except Exception as e:
                logger.error(f"Ungültiges JSON vom Userinfo-Endpoint: {e}", exc_info=True)
                raise OAuthError("Userinfo endpoint returned malformed JSON")

        # 4. Extract and sanitize username
        username = self._extract_username(userinfo)
        return username

    def _extract_username(self, userinfo: Dict[str, Any]) -> str:
        """
        Extracts user identifier following the claim priority chain:
        configured username_claim -> preferred_username -> sub -> email -> Nextcloud OCS data.id
        Sanitizes result for filesystem and session safety.
        """
        candidates = [self.username_claim, "preferred_username", "sub", "email", "id"]
        raw_username = None

        for claim in candidates:
            if claim and claim in userinfo and userinfo[claim]:
                val = str(userinfo[claim]).strip()
                if val:
                    raw_username = val
                    break

        # Fallback for nested Nextcloud OCS response if present
        if not raw_username and isinstance(userinfo.get("ocs"), dict):
            data = userinfo["ocs"].get("data")
            if isinstance(data, dict) and data.get("id"):
                raw_username = str(data["id"]).strip()

        if not raw_username:
            logger.error(f"Keine gültige Benutzerkennung in Userinfo-Claims gefunden: {list(userinfo.keys())}")
            raise OAuthError("No valid username claim found in userinfo response")

        # Remove dot-dot sequences and directory traversal patterns
        cleaned = re.sub(r'\.{2,}', '_', raw_username)
        # Sanitize username against path traversal or malicious filesystem characters
        safe_username = re.sub(r'[^a-zA-Z0-9_\-\.@]', '_', cleaned)
        safe_username = safe_username.strip('._')
        if not safe_username:
            logger.error(f"Benutzername '{raw_username}' nach Sanitization ungültig ('{safe_username}')")
            raise OAuthError("Sanitized username is invalid")

        return safe_username
