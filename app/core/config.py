import os
import re
import logging

logger = logging.getLogger(__name__)

# --- Typed Environment Helpers ---

def get_env_str(key: str, default: str) -> str:
    """Reads a string environment variable, returning default if unset or empty."""
    val = os.getenv(key)
    if val is None:
        return default
    cleaned = val.strip()
    return cleaned if cleaned else default


def get_env_int(key: str, default: int) -> int:
    """Reads an integer environment variable, logging a warning and returning default on failure."""
    val = os.getenv(key)
    if val is None or not val.strip():
        return default
    try:
        return int(val.strip())
    except ValueError:
        logger.warning(
            f"Ungültiger Integer-Wert für Umgebungsvariable '{key}': '{val}'. "
            f"Verwende Standardwert {default}."
        )
        return default


def get_env_float(key: str, default: float) -> float:
    """Reads a float environment variable, logging a warning and returning default on failure."""
    val = os.getenv(key)
    if val is None or not val.strip():
        return default
    try:
        return float(val.strip())
    except ValueError:
        logger.warning(
            f"Ungültiger Float-Wert für Umgebungsvariable '{key}': '{val}'. "
            f"Verwende Standardwert {default}."
        )
        return default


def get_env_bool(key: str, default: bool) -> bool:
    """Reads a boolean environment variable, logging a warning and returning default on failure."""
    val = os.getenv(key)
    if val is None:
        return default
    normalized = val.strip().lower()
    if normalized in ("true", "1", "yes", "on"):
        return True
    if normalized in ("false", "0", "no", "off"):
        return False
    logger.warning(
        f"Ungültiger Boolean-Wert für Umgebungsvariable '{key}': '{val}'. "
        f"Verwende Standardwert {default}."
    )
    return default


def get_env_list(key: str, default: list[str], sep: str = ",") -> list[str]:
    """Reads a delimited list of strings from an environment variable."""
    val = os.getenv(key)
    if val is None or not val.strip():
        return default
    items = [item.strip() for item in val.split(sep) if item.strip()]
    return items if items else default


# --- Base Persistence & Storage Settings ---
DATA_DIR = get_env_str(
    "DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
)

# --- User Backend & Authentication Configuration ---
USER_BACKEND = get_env_str("USER_BACKEND", "json").lower()
USERS_FILE_PATH = os.getenv("USERS_FILE_PATH", "").strip() or None

# --- OAuth 2.0 & OpenID Connect (OIDC) Settings ---
OAUTH_CLIENT_ID = get_env_str("OAUTH_CLIENT_ID", "")
OAUTH_CLIENT_SECRET = get_env_str("OAUTH_CLIENT_SECRET", "")
OAUTH_ISSUER_URL = get_env_str("OAUTH_ISSUER_URL", "")
OAUTH_DISCOVERY_URL = get_env_str("OAUTH_DISCOVERY_URL", "")
OAUTH_REDIRECT_URI = get_env_str("OAUTH_REDIRECT_URI", "")
OAUTH_AUTHORIZE_URL = get_env_str("OAUTH_AUTHORIZE_URL", "")
OAUTH_TOKEN_URL = get_env_str("OAUTH_TOKEN_URL", "")
OAUTH_USERINFO_URL = get_env_str("OAUTH_USERINFO_URL", "")
OAUTH_SCOPE = get_env_str("OAUTH_SCOPE", "openid profile email")
OAUTH_USERNAME_CLAIM = get_env_str("OAUTH_USERNAME_CLAIM", "preferred_username")
OAUTH_PROVIDER_NAME = get_env_str("OAUTH_PROVIDER_NAME", "SSO")

