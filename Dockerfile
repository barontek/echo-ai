FROM python:3.13-slim

WORKDIR /app

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy the lockfile and pyproject
COPY pyproject.toml uv.lock ./

# Install dependencies into .venv
RUN uv sync --frozen --no-dev

# Copy project files
COPY . .

# Expose Streamlit (8501) and FastAPI (8000)
EXPOSE 8501 8000

ENV PATH="/app/.venv/bin:$PATH"
