"""Modal app: Envision critic agent (manual fire; curator tick drives scheduled)."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import modal

APP_NAME = "critic-agent"

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
    .pip_install(*SKILL_EXEC_PIP_PACKAGES)
    .add_local_dir(str(AGENT_DIR), remote_path="/root/agent")
    .add_local_dir(str(AGENTS_DIR), remote_path="/root/agents")
    .add_local_dir(str(PIPELINE_DIR), remote_path="/root/pipeline")
)

app = modal.App(APP_NAME)
secret = modal.Secret.from_name("envision-neon")


@app.function(
    image=image,
    secrets=[secret],
    timeout=60 * 60,
)
def critic_agent(trigger: str = "operator") -> dict:
    """Run one critic ReAct cycle. Manual invoke; curator cron uses loop directly."""
    import sys

    sys.path.insert(0, "/root")
    sys.path.insert(0, "/root/agents")
    sys.path.insert(0, "/root/agent/lib")
    sys.path.insert(0, "/root/agent")

    import psycopg

    from agents.critic.loop import run_critic_loop

    now = datetime.now(timezone.utc)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as db:
        result = run_critic_loop(now, db, trigger=trigger)
        db.commit()
        return {
            "agent_run_id": str(result.agent_run_id),
            "status": result.status,
            "step_count": result.step_count,
            "proposal_ids": result.proposal_ids,
            "error": result.error,
        }


@app.local_entrypoint()
def main() -> None:
    print(critic_agent.remote(trigger="operator"))
