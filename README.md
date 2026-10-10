# RememberBot - Persistent Agentic AI Chat

[![Build Status](https://img.shields.io/github/actions/workflow/status/peez80/rememberbot/main.yml?branch=main)](https://github.com/peez80/rememberbot/actions)
[![Docker Pulls](https://img.shields.io/docker/pulls/peez/rememberbot)](https://hub.docker.com/r/peez/rememberbot)

A modern, web-based AI agentic chat with persistent Memory. The application uses the `antigravity-cli` (`agy`) as an AI backend to intelligently parse user input (both text and images) into structured data.

<!-- 
## Screenshots
![RememberBot Chat Interface](docs/images/screenshot.png) 
-->

## Origin Story

I originally started this project to use the normal Gemini web chat as a nutrition diary. However, after about two months, I realized that while Gemini has a long context window, it struggles to export data beyond the last few days. Furthermore, the standard web chat doesn't allow the use of MCP servers or other custom tools. 

I loved the agentic behavior of the `gemini` / `antigravity` CLI, and I wanted to bring exactly those powerful capabilities—persistent local memory and tool use—into a convenient web-based chat UI. Thus, RememberBot was born.

## Features
- **Conversational Interface**: Interact with your AI agent just by chatting.
- **Real-Time Live Streaming & Low-Latency Turns**: Experience smooth token-by-token output streaming powered by `agy --output-format stream-json` and Server-Sent Events (SSE). Multi-turn conversations run with minimal latency via native `agy --conversation` context continuation without re-parsing chat history on every turn.
- **High-Performance Chat Loading**: Lightning-fast session switching with progressive rendering (20-message initial batch with seamless infinite scroll) and $O(1)$ direct session lookup.
- **Automatic Thumbnail Generation & Caching**: Fast image loading with on-demand generated thumbnails (max 400px, EXIF-transposed, transparent-safe JPEG), long-term HTTP caching (`immutable`), and full-resolution viewing in a new tab.
- **Universal File & Image Support**: Attach arbitrary files (documents, PDFs, spreadsheets, CSVs, code files, archives) and pictures (with or without text captions) for automatic recognition and processing. Supports file attachments via dedicated 3-button bar (📎 Paperclip, 🖼️ Gallery, 📷 Mobile Camera), drag-and-drop, and clipboard paste. The AI agent can inspect and work with uploaded files directly.
- **Session Export & Import (ZIP Archives)**: Easily back up or migrate complete chat sessions as compact ZIP archives (including messages, settings, custom icons, uploaded attachments, and AI-generated files, while omitting regenerable thumbnails). Import archives into fresh chat sessions with automatic URL and path remapping, ZipSlip protection, and cross-user/cross-instance portability.
- **Modular Authentication & OpenID Connect SSO**: Support for simple file-based authentication (`users.json`) or enterprise Single Sign-On via standard OpenID Connect / OAuth 2.0 (Nextcloud, Keycloak, Authentik, Zitadel, GitLab, Google) hardened with PKCE (RFC 7636) and CSRF protection.
- **Hardened Security Architecture**: Defense-in-depth security including strict session ID validation against path traversal, timing-attack-resistant authentication, sandboxed Content Security Policy (CSP) and nosniff headers for user uploads and generated files, streaming Zip-Bomb and DoS defense, and DOMPurify with Subresource Integrity (SRI).
- **Smart Parsing**: Powered by Google's Gemini models via the `antigravity-cli`, extracting structured data automatically.
- **Responsive Web App**: Built with vanilla HTML/JS/CSS for a fast, responsive user experience.

## Tech Stack
- **Backend**: Python, FastAPI, Pillow
- **Frontend**: HTML, CSS, JavaScript (Vanilla)
- **AI Integration**: `antigravity-cli` (`agy`)
- **Containerization**: Docker, Docker Compose

## Setup and Installation

### Prerequisites
- Docker and Docker Compose installed on your system.
- The `antigravity-cli` must be configured locally. The Docker container mounts your local config `~/.gemini/antigravity-cli` to authenticate and run the backend. 
  - *Tip:* If you don't have the CLI installed on your host system, you can initialize it directly through the container by running:
    ```bash
    docker compose run --rm web agy setup
    ```
    (This will interactively guide you through the setup and populate the mounted `~/.gemini/antigravity-cli` directory on your host).

### Running the Application
The application is fully containerized and can be started with Docker Compose:

1. Clone the repository and navigate into the project directory.
2. Build and start the containers:
   ```bash
   docker compose up --build
   ```
3. Open your web browser and navigate to `http://localhost:8000`.

### Data Storage
Data such as logged conversations and parsed information are stored in the local `_rememberbot_data` directory, which is mapped into the container. The data is stored isolated in separate subfolders for each user (e.g., `data/alice/sessions`).

### User Management
The application supports multi-user authentication without self-registration through modular user backends (`USER_BACKEND` environment variable).

#### 1. File-based Backend (`USER_BACKEND=json` or `file`)
- Reads users and passwords from `users.json` located under `data/config/users.json` (or `_rememberbot_data/config/users.json` when running via Docker Compose).
- A custom path to the users file can optionally be specified via `USERS_FILE_PATH`.

Example `users.json`:
```json
{
  "alice": "secret123",
  "bob": "password"
}
```

> [!WARNING]
> **Security Note:** Passwords in `users.json` are stored in plain text. This authentication mechanism is intended for local or personal use only.

#### 2. OpenID Connect & OAuth 2.0 Backend (`USER_BACKEND=oauth`, `oidc`, or `nextcloud`)
- Connects to any standard OpenID Connect (OIDC) or OAuth 2.0 identity provider, including **Nextcloud** (with the *OpenID Connect Provider* app), **Keycloak**, **Authentik**, **Zitadel**, **GitLab**, or **Google**.
- Employs **PKCE (RFC 7636)** and cryptographically secure state cookies for CSRF protection.
- Automatically resolves endpoints via OIDC Discovery (`/.well-known/openid-configuration` or `/index.php/.well-known/openid-configuration`).
- Hides the password login form and provides a single-click SSO button in the UI (`Mit Nextcloud anmelden` / `Mit SSO anmelden`).

Example `.env` configuration for Nextcloud OIDC:
```env
USER_BACKEND=oauth
OAUTH_CLIENT_ID=your-nextcloud-client-id
OAUTH_CLIENT_SECRET=your-nextcloud-client-secret
OAUTH_ISSUER_URL=https://nextcloud.example.com
OAUTH_REDIRECT_URI=https://rememberbot.example.com/api/auth/oauth/callback
OAUTH_PROVIDER_NAME=Nextcloud
OAUTH_SCOPE=openid profile email
OAUTH_USERNAME_CLAIM=preferred_username
COOKIE_SECURE=true
```

## Architecture

RememberBot follows a clean, modular multi-tier architecture. See [`docs/architecture.md`](docs/architecture.md) for the complete architectural blueprint and diagrams.

- **`app/core/`**: Centralized configuration (`config.py`), task supervision (`BackgroundSupervisor`), and formatting utilities.
- **`app/models/`**: Strongly typed Pydantic domain models for auth, sessions, and chat.
- **`app/services/`**: Decoupled service layer (`auth_service`, `storage_service`, `session_service`, `agy_service`, `chat_service`).
- **`app/services/oauth/`**: OpenID Connect & OAuth 2.0 client (`OAuthClient`) with automatic discovery, PKCE, and claim sanitization.
- **`app/services/user_backends/`**: Modular user backend providers (`BaseUserBackend`, `JsonUserBackend`, `OAuthUserBackend`, factory registry).
- **`app/routers/`**: Dedicated FastAPI APIRouters (`auth`, `sessions`, `files`, `chat`).
- **`app/storage.py` & `app/agy_client.py`**: Lean, backward-compatible facades delegating cleanly to the service layer.
- **`app/main.py`**: Lean application entry point and middleware configuration.
- **`app/static/js/`**: Modular Vanilla ES6 frontend (`state`, `api`, `components`, `utils`).
- **`app/logging_config.py`**: Centralized structured logging.

## Configuration & Environment Variables

RememberBot is fully configurable via environment variables. To customize settings, copy the provided `.env.example` file to `.env`:

```bash
cp .env.example .env
```

Docker Compose automatically loads variables from `.env`.

### Environment Variables Reference

| Variable | Type | Default | Description |
|---|---|---|---|
| `USER_BACKEND` | `str` | `json` | Active user backend (`json`, `file`, `oauth`, `oidc`, `nextcloud`). |
| `USERS_FILE_PATH` | `str` | *(empty)* | Optional custom path to `users.json` (default: `${DATA_DIR}/config/users.json`). |
| `OAUTH_CLIENT_ID` | `str` | *(empty)* | OAuth 2.0 / OIDC Client Identifier. |
| `OAUTH_CLIENT_SECRET` | `str` | *(empty)* | OAuth 2.0 / OIDC Client Secret (confidential clients). |
| `OAUTH_ISSUER_URL` | `str` | *(empty)* | Base Issuer URL for automatic OIDC discovery (e.g. `https://cloud.example.com`). |
| `OAUTH_DISCOVERY_URL` | `str` | *(empty)* | Optional explicit URL to `openid-configuration` (bypasses discovery resolution). |
| `OAUTH_REDIRECT_URI` | `str` | *(empty)* | Explicit external redirect callback URI (recommended behind reverse proxies). |
| `OAUTH_AUTHORIZE_URL` | `str` | *(empty)* | Optional explicit authorization endpoint override. |
| `OAUTH_TOKEN_URL` | `str` | *(empty)* | Optional explicit token endpoint override. |
| `OAUTH_USERINFO_URL` | `str` | *(empty)* | Optional explicit userinfo endpoint override. |
| `OAUTH_SCOPE` | `str` | `openid profile email` | Requested OAuth scopes (space-delimited). |
| `OAUTH_USERNAME_CLAIM` | `str` | `preferred_username` | Primary ID token/userinfo claim for username (fallbacks: `sub`, `email`). |
| `OAUTH_PROVIDER_NAME` | `str` | `SSO` | Display name of the identity provider on the UI button (e.g. `Nextcloud`). |
| `DATA_DIR` | `str` | `/app/data` | Directory path for persistent data. |
| `SESSION_COOKIE_NAME` | `str` | `session_token` | Name of the authentication session cookie. |
| `SESSION_MAX_AGE_SECONDS` | `int` | `2592000` | Session cookie maximum age in seconds (30 days). |
| `COOKIE_SECURE` | `bool` | `false` | Enforce `Secure` attribute on cookies (requires HTTPS). |
| `MAX_LOGIN_ATTEMPTS` | `int` | `5` | Maximum failed logins before temporary rate-limiting lockout. |
| `LOGIN_RATE_WINDOW_SECONDS` | `int` | `60` | Sliding window in seconds for login rate-limiting. |
| `MAX_UPLOADS_PER_MESSAGE` | `int` | `10` | Maximum file attachments allowed per chat message. |
| `MAX_UPLOAD_FILE_SIZE` | `int` | `26214400` | Maximum single file upload size in bytes (25 MB). |
| `MAX_ZIP_UPLOAD_SIZE` | `int` | `2097152000` | Maximum session ZIP archive import size in bytes (2000 MB). |
| `MAX_ZIP_FILES_COUNT` | `int` | `10000` | Maximum file count inside imported archives (Zip-Bomb defense). |
| `MAX_ZIP_UNCOMPRESSED_BYTES` | `int` | `10485760000` | Maximum uncompressed archive payload in bytes (10000 MB). |
| `THUMBNAIL_MAX_DIMENSION` | `int` | `400` | Maximum width/height in pixels for cached thumbnails. |
| `AGY_EXECUTABLE_PATH` | `str` | `agy` | Command or path to the `antigravity-cli` executable. |
| `AGY_CONVERSATIONS_DIR` | `str` | `~/.gemini/...` | Path to `antigravity-cli` conversations database directory. |
| `AGY_DEFAULT_MODEL` | `str` | `gemini-3.8-flash` | Global default model passed to `agy` CLI (`gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.1-pro`, `claude-sonnet-4-6`, `claude-opus-4-6-thinking`, `gpt-oss-120b-medium`). |
| `AGY_DEFAULT_THINKING_EFFORT` | `str` | `medium` | Default reasoning depth for models with thinking support (`low`, `medium`, `high`). |
| `ICON_GENERATION_TIMEOUT_SECONDS` | `float` | `180.0` | Timeout in seconds for background icon generation. |
| `LOG_LEVEL` | `str` | `INFO` | Log severity level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). |
| `LOG_FORMAT` | `str` | `text` | Log format: `text` (human-readable) or `json` (structured NDJSON). |
| `CORS_ALLOWED_ORIGINS` | `list[str]` | `http://localhost:8000,http://127.0.0.1:8000` | Comma-separated list of allowed CORS origins. |

> [!NOTE]
> **Per-Session Customization:** In addition to environment defaults, users can configure the model and thinking effort per chat session via the session settings modal (⚙️ icon). The active session's model and effort are shown as a badge in the chat header.

## CI/CD Pipeline

The project uses GitHub Actions for continuous integration and deployment with a multi-stage Docker setup:
- **Multi-Stage Builds**: The `Dockerfile` separates the lean `production` stage (runtime dependencies only) from the `test` stage (Playwright, browser binaries, pytest).
- **Automated Testing & Builds**: On every push, the pipeline builds the `test` image, runs the full automated test suite, and then builds and pushes only the lightweight `production` image.
- **Docker Hub**: Successful builds are automatically published to Docker Hub under [`peez/rememberbot`](https://hub.docker.com/r/peez/rememberbot).
- **Versioning Strategy**: Docker images are automatically tagged based on the short Git commit SHA and a timestamp (e.g., `peez/rememberbot:<sha>-<timestamp>`). Builds from the default branch also receive the `latest` tag.
- **Manual Triggers**: Workflows can also be triggered manually (`workflow_dispatch`) from the GitHub Actions interface.

## Testing

The project uses `pytest` and `Playwright` for automated testing. Tests are cleanly separated into three tiers with corresponding directories and `pytest` markers:

- **Unit Tests (`tests/unit/`, marker: `unit`)**: Fast, isolated tests (<3s) for domain models, services, formatters, tasks, and CLI parsing without external services or browsers.
- **Integration Tests (`tests/integration/`, marker: `integration`)**: In-process API tests (<25s) using FastAPI `TestClient` / `AsyncClient` for routing, security middleware, file uploads, caching headers, and rate limiting.
- **End-to-End Tests (`tests/e2e/`, marker: `e2e`)**: Playwright browser tests (~1-2m) verifying live UI behavior, thinking boxes, progressive streaming rendering, DOM persistence, and user concurrency in headless Chromium.

### Running Tests

Use Docker Compose to execute `pytest` within the container environment:

**Run all tests:**
```bash
docker compose run --rm web pytest tests/
```

**Run only fast Unit Tests (<3s):**
```bash
docker compose run --rm web pytest tests/unit
# or via marker:
docker compose run --rm web pytest -m unit
```

**Run API & Integration Tests:**
```bash
docker compose run --rm web pytest tests/integration
# or via marker:
docker compose run --rm web pytest -m integration
```

**Run all fast tests (Unit + Integration, without browser):**
```bash
docker compose run --rm web pytest -m "not e2e"
```

**Run only Playwright E2E Browser Tests:**
```bash
docker compose run --rm web pytest tests/e2e
# or via marker:
docker compose run --rm web pytest -m e2e
```

> [!TIP]
> **Hinweis bei WSL & unendlich hängenden Tests:** Falls Tests über `docker compose` nicht beendet werden (ewig hängen), liegt das meist daran, dass die CLI unter WSL im Docker-Container läuft und NAT'ing-Probleme verursacht. Starte die Tests in diesem Fall mit `--net=host`:
> ```bash
> docker compose run --rm --net=host web pytest tests/
> ```



