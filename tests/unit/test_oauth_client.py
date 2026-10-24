import pytest
import logging
from tests.mocks.mock_oauth_server import MockOAuthTransport
from app.services.oauth.client import OAuthClient, OAuthError, OAuthConfigurationError

@pytest.mark.asyncio
async def test_oauth_client_discovery_success():
    transport = MockOAuthTransport(issuer_url="https://idp.example.com")
    client = OAuthClient(
        issuer_url="https://idp.example.com",
        client_id="test-client-id",
        client_secret="test-client-secret",
        transport=transport,
    )

    discovery = await client.get_discovery_config()
    assert discovery["authorization_endpoint"] == "https://idp.example.com/oauth/authorize"
    assert discovery["token_endpoint"] == "https://idp.example.com/oauth/token"
    assert discovery["userinfo_endpoint"] == "https://idp.example.com/oauth/userinfo"


@pytest.mark.asyncio
async def test_oauth_client_discovery_fallback_to_index_php():
    transport = MockOAuthTransport(issuer_url="https://idp.example.com", simulate_error="discovery_404")
    client = OAuthClient(
        issuer_url="https://idp.example.com",
        client_id="test-client-id",
        client_secret="test-client-secret",
        transport=transport,
    )

    discovery = await client.get_discovery_config()
    assert discovery["authorization_endpoint"] == "https://idp.example.com/oauth/authorize"
    # Check that both requests were attempted
    paths = [r.url.path for r in transport.request_history]
    assert "/.well-known/openid-configuration" in paths
    assert "/index.php/.well-known/openid-configuration" in paths


@pytest.mark.asyncio
async def test_oauth_client_explicit_endpoints_bypass_discovery():
    transport = MockOAuthTransport(issuer_url="https://idp.example.com")
    client = OAuthClient(
        client_id="test-client-id",
        client_secret="test-client-secret",
        authorize_url="https://custom.example.com/auth",
        token_url="https://custom.example.com/token",
        userinfo_url="https://custom.example.com/userinfo",
        transport=transport,
    )

    url, verifier = await client.get_authorization_url(
        redirect_uri="http://localhost:8000/callback",
        state="xyz123"
    )
    assert url.startswith("https://custom.example.com/auth?")
    assert len(transport.request_history) == 0  # No discovery HTTP requests needed!


@pytest.mark.asyncio
async def test_oauth_client_get_authorization_url_with_pkce():
    transport = MockOAuthTransport(issuer_url="https://idp.example.com")
    client = OAuthClient(
        issuer_url="https://idp.example.com",
        client_id="my-client",
        client_secret="my-secret",
        transport=transport,
    )

    auth_url, code_verifier = await client.get_authorization_url(
        redirect_uri="http://localhost:8000/api/auth/oauth/callback",
        state="secure-state-token"
    )

    assert "https://idp.example.com/oauth/authorize" in auth_url
    assert "response_type=code" in auth_url
    assert "client_id=my-client" in auth_url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fapi%2Fauth%2Foauth%2Fcallback" in auth_url
    assert "state=secure-state-token" in auth_url
    assert "code_challenge=" in auth_url
    assert "code_challenge_method=S256" in auth_url
    assert len(code_verifier) >= 43


@pytest.mark.asyncio
async def test_oauth_client_exchange_code_for_user_success():
    transport = MockOAuthTransport(
        issuer_url="https://idp.example.com",
        client_id="test-client",
        client_secret="test-secret",
        valid_code="valid-code-42",
        valid_token="token-abc",
        user_claims={
            "preferred_username": "alice",
            "sub": "123",
            "email": "alice@example.com"
        }
    )
    client = OAuthClient(
        issuer_url="https://idp.example.com",
        client_id="test-client",
        client_secret="test-secret",
        transport=transport,
    )

    # First get auth url to obtain verifier and challenge
    auth_url, verifier = await client.get_authorization_url(
        redirect_uri="http://localhost:8000/callback",
        state="state-1"
    )
    from urllib.parse import parse_qs, urlparse
    qs = parse_qs(urlparse(auth_url).query)
    transport.set_expected_pkce(qs["code_challenge"][0])

    username = await client.exchange_code_for_user(
        code="valid-code-42",
        redirect_uri="http://localhost:8000/callback",
        code_verifier=verifier
    )
    assert username == "alice"


@pytest.mark.asyncio
async def test_oauth_client_claim_fallback_chain():
    # 1. preferred_username missing, use sub
    transport = MockOAuthTransport(
        issuer_url="https://idp.example.com",
        user_claims={"sub": "sub_user_99"}
    )
    client = OAuthClient(
        issuer_url="https://idp.example.com",
        client_id="test-client-id",
        client_secret="test-client-secret",
        transport=transport,
    )
    username = await client.exchange_code_for_user(
        code="valid-auth-code",
        redirect_uri="http://localhost:8000/callback"
    )
    assert username == "sub_user_99"

    # 2. preferred_username and sub missing, use email
    transport2 = MockOAuthTransport(
        issuer_url="https://idp.example.com",
        user_claims={"email": "charlie@company.org"}
    )
    client2 = OAuthClient(
        issuer_url="https://idp.example.com",
        client_id="test-client-id",
        client_secret="test-client-secret",
        transport=transport2,
    )
    username2 = await client2.exchange_code_for_user(
        code="valid-auth-code",
        redirect_uri="http://localhost:8000/callback"
    )
    assert username2 == "charlie@company.org"


