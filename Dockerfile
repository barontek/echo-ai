FROM python:3.13-slim

# Create non-root user
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash appuser

WORKDIR /app

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy pyproject only (no lockfile - generate during build)
COPY pyproject.toml ./

# Install dependencies into .venv
RUN uv pip install . --system

# Copy project files
COPY --chown=appuser:appgroup . .

# Ensure data directory exists (used as mount point for echo_data volume)
RUN mkdir -p /root/.echo-ai/sessions /root/.echo-ai/memory

# Switch to non-root user
USER appuser

# Expose FastAPI web backend
EXPOSE 8080

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1
