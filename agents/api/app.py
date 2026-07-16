"""Modal ASGI app: operator-gated agent fire + public replay SSE."""
from __future__ import annotations

import sys
from pathlib import Path

import modal

APP_NAME = "envision-agent-api"

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = REPO_ROOT / "agent"
AGENTS_DIR = REPO_ROOT / "agents"
PIPELINE_DIR = REPO_ROOT / "pipeline"
SHARED = AGENT_DIR / "modal_skills" / "_shared"

if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))
from skill_exec_image import SKILL_EXEC_PIP_PACKAGES  # noqa: E402

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(*SKILL_EXEC_PIP_PACKAGES, "fastapi")
    .add_local_dir(str(AGENT_DIR), remote_path="/root/agent")
    .add_local_dir(str(AGENTS_DIR), remote_path="/root/agents")
    .add_local_dir(str(PIPELINE_DIR), remote_path="/root/pipeline")
)

app = modal.App(APP_NAME)
secret = modal.Secret.from_name("envision-neon")


@app.function(
    image=image,
    secrets=[secret],
    timeout=60 * 45,
)
@modal.asgi_app()
def fastapi_app():
    import sys

    sys.path.insert(0, "/root")
    sys.path.insert(0, "/root/agents")
    sys.path.insert(0, "/root/agent/lib")
    sys.path.insert(0, "/root/agent")

    from agents.api.fastapi_app import create_app

    return create_app()
