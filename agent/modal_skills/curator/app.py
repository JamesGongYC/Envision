"""Modal app: Envision curator (daily evolution pass)."""
from __future__ import annotations

import os
import sys
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

_shared = Path(__file__).resolve().parent.parent / "_shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from skill_exec_image import build_skill_exec_image  # noqa: E402

image = build_skill_exec_image(
    agent_dir=_agent_dir,
    agent_lib=_agent_lib,
    skill_dir=_skill_dir,
)

app = modal.App(APP_NAME)
secret = modal.Secret.from_name("envision-neon")


@app.function(
    image=image,
    secrets=[secret],
    timeout=60 * 60,
    schedule=modal.Cron("0 4 * * *"),
)
def curator_cycle() -> dict:
    import sys

    sys.path.insert(0, "/root")
    sys.path.insert(0, "/root/skill")
    sys.path.insert(0, "/root/agent_lib")
    sys.path.insert(0, "/root/agent")
    import psycopg

    import run as pipeline

    now = datetime.now(timezone.utc)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as db:
        return pipeline.run(now, db)


@app.local_entrypoint()
def main() -> None:
    print(curator_cycle.remote())
