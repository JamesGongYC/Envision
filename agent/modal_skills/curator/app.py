"""Modal app: Envision curator (daily)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import modal

APP_NAME = "curator"
REMOTE_SKILL = "/root/skill"
REMOTE_DETECT = "/root/repo_detect"


REMOTE_AGENT_LIB = "/root/agent_lib"


def _local_paths() -> tuple[Path | None, Path | None, Path | None]:
    """Resolve repo paths at deploy time; skip on container (/root/app.py)."""
    p = Path(__file__).resolve()
    if "modal_skills" not in p.parts:
        return None, None, None
    idx = p.parts.index("modal_skills")
    agent_root = Path(*p.parts[:idx])
    return p.parent, agent_root / "skills" / "detect", agent_root / "lib"


_skill_local, _detect_local, _lib_local = _local_paths()

image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "psycopg[binary]", "anthropic"
)
if _skill_local and _skill_local.is_dir():
    image = image.add_local_dir(str(_skill_local), remote_path=REMOTE_SKILL)
if _detect_local and _detect_local.is_dir():
    image = image.add_local_dir(str(_detect_local), remote_path=REMOTE_DETECT)
if _lib_local and _lib_local.is_dir():
    image = image.add_local_dir(str(_lib_local), remote_path=REMOTE_AGENT_LIB)

app = modal.App(APP_NAME)
secret = modal.Secret.from_name("envision-neon")


@app.function(
    image=image,
    secrets=[secret],
    timeout=60 * 20,
    schedule=modal.Cron("0 4 * * *"),
)
def curator_cycle() -> dict:
    import sys

    sys.path.insert(0, REMOTE_SKILL)
    sys.path.insert(0, REMOTE_AGENT_LIB)
    import psycopg

    from stage_skills import stage_detection_skills

    stage_detection_skills()

    import run as pipeline

    now = datetime.now(timezone.utc)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as db:
        return pipeline.run(now, db)


@app.local_entrypoint()
def main() -> None:
    print(curator_cycle.remote())
