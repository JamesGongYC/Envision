"""Modal app: Envision critic agent (manual fire; curator tick drives scheduled)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import modal

APP_NAME = "critic-agent"

# Inline deps — avoid Path(__file__) parent walks (Modal flattens entrypoint to /root/app.py).
_PIP = (
    "psycopg[binary]",
    "shapely",
    "scikit-learn",
    "numpy",
    "httpx",
    "anthropic",
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
    timeout=60 * 60,
)
def critic_agent(trigger: str = "operator") -> dict:
    """Run one critic ReAct cycle. Manual invoke; curator cron uses loop directly."""
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
