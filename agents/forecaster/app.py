"""Modal app: Envision forecaster agent (manual fire only — no cron)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import modal

APP_NAME = "forecaster-agent"

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
    timeout=60 * 45,
)
def forecaster_agent(trigger: str = "operator") -> dict:
    """Run one forecaster ReAct cycle. Manual invoke only (no schedule)."""
    import psycopg

    from agents.forecaster.loop import run_forecaster_loop

    now = datetime.now(timezone.utc)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as db:
        result = run_forecaster_loop(now, db, trigger=trigger)
        db.commit()
        return {
            "agent_run_id": str(result.agent_run_id),
            "status": result.status,
            "step_count": result.step_count,
            "emitted_ids": result.emitted_ids,
            "error": result.error,
        }


@app.local_entrypoint()
def main() -> None:
    print(forecaster_agent.remote(trigger="operator"))
