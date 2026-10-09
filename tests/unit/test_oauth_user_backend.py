import os
import pytest
from app.services.user_backends.base import BaseUserBackend
from app.services.user_backends.oauth_backend import OAuthUserBackend
from app.services.user_backends.factory import get_user_backend, validate_user_backend
from tests.mocks.mock_oauth_server import MockOAuthTransport
from app.services.oauth.client import OAuthClient

def test_oauth_user_backend_implements_base_backend(tmp_path):
    data_dir = str(tmp_path / "data")
    transport = MockOAuthTransport()
    client = OAuthClient(
        client_id="cid",
        client_secret="sec",
        issuer_url="https://idp.example.com",
        transport=transport
    )
    backend = OAuthUserBackend(data_dir=data_dir, client=client)

    assert isinstance(backend, BaseUserBackend)
    assert backend.backend_name == "oauth"
    assert backend.is_oauth is True
    assert backend.is_password_supported is False

    # Password auth must always return False
    assert backend.authenticate("alice", "any_password") is False
    assert backend.get_valid_users() == {}


def test_oauth_user_backend_user_exists(tmp_path):
    data_dir = str(tmp_path / "data")
    user_dir = tmp_path / "data" / "users" / "alice"
    user_dir.mkdir(parents=True, exist_ok=True)

    transport = MockOAuthTransport()
    client = OAuthClient(
        client_id="cid",
        client_secret="sec",
        issuer_url="https://idp.example.com",
        transport=transport
    )
    backend = OAuthUserBackend(data_dir=data_dir, client=client)

    assert backend.user_exists("alice") is True
    assert backend.user_exists("bob") is False


def test_factory_resolves_oauth_backends(tmp_path):
    data_dir = str(tmp_path / "data")

    # Validation
    assert validate_user_backend("oauth") == "oauth"
    assert validate_user_backend("oidc") == "oidc"
    assert validate_user_backend("nextcloud") == "nextcloud"

    # Instantiation via factory with mock client
    transport = MockOAuthTransport()
    mock_client = OAuthClient(
        client_id="cid",
        client_secret="sec",
        issuer_url="https://idp.example.com",
        transport=transport
    )

    b_oauth = get_user_backend("oauth", data_dir=data_dir, client=mock_client)
    assert isinstance(b_oauth, OAuthUserBackend)

    b_oidc = get_user_backend("oidc", data_dir=data_dir, client=mock_client)
    assert isinstance(b_oidc, OAuthUserBackend)

    b_nc = get_user_backend("nextcloud", data_dir=data_dir, client=mock_client)
    assert isinstance(b_nc, OAuthUserBackend)
