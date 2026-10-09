import json
import base64
import hashlib
from typing import Optional, Dict, Any
import httpx

class MockOAuthTransport(httpx.AsyncBaseTransport):
    """
    Mock transport for httpx.AsyncClient that simulates a standard OpenID Connect (OIDC) / OAuth 2.0 provider.
    Supports OIDC Discovery, PKCE verification, Token Exchange, and Userinfo endpoints.
    Allows simulating various error scenarios (400, 401, 500, corrupt JSON, etc.).
    """

    def __init__(
        self,
        issuer_url: str = "https://idp.example.com",
        client_id: str = "test-client-id",
        client_secret: str = "test-client-secret",
        valid_code: str = "valid-auth-code",
        valid_token: str = "mock-access-token-xyz",
        user_claims: Optional[Dict[str, Any]] = None,
        simulate_error: Optional[str] = None,
        simulate_status_code: Optional[int] = None,
        simulate_malformed_json: bool = False,
    ):
        self.issuer_url = issuer_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.valid_code = valid_code
        self.valid_token = valid_token
        self.user_claims = user_claims or {
            "sub": "user_id_12345",
            "preferred_username": "alice",
            "name": "Alice Nextcloud",
            "email": "alice@example.com",
        }
        self.simulate_error = simulate_error
        self.simulate_status_code = simulate_status_code
        self.simulate_token_status_code: Optional[int] = None
        self.simulate_malformed_json = simulate_malformed_json
        self.stored_code_verifier: Optional[str] = None
        self.issued_code_challenge: Optional[str] = None
        self.request_history: list[httpx.Request] = []

    def set_expected_pkce(self, code_challenge: str):
        self.issued_code_challenge = code_challenge

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.request_history.append(request)
        url_path = request.url.path

        if self.simulate_status_code:
            return httpx.Response(self.simulate_status_code, content=b"Simulated Error", request=request)

        if self.simulate_error == "network_error":
            raise httpx.ConnectError("Connection refused by mock identity provider", request=request)

        if self.simulate_error == "timeout":
            raise httpx.TimeoutException("Request timed out to mock identity provider", request=request)

        # 1. Discovery endpoint
        if url_path in ("/.well-known/openid-configuration", "/index.php/.well-known/openid-configuration"):
            if self.simulate_error == "discovery_404" and url_path == "/.well-known/openid-configuration":
                return httpx.Response(404, text="Not Found", request=request)

            discovery_data = {
                "issuer": self.issuer_url,
                "authorization_endpoint": f"{self.issuer_url}/oauth/authorize",
                "token_endpoint": f"{self.issuer_url}/oauth/token",
                "userinfo_endpoint": f"{self.issuer_url}/oauth/userinfo",
                "response_types_supported": ["code"],
                "subject_types_supported": ["public"],
                "id_token_signing_alg_values_supported": ["RS256"],
                "scopes_supported": ["openid", "profile", "email"],
                "code_challenge_methods_supported": ["S256"],
            }
            if self.simulate_malformed_json:
                return httpx.Response(200, content=b"invalid {json}", headers={"content-type": "application/json"}, request=request)

            return httpx.Response(200, json=discovery_data, request=request)

        # 2. Token endpoint
        if url_path in ("/oauth/token", "/apps/oauth2/api/v1/token"):
            if self.simulate_token_status_code:
                return httpx.Response(self.simulate_token_status_code, content=b"Simulated Token Error", request=request)

            if request.method != "POST":
                return httpx.Response(405, text="Method Not Allowed", request=request)

            body = await request.aread()
            # Parse form-encoded body
            from urllib.parse import parse_qs
            form_data = parse_qs(body.decode("utf-8"))
            grant_type = form_data.get("grant_type", [""])[0]
            code = form_data.get("code", [""])[0]
            client_id = form_data.get("client_id", [""])[0]
            client_secret = form_data.get("client_secret", [""])[0]
            code_verifier = form_data.get("code_verifier", [""])[0]

            if grant_type != "authorization_code":
                return httpx.Response(400, json={"error": "unsupported_grant_type"}, request=request)

            if client_id != self.client_id or client_secret != self.client_secret:
                return httpx.Response(401, json={"error": "invalid_client"}, request=request)

            if code != self.valid_code:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Code invalid or expired"}, request=request)

            # Check PKCE if expected
            if self.issued_code_challenge and code_verifier:
                computed_challenge = base64.urlsafe_b64encode(
                    hashlib.sha256(code_verifier.encode("ascii")).digest()
                ).decode("ascii").rstrip("=")
                if computed_challenge != self.issued_code_challenge:
                    return httpx.Response(400, json={"error": "invalid_grant", "error_description": "PKCE verification failed"}, request=request)

            if self.simulate_error == "token_missing_access_token":
                return httpx.Response(200, json={"token_type": "Bearer"}, request=request)

            return httpx.Response(
                200,
                json={
                    "access_token": self.valid_token,
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "openid profile email",
                },
                request=request
            )

        # 3. Userinfo endpoint
        if url_path in ("/oauth/userinfo", "/apps/oidc/userinfo", "/ocs/v2.php/cloud/user"):
            auth_header = request.headers.get("authorization", "")
            if not auth_header.startswith("Bearer ") or auth_header[7:].strip() != self.valid_token:
                return httpx.Response(401, json={"error": "invalid_token"}, request=request)

            if self.simulate_malformed_json:
                return httpx.Response(200, content=b"corrupt-data", headers={"content-type": "application/json"}, request=request)

            return httpx.Response(200, json=self.user_claims, request=request)

        return httpx.Response(404, text=f"Unknown mock path: {url_path}", request=request)