@pytest.mark.asyncio
async def test_oauth_client_path_traversal_sanitization():
    transport = MockOAuthTransport(
        issuer_url="https://idp.example.com",
        user_claims={"preferred_username": "../../etc/passwd"}
    )
    client = OAuthClient(
        issuer_url="https://idp.example.com",
        client_id="test-client-id",
        client_secret="test-client-secret",
        transport=transport,
    )
    username = await client.exchange_code_for_user(
        code="valid-auth-code",
        redirect_uri="http://localhost:8000/callback"
    )
    assert "/" not in username
    assert ".." not in username
    assert username == "etc_passwd"


@pytest.mark.asyncio
async def test_oauth_client_token_exchange_failure_and_logging(caplog):
    transport = MockOAuthTransport(
        issuer_url="https://idp.example.com",
    )
    transport.simulate_token_status_code = 500
    client = OAuthClient(
        issuer_url="https://idp.example.com",
        client_id="test-client-id",
        client_secret="test-client-secret",
        transport=transport,
    )

    with caplog.at_level(logging.ERROR):
        with pytest.raises(OAuthError) as exc_info:
            await client.exchange_code_for_user(
                code="bad-code",
                redirect_uri="http://localhost:8000/callback"
            )
        assert "OAuth token exchange failed" in str(exc_info.value) or "Token endpoint returned status" in str(exc_info.value)
        # Ensure client_secret was NOT logged
        assert "test-client-secret" not in caplog.text


@pytest.mark.asyncio
async def test_oauth_client_missing_config_raises():
    with pytest.raises(OAuthConfigurationError):
        OAuthClient(client_id="", client_secret="secret")

    with pytest.raises(OAuthConfigurationError):
        OAuthClient(client_id="id", client_secret="")


@pytest.mark.asyncio
async def test_discovery_missing_urls_raises_configuration_error():
    client = OAuthClient(client_id="id", client_secret="sec")
    with pytest.raises(OAuthConfigurationError):
        await client.get_discovery_config()


@pytest.mark.asyncio
async def test_discovery_all_endpoints_fail_raises_oauth_error(caplog):
    transport = MockOAuthTransport(issuer_url="https://idp.example.com", simulate_status_code=404)
    client = OAuthClient(
        issuer_url="https://idp.example.com",
        client_id="client",
        client_secret="secret",
        transport=transport,
    )

    with caplog.at_level(logging.ERROR):
        with pytest.raises(OAuthError) as exc_info:
            await client.get_discovery_config()

    assert "OIDC Discovery fehlgeschlagen" in str(exc_info.value)
    assert "vollständig fehlgeschlagen" in caplog.text


@pytest.mark.asyncio
async def test_exchange_code_network_and_payload_errors(caplog):
    import httpx

    # 1. Network error during token exchange
    class FailingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx.RequestError("Network connection reset", request=request)

    client_failing = OAuthClient(
        issuer_url="https://idp.example.com",
        client_id="client",
        client_secret="secret",
        authorize_url="https://idp.example.com/auth",
        token_url="https://idp.example.com/token",
        userinfo_url="https://idp.example.com/userinfo",
        transport=FailingTransport(),
    )

    with caplog.at_level(logging.ERROR):
        with pytest.raises(OAuthError) as exc_info:
            await client_failing.exchange_code_for_user(code="abc", redirect_uri="http://cb")
        assert "network error" in str(exc_info.value).lower()

    # 2. Token endpoint returns 200 but missing access_token
    class MalformedTokenTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            if "/token" in str(request.url):
                return httpx.Response(200, json={"token_type": "bearer"}, request=request)
            return httpx.Response(404, request=request)

    client_malformed = OAuthClient(
        issuer_url="https://idp.example.com",
        client_id="client",
        client_secret="secret",
        token_url="https://idp.example.com/token",
        userinfo_url="https://idp.example.com/userinfo",
        transport=MalformedTokenTransport(),
    )

    with caplog.at_level(logging.ERROR):
        with pytest.raises(OAuthError) as exc_info:
            await client_malformed.exchange_code_for_user(code="abc", redirect_uri="http://cb")
        assert "access_token" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_extract_username_nextcloud_ocs_and_invalid_claims():
    client = OAuthClient(client_id="client", client_secret="secret")

    # Nextcloud OCS structure
    userinfo_nc = {
        "ocs": {
            "data": {
                "id": "nc_admin"
            }
        }
    }
    assert client._extract_username(userinfo_nc) == "nc_admin"

    # Missing claims entirely raises OAuthError
    with pytest.raises(OAuthError) as exc_info:
        client._extract_username({})
    assert "no valid username claim" in str(exc_info.value).lower()

    # Claim consisting only of dots/slashes sanitizes to empty string -> raises OAuthError
    with pytest.raises(OAuthError) as exc_info:
        client._extract_username({"preferred_username": "...///.."})
    assert "username is invalid" in str(exc_info.value).lower()
