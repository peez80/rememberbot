FROM python:3.11-slim AS production

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl jq ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Dynamically install the latest antigravity-cli
RUN if [ "$(uname -m)" = "x86_64" ]; then ARCH="x64"; elif [ "$(uname -m)" = "aarch64" ]; then ARCH="arm64"; else ARCH="$(uname -m)"; fi && \
    LATEST_TAG=$(curl -s https://api.github.com/repos/google-antigravity/antigravity-cli/releases/latest | jq -r .tag_name) && \
    if [ "$LATEST_TAG" = "null" ] || [ -z "$LATEST_TAG" ]; then echo "Failed to fetch latest tag" && exit 1; fi && \
    curl -fsSL "https://github.com/google-antigravity/antigravity-cli/releases/download/${LATEST_TAG}/agy_cli_linux_${ARCH}.tar.gz" -o agy.tar.gz && \
    mkdir -p agy_tmp && \
    tar -xzf agy.tar.gz -C agy_tmp && \
    mv agy_tmp/antigravity /usr/local/bin/agy && \
    chmod +x /usr/local/bin/agy && \
    rm -rf agy.tar.gz agy_tmp

# Copy application code
COPY app/ ./app/

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/app/data

# Expose port
EXPOSE 8000

# Start FastAPI application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Stage 2: Test stage for running tests with Playwright and pytest
FROM production AS test

# Install test dependencies and Playwright browser with dependencies
COPY requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt && \
    playwright install --with-deps chromium

# Copy tests and pytest configuration
COPY tests/ ./tests/
COPY pytest.ini .
