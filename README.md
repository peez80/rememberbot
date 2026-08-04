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
- **Advanced Image Support**: Upload pictures (with or without text captions) for automatic recognition and processing. On mobile devices, you can use your camera directly to snap and upload photos.
- **Smart Parsing**: Powered by Google's Gemini models via the `antigravity-cli`, extracting structured data automatically.
- **Responsive Web App**: Built with vanilla HTML/JS/CSS for a fast, responsive user experience.

## Tech Stack
- **Backend**: Python, FastAPI
- **Frontend**: HTML, CSS, JavaScript (Vanilla)
- **AI Integration**: `antigravity-cli` (`agy`)
- **Containerization**: Docker, Docker Compose

## Setup and Installation

### Prerequisites
- Docker and Docker Compose installed on your system.
- The `antigravity-cli` must be configured locally. The Docker container mounts your local config `~/.gemini/antigravity-cli` to authenticate and run the backend. 
  - *Tip:* If you don't have the CLI installed on your host system, you can initialize it directly through the container by running:
    ```bash
    docker-compose run --rm web agy setup
    ```
    (This will interactively guide you through the setup and populate the mounted `~/.gemini/antigravity-cli` directory on your host).

### Running the Application
The application is fully containerized and can be started with Docker Compose:

1. Clone the repository and navigate into the project directory.
2. Build and start the containers:
   ```bash
   docker-compose up --build
   ```
3. Open your web browser and navigate to `http://localhost:8000`.

### Data Storage
Data such as logged conversations and parsed information are stored in the local `_rememberbot_data` directory, which is mapped into the container. The data is stored isolated in separate subfolders for each user (e.g., `data/alice/sessions`).

### User Management
The application supports multi-user authentication without self-registration. Valid users and their passwords must be configured manually in the `users.json` file located in the persistent data volume, specifically under `data/config/users.json` (or `_rememberbot_data/config/users.json` if running via docker-compose).

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
- `app/main.py`: The FastAPI application entry point, handling routing and HTTP requests.
- `app/agy_client.py`: The client wrapper for interacting with the `antigravity-cli` via subprocesses.
- `app/storage.py`: Handles saving the structured parsed data locally.
- `app/static/`: Contains the frontend assets (`index.html`, `app.js`, `index.css`).
- `docker-compose.yml`: Defines the services and volume mappings for the Docker environment.

## CI/CD Pipeline

The project uses GitHub Actions for continuous integration and deployment:
- **Automated Testing & Builds**: On every push, the pipeline runs automated tests and builds a new Docker image.
- **Docker Hub**: Successful builds are automatically published to Docker Hub under [`peez/rememberbot`](https://hub.docker.com/r/peez/rememberbot).
- **Versioning Strategy**: Docker images are automatically tagged based on the short Git commit SHA and a timestamp (e.g., `peez/rememberbot:<sha>-<timestamp>`). Builds from the default branch also receive the `latest` tag.
- **Manual Triggers**: Workflows can also be triggered manually (`workflow_dispatch`) from the GitHub Actions interface.

## Testing

The project uses `pytest` and `Playwright` for automated testing, including unit tests, API integration tests, and end-to-end (E2E) browser tests.

To run the test suite, use Docker Compose to execute `pytest` within the container environment:

```bash
docker-compose run --rm web pytest tests/
```

> [!TIP]
> **Hinweis bei WSL & unendlich hängenden Tests:** Falls Tests über `docker compose` nicht beendet werden (ewig hängen), liegt das meist daran, dass die CLI unter WSL im Docker-Container läuft und NAT'ing-Probleme verursacht. Starte die Tests in diesem Fall mit `--net=host`:
> ```bash
> docker-compose run --rm --net=host web pytest tests/
> ```



This will run all tests (both unit tests and Playwright E2E browser tests) together:
- Local storage logic (`tests/test_storage.py`)
- API endpoints and chat behavior (`tests/test_main.py`)
- `agy` CLI interaction and JSON parsing (`tests/test_agy_client.py`)
- UI component static asset integrity (`tests/test_scroll_button.py`)
- End-to-End browser UI interactions via Playwright (`tests/test_scroll_e2e.py`)

To run only the Playwright E2E browser tests:

```bash
docker-compose run --rm web pytest tests/test_scroll_e2e.py
```


