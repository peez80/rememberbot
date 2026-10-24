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
EFFORT_SUFFIXES = ("-low", "-medium", "-high", "-xhigh", "-max")

DEFAULT_MODEL_CATALOG = {
    "gemini-4-argon-medium": {
        "label": "Gemini 4 Argon (Medium)",
        "allowed_efforts": [],
        "default_effort": None,
        "supports_thinking": False,
    },
    "gemini-4-argon-high": {
        "label": "Gemini 4 Argon (High)",
        "allowed_efforts": [],
        "default_effort": None,
        "supports_thinking": False,
    },
    "gemini-4-argon-low": {
        "label": "Gemini 4 Argon (Low)",
        "allowed_efforts": [],
        "default_effort": None,
        "supports_thinking": False,
    },
    "gemini-3.8-flash-high": {
        "label": "Gemini 3.8 Flash (High)",
        "allowed_efforts": [],
        "default_effort": None,
        "supports_thinking": False,
    },
    "gemini-3.8-flash-medium": {
        "label": "Gemini 3.8 Flash (Medium)",
        "allowed_efforts": [],
        "default_effort": None,
        "supports_thinking": False,
    },
    "gemini-3.8-flash-low": {
        "label": "Gemini 3.8 Flash (Low)",
        "allowed_efforts": [],
        "default_effort": None,
        "supports_thinking": False,
    },
    "claude-opus-5-5-low": {
        "label": "Claude Opus 5.5 (Low)",
        "allowed_efforts": [],
        "default_effort": None,
        "supports_thinking": False,
    },
    "claude-opus-5-5-medium": {
        "label": "Claude Opus 5.5 (Medium)",
        "allowed_efforts": [],
        "default_effort": None,
        "supports_thinking": False,
    },
    "claude-opus-5-5-high": {
        "label": "Claude Opus 5.5 (High)",
        "allowed_efforts": [],
        "default_effort": None,
        "supports_thinking": False,
    },
    "claude-sonnet-5-5-low": {
        "label": "Claude Sonnet 5.5 (Low)",
        "allowed_efforts": [],
        "default_effort": None,
        "supports_thinking": False,
    },
    "claude-sonnet-5-5-medium": {
        "label": "Claude Sonnet 5.5 (Medium)",
        "allowed_efforts": [],
        "default_effort": None,
        "supports_thinking": False,
    },
    "claude-sonnet-5-5-high": {
        "label": "Claude Sonnet 5.5 (High)",
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

AGY_DEFAULT_THINKING_EFFORT = get_env_str("AGY_DEFAULT_THINKING_EFFORT", "medium").lower()
_raw_default_model = get_env_str("AGY_DEFAULT_MODEL", "gemini-3.8-flash-medium")
if (
    _raw_default_model not in DEFAULT_MODEL_CATALOG
    and f"{_raw_default_model}-{AGY_DEFAULT_THINKING_EFFORT}" in DEFAULT_MODEL_CATALOG
):
    AGY_DEFAULT_MODEL = f"{_raw_default_model}-{AGY_DEFAULT_THINKING_EFFORT}"
elif (
    _raw_default_model not in DEFAULT_MODEL_CATALOG
    and f"{_raw_default_model}-medium" in DEFAULT_MODEL_CATALOG
):
    AGY_DEFAULT_MODEL = f"{_raw_default_model}-medium"
else:
    AGY_DEFAULT_MODEL = _raw_default_model

# --- Network & CORS Settings ---
CORS_ALLOWED_ORIGINS = get_env_list(
    "CORS_ALLOWED_ORIGINS",
    ["http://localhost:8000", "http://127.0.0.1:8000"]
)

MODEL_CATALOG = {
    "default": {
        "label": f"Standard (Server-Default: {AGY_DEFAULT_MODEL})",
        "allowed_efforts": [],
        "default_effort": None,
        "supports_thinking": False,
    },
    **DEFAULT_MODEL_CATALOG,
}


def parse_agy_models_output(raw_output: str) -> dict[str, dict]:
    """
    Parses the stdout of `agy models` into a MODEL_CATALOG-compatible dictionary.
    Handles carriage-return spinner prefixes, ANSI escape sequences, and tab/multi-space column separation.
    """
    parsed: dict[str, dict] = {
        "default": {
            "label": f"Standard (Server-Default: {AGY_DEFAULT_MODEL})",
            "allowed_efforts": [],
            "default_effort": None,
            "supports_thinking": False,
        }
    }
    if not raw_output:
        return parsed

    ansi_escape_re = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
    for raw_line in raw_output.split("\n"):
        # Take the final segment after any carriage return (spinner overwrite) and strip ANSI codes
        segment = raw_line.split("\r")[-1]
        clean_line = ansi_escape_re.sub("", segment).strip()
        if not clean_line or "fetching available models" in clean_line.lower():
            continue
        parts = re.split(r"\t+|\s{2,}", clean_line, maxsplit=1)
        if len(parts) != 2:
            continue
        model_id, label = parts[0].strip(), parts[1].strip()
        if not model_id or not label or not re.match(r"^[a-zA-Z0-9._-]+$", model_id):
            continue
        parsed[model_id] = {
            "label": label,
            "allowed_efforts": [],
            "default_effort": None,
            "supports_thinking": False,
        }
    return parsed


def validate_model_and_effort(model: str | None, effort: str | None) -> tuple[bool, str | None]:
    """
    Validates whether the requested model and thinking_effort combination is supported.
    Returns (True, None) if valid, or (False, error_message) if invalid.
    """
    if not model or model == "default":
        normalized_model = "default"
    else:
        normalized_model = model.strip()

    normalized_effort = effort.strip().lower() if effort and str(effort).strip() else None
    if normalized_effort == "default":
        normalized_effort = None

    # Allow legacy base model + effort combinations (e.g. "gemini-3.8-flash" + "high")
    if normalized_model not in MODEL_CATALOG and normalized_effort:
        candidate = f"{normalized_model}-{normalized_effort}"
        if candidate in MODEL_CATALOG:
            normalized_model = candidate
            normalized_effort = None
    elif normalized_model not in MODEL_CATALOG and f"{normalized_model}-medium" in MODEL_CATALOG:
        if normalized_effort is None:
            normalized_model = f"{normalized_model}-medium"

    if normalized_model not in MODEL_CATALOG:
        allowed_models = ", ".join(list(MODEL_CATALOG.keys()))
        return False, f"Unbekanntes Modell '{model}'. Erlaubte Modelle: {allowed_models}."

    model_spec = MODEL_CATALOG[normalized_model]
    supports_thinking = model_spec.get("supports_thinking", False)
    allowed_efforts = model_spec.get("allowed_efforts", [])

    if not supports_thinking:
        if normalized_effort is not None:
            # Allow matching suffix effort (e.g. model="gemini-4-argon-high", effort="high")
            if normalized_model.endswith(f"-{normalized_effort}"):
                return True, None
            return (
                False,
                f"Modell '{model_spec.get('label', model)}' unterstützt den Thinking Effort '{effort}' nicht.",
            )
        return True, None

    if not normalized_effort:
        return True, None

    if normalized_effort not in allowed_efforts:
        allowed_str = ", ".join(allowed_efforts)
        return (
            False,
            f"Modell '{model_spec.get('label', model)}' unterstützt den Thinking Effort '{effort}' nicht. Erlaubte Stufen: {allowed_str}.",
        )

    return True, None


def resolve_session_model_and_effort(model: str | None, thinking_effort: str | None) -> tuple[str, str | None]:
    """
    Resolves effective model and thinking effort, migrating legacy base model + effort
    pairs (e.g. 'gemini-3.8-flash' + 'high' -> 'gemini-3.8-flash-high') and falling back
    to AGY_DEFAULT_MODEL for unknown or obsolete model names.
    """
    clean_model = model.strip() if model and isinstance(model, str) else ""
    clean_effort = (
        str(thinking_effort).strip().lower()
        if thinking_effort and str(thinking_effort).strip()
        else None
    )

    if not clean_model or clean_model == "default":
        eff_model = AGY_DEFAULT_MODEL
    elif clean_model in MODEL_CATALOG:
        eff_model = clean_model
    elif clean_effort and f"{clean_model}-{clean_effort}" in MODEL_CATALOG:
        eff_model = f"{clean_model}-{clean_effort}"
    elif f"{clean_model}-{AGY_DEFAULT_THINKING_EFFORT}" in MODEL_CATALOG:
        eff_model = f"{clean_model}-{AGY_DEFAULT_THINKING_EFFORT}"
    elif f"{clean_model}-medium" in MODEL_CATALOG:
        eff_model = f"{clean_model}-medium"
    else:
        eff_model = AGY_DEFAULT_MODEL

    spec = MODEL_CATALOG.get(eff_model, {})
    if not spec.get("supports_thinking", False) or eff_model.endswith(EFFORT_SUFFIXES):
        return eff_model, None

    allowed_efforts = spec.get("allowed_efforts", [])
    if clean_effort and clean_effort in allowed_efforts:
        return eff_model, clean_effort

    default_eff = spec.get("default_effort", AGY_DEFAULT_THINKING_EFFORT)
    if default_eff in allowed_efforts:
        return eff_model, default_eff
    return eff_model, allowed_efforts[0] if allowed_efforts else None


# Validation pattern for session IDs: starts with alphanumeric, followed by underscores, and hyphens (1-64 chars)
SESSION_ID_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$')

def is_safe_session_id(session_id: str | None) -> bool:
    """
    Validates that a session_id is a non-empty string consisting only of
    alphanumeric characters, underscores, and hyphens (up to 64 chars),
    and is not a directory traversal token like '.' or '..'.
    """
    if not session_id or not isinstance(session_id, str):
        return False
    return bool(SESSION_ID_PATTERN.match(session_id)) and session_id not in (".", "..")

