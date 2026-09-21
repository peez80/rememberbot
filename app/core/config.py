import os

# Base persistence directory
DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data"))

# Logging settings
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.getenv("LOG_FORMAT", "text").lower()

# Security & Cookie settings
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() in ("true", "1")
SESSION_COOKIE_NAME = "session_token"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30 days

# Rate limiting limits
MAX_LOGIN_ATTEMPTS = 5
LOGIN_RATE_WINDOW_SECONDS = 60

# Upload limits
MAX_UPLOAD_FILES_PER_REQUEST = 10
MAX_UPLOADS_PER_MESSAGE = MAX_UPLOAD_FILES_PER_REQUEST
MAX_SINGLE_FILE_SIZE = 25 * 1024 * 1024  # 25 MB
MAX_UPLOAD_FILE_SIZE = MAX_SINGLE_FILE_SIZE
MAX_ZIP_UPLOAD_SIZE = 500 * 1024 * 1024  # 500 MB
MAX_ZIP_FILES_COUNT = 1000
MAX_ZIP_UNCOMPRESSED_BYTES = 1000 * 1024 * 1024  # 1000 MB

# AI & Generation timeouts
ICON_GENERATION_TIMEOUT_SECONDS = float(os.getenv("ICON_GENERATION_TIMEOUT_SECONDS", "180.0"))

# AI Models & Thinking Effort configuration
AGY_DEFAULT_MODEL = os.getenv("AGY_DEFAULT_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
AGY_DEFAULT_THINKING_EFFORT = os.getenv("AGY_DEFAULT_THINKING_EFFORT", "medium").strip().lower() or "medium"

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
