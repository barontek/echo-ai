"""Legacy web_ui module kept for backward compatibility.

Streamlit UI has been removed. Use the FastAPI static web UI instead.
"""

from src.agentframework.web_api import run_server


def run_app() -> None:
    """Run the FastAPI-based web UI server."""
    run_server(host="0.0.0.0", port=8080)


if __name__ == "__main__":
    run_app()
