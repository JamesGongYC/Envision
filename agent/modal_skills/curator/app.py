"""Modal app: Envision curator (daily evolution pass)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import modal

APP_NAME = "curator"


def _local_paths() -> tuple[Path | None, Path | None, Path | None]:
    p = Path(__file__).resolve()
    if "modal_skills" not in p.parts:
        return None, None, None
    agent_dir = Path(*p.parts[: p.parts.index("modal_skills")])
    return agent_dir, agent_dir / "lib", p.parent


_agent_dir, _agent_lib, _skill_dir = _local_paths()

image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "psycopg[binary]",
    "anthropic",
    "shapely",
    "scikit-learn",
    "numpy",
)
if _agent_dir:
    image = image.add_local_dir(str(_agent_dir), remote_path="/root/agent")
if _skill_dir:
    image = image.add_local_dir(str(_skill_dir), remote_path="/root/skill")
if _agent_lib:
    image = image.add_local_dir(str(_agent_lib), remote_path="/root/agent_lib")

app = modal.App(APP_NAME)
secret = modal.Secret.from_name("envision-neon")


@app.function(
    image=image,
    secrets=[secret],
    timeout=60 * 30,
    schedule=modal.Cron("0 4 * * *"),
)
def curator_cycle() -> dict:
    import sys

    sys.path.insert(0, "/root")
    sys.path.insert(0, "/root/skill")
    sys.path.insert(0, "/root/agent_lib")
    import psycopg

    import run as pipeline

    now = datetime.now(timezone.utc)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as db:
        return pipeline.run(now, db)


@app.local_entrypoint()
def main() -> None:
    print(curator_cycle.remote())
