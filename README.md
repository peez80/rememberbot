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
The application supports multi-user authentication without self-registration. Valid users and their passwords must be configured manually in the `users.json` file located in the persistent data volume, specifically under `data/config/users.json` (or `_rememberbot_data/config/users.json` if running via docker compose).

Example `users.json`:
```json
{
  "alice": "secret123",
  "bob": "password"
}
```
> [!WARNING]
> **Security Note:** Passwords are currently stored in plain text. This authentication mechanism is intended for local or personal use only. Do not use this in a public-facing or production environment without adding proper password hashing.

## Architecture

RememberBot follows a clean, modular multi-tier architecture. See [`docs/architecture.md`](docs/architecture.md) for the complete architectural blueprint and diagrams.

- **`app/core/`**: Configuration, task supervision (`BackgroundSupervisor`), and formatting utilities.
- **`app/models/`**: Strongly typed Pydantic domain models for auth, sessions, and chat.
- **`app/services/`**: Decoupled service layer (`auth_service`, `storage_service`, `session_service`, `agy_service`, `chat_service`).
- **`app/routers/`**: Dedicated FastAPI APIRouters (`auth`, `sessions`, `files`, `chat`).
- **`app/storage.py` & `app/agy_client.py`**: Lean, backward-compatible facades delegating cleanly to the service layer.
- **`app/main.py`**: Lean application entry point and middleware configuration.
- **`app/static/js/`**: Modular Vanilla ES6 frontend (`state`, `api`, `components`, `utils`).
- **`app/logging_config.py`**: Centralized structured logging.

## Configuration & Logging

RememberBot supports the following environment variables:
- `DATA_DIR`: Directory path for persistent data (default: `/app/data`).
- `LOG_LEVEL`: Log severity level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` - default: `INFO`).
- `LOG_FORMAT`: Format of log messages:
  - `text` (default): Human-readable formatted console output (`YYYY-MM-DD HH:MM:SS [LEVEL] logger (file:line) - message`).
  - `json`: Structured NDJSON format for log aggregators (e.g., Loki, ELK, CloudWatch).
- `AGY_DEFAULT_MODEL`: Global default model passed to `agy` CLI (default: `gemini-3.8-flash`). Supported options include Gemini models (`gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.1-pro`), Claude (`claude-sonnet-4-6`, `claude-opus-4-6-thinking`), and GPT (`gpt-oss-120b-medium`).
- `AGY_DEFAULT_THINKING_EFFORT`: Global default reasoning depth for models supporting thinking effort (`low`, `medium`, `high` for Gemini Flash models; `low`, `high` for Gemini 3.1 Pro - default: `medium`). Models without separate effort configuration (Claude, GPT-OSS) automatically omit the effort flag.

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



