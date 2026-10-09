import os
import logging
from typing import Dict, Optional, Tuple

from app.core.config import DATA_DIR
from .base import BaseUserBackend
from app.services.oauth.client import OAuthClient

logger = logging.getLogger(__name__)

class OAuthUserBackend(BaseUserBackend):
    """
    User backend implementing OpenID Connect (OIDC) & OAuth 2.0 authentication.
    Delegates credentials and identity flows to OAuthClient.
    """

    is_oauth: bool = True
    is_password_supported: bool = False

    def __init__(
        self,
        data_dir: str = DATA_DIR,
        client: Optional[OAuthClient] = None,
        **kwargs
    ):
        self.data_dir = data_dir
        self.client = client or OAuthClient(**kwargs)

    @property
    def backend_name(self) -> str:
        return "oauth"

    @property
    def provider_name(self) -> str:
        return self.client.provider_name

    def authenticate(self, username: str, password: str) -> bool:
        """Password authentication is not supported in OAuth backend."""
        return False

    def user_exists(self, username: str) -> bool:
        """Checks if a local user directory exists for the user."""
        user_dir = os.path.join(self.data_dir, "users", username)
        return os.path.isdir(user_dir)

    def get_valid_users(self) -> Dict[str, str]:
        """User credential enumeration is not supported for OAuth."""
        return {}

    async def get_authorization_url(self, redirect_uri: str, state: str) -> Tuple[str, str]:
        return await self.client.get_authorization_url(redirect_uri, state)

    async def exchange_code_for_user(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: Optional[str] = None
    ) -> str:
        return await self.client.exchange_code_for_user(
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier
        )
