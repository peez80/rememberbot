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

