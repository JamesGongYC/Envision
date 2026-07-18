"""Modal ASGI app: operator-gated agent fire + public replay SSE."""
from __future__ import annotations

from pathlib import Path

import modal

APP_NAME = "envision-agent-api"

# Inline deps — avoid Path(__file__) parent walks (Modal flattens entrypoint to /root/app.py).
_PIP = (
    "psycopg[binary]",
    "shapely",
    "scikit-learn",
    "numpy",
    "httpx",
    "anthropic",
    "fastapi",
)


def _ignore_junk(p: Path) -> bool:
    """Exclude caches/dotfiles; keep SKILL.md and other non-.py assets."""
    return (
        p.name.startswith(".")
        or p.name == "__pycache__"
        or p.suffix in {".pyc", ".pyo"}
    )


image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(*_PIP)
    .add_local_python_source(
        "agent",
        "agents",
        "pipeline",
        ignore=_ignore_junk,
    )
)

app = modal.App(APP_NAME)
secret = modal.Secret.from_name("envision-neon")


@app.function(
    image=image,
    secrets=[secret],
    timeout=60 * 8,
)
@modal.asgi_app()
def fastapi_app():
    from agents.api.fastapi_app import create_app

    return create_app()