# --- Logging Settings ---
LOG_LEVEL = get_env_str("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = get_env_str("LOG_FORMAT", "text").lower()

# --- Security & Cookie Settings ---
COOKIE_SECURE = get_env_bool("COOKIE_SECURE", False)
SESSION_COOKIE_NAME = get_env_str("SESSION_COOKIE_NAME", "session_token")
SESSION_MAX_AGE_SECONDS = get_env_int("SESSION_MAX_AGE_SECONDS", 30 * 24 * 60 * 60)  # 30 days

# --- Rate Limiting Limits ---
MAX_LOGIN_ATTEMPTS = get_env_int("MAX_LOGIN_ATTEMPTS", 5)
LOGIN_RATE_WINDOW_SECONDS = get_env_int("LOGIN_RATE_WINDOW_SECONDS", 60)

# --- Upload Limits ---
MAX_UPLOADS_PER_MESSAGE = get_env_int("MAX_UPLOADS_PER_MESSAGE", 10)
MAX_UPLOAD_FILES_PER_REQUEST = MAX_UPLOADS_PER_MESSAGE
MAX_UPLOAD_FILE_SIZE = get_env_int("MAX_UPLOAD_FILE_SIZE", 25 * 1024 * 1024)  # 25 MB
MAX_SINGLE_FILE_SIZE = MAX_UPLOAD_FILE_SIZE
MAX_ZIP_UPLOAD_SIZE = get_env_int("MAX_ZIP_UPLOAD_SIZE", 2000 * 1024 * 1024)  # 2000 MB
MAX_ZIP_FILES_COUNT = get_env_int("MAX_ZIP_FILES_COUNT", 10000)
MAX_ZIP_UNCOMPRESSED_BYTES = get_env_int("MAX_ZIP_UNCOMPRESSED_BYTES", 10000 * 1024 * 1024)  # 10000 MB
THUMBNAIL_MAX_DIMENSION = get_env_int("THUMBNAIL_MAX_DIMENSION", 400)

# --- AI & Generation Timeouts ---
ICON_GENERATION_TIMEOUT_SECONDS = get_env_float("ICON_GENERATION_TIMEOUT_SECONDS", 180.0)

# --- AI Models, Thinking Effort & CLI Paths ---
AGY_EXECUTABLE_PATH = get_env_str("AGY_EXECUTABLE_PATH", "agy")
AGY_CONVERSATIONS_DIR = get_env_str(
    "AGY_CONVERSATIONS_DIR",
    os.path.expanduser("~/.gemini/antigravity-cli/conversations")
)
AGY_DEFAULT_MODEL = get_env_str("AGY_DEFAULT_MODEL", "gemini-3.8-flash")
AGY_DEFAULT_THINKING_EFFORT = get_env_str("AGY_DEFAULT_THINKING_EFFORT", "medium").lower()

# --- Network & CORS Settings ---
CORS_ALLOWED_ORIGINS = get_env_list(
    "CORS_ALLOWED_ORIGINS",
    ["http://localhost:8000", "http://127.0.0.1:8000"]
)

MODEL_CATALOG = {
    "default": {
        "label": f"Standard (Server-Default: {AGY_DEFAULT_MODEL})",
        "allowed_efforts": ["low", "medium", "high"],
        "default_effort": AGY_DEFAULT_THINKING_EFFORT,
        "supports_thinking": True,
    },
    "gemini-3.1-pro": {
        "label": "Gemini 3.1 Pro",
        "allowed_efforts": ["low", "high"],
        "default_effort": "high",
        "supports_thinking": True,
    },
    "gemini-3.8-flash": {
        "label": "Gemini 3.8 Flash",
        "allowed_efforts": ["low", "medium", "high"],
        "default_effort": "medium",
        "supports_thinking": True,
    },
    "gemini-3.7-flash": {
        "label": "Gemini 3.7 Flash",
        "allowed_efforts": ["low", "medium", "high"],
        "default_effort": "high",
        "supports_thinking": True,
    },
    "claude-sonnet-4-6": {
        "label": "Claude Sonnet 4.6 (Thinking)",
        "allowed_efforts": [],
        "default_effort": None,
        "supports_thinking": False,
    },
    "claude-opus-4-6-thinking": {
        "label": "Claude Opus 4.6 (Thinking)",
        "allowed_efforts": [],
        "default_effort": None,
        "supports_thinking": False,
    },
    "gpt-oss-120b-medium": {
        "label": "GPT-OSS 120B (Medium)",
        "allowed_efforts": [],
        "default_effort": None,
        "supports_thinking": False,
    },
}

def validate_model_and_effort(model: str | None, effort: str | None) -> tuple[bool, str | None]:
    """
    Validates whether the requested model and thinking_effort combination is supported.
    Returns (True, None) if valid, or (False, error_message) if invalid.
    """
    if not model or model == "default":
        normalized_model = "default"
    else:
        normalized_model = model.strip()

    if normalized_model not in MODEL_CATALOG:
        allowed_models = ", ".join(list(MODEL_CATALOG.keys()))
        return False, f"Unbekanntes Modell '{model}'. Erlaubte Modelle: {allowed_models}."

    model_spec = MODEL_CATALOG[normalized_model]
    supports_thinking = model_spec.get("supports_thinking", True)
    allowed_efforts = model_spec.get("allowed_efforts", [])

    # If the model does not support manual thinking effort (e.g. Claude, GPT-OSS)
    if not supports_thinking:
        if effort is not None and str(effort).strip() != "" and str(effort).strip().lower() != "default":
            return False, f"Modell '{model_spec.get('label', model)}' unterstützt keine manuelle Thinking-Effort-Einstellung."
        return True, None

    # Model supports thinking
    if not effort or effort == "default":
        return True, None

    normalized_effort = effort.strip().lower()
    if normalized_effort not in allowed_efforts:
        allowed_str = ", ".join(allowed_efforts)
        return False, f"Modell '{model_spec.get('label', model)}' unterstützt den Thinking Effort '{effort}' nicht. Erlaubte Stufen: {allowed_str}."

    return True, None


def resolve_session_model_and_effort(model: str | None, thinking_effort: str | None) -> tuple[str, str | None]:
    """
    Resolves effective model and thinking effort, falling back to defaults if not set
    or if an obsolete/unknown model name is provided.
    """
    if not model or model == "default" or model not in MODEL_CATALOG:
        eff_model = AGY_DEFAULT_MODEL
    else:
        eff_model = model.strip()

    spec = MODEL_CATALOG.get(eff_model, {})
    if not spec.get("supports_thinking", True):
        return eff_model, None

    allowed_efforts = spec.get("allowed_efforts", [])
    if thinking_effort and str(thinking_effort).strip().lower() in allowed_efforts:
        return eff_model, str(thinking_effort).strip().lower()

    default_eff = spec.get("default_effort", AGY_DEFAULT_THINKING_EFFORT)
    if default_eff in allowed_efforts:
        return eff_model, default_eff
    return eff_model, allowed_efforts[0] if allowed_efforts else None


# Validation pattern for session IDs: alphanumeric, underscores, and hyphens (1-64 chars)
SESSION_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')

def is_safe_session_id(session_id: str | None) -> bool:
    """
    Validates that a session_id is a non-empty string consisting only of
    alphanumeric characters, underscores, and hyphens (up to 64 chars),
    and is not a directory traversal token like '.' or '..'.
    """
    if not session_id or not isinstance(session_id, str):
        return False
    return bool(SESSION_ID_PATTERN.match(session_id)) and session_id not in (".", "..")

