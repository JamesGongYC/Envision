"""Modal app: generic shadow runner (30m wildfire + 3h typhoon buckets)."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import modal

APP_NAME = "shadow-runner"


def _local_paths() -> tuple[Path | None, Path | None]:
    p = Path(__file__).resolve()
    if "modal_skills" not in p.parts:
        return None, None
    agent_dir = Path(*p.parts[: p.parts.index("modal_skills")])
    return agent_dir, agent_dir / "lib"


_agent_dir, _agent_lib = _local_paths()

_shared = Path(__file__).resolve().parent.parent / "_shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from skill_exec_image import build_skill_exec_image  # noqa: E402

image = build_skill_exec_image(agent_dir=_agent_dir, agent_lib=_agent_lib)

app = modal.App(APP_NAME)
secret = modal.Secret.from_name("envision-neon")


def _run_bucket(cadence_minutes: int) -> int:
    import sys

    sys.path.insert(0, "/root")
    sys.path.insert(0, "/root/agent_lib")

    from agent.evolution.shadow_runner import run_shadow_bucket

    import psycopg

    cadence = timedelta(minutes=cadence_minutes)
    now = datetime.now(timezone.utc)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as db:
        n = run_shadow_bucket(cadence, now, db)
        db.commit()
        return n


@app.function(
    image=image,
    secrets=[secret],
    timeout=60 * 20,
    schedule=modal.Cron("*/30 * * * *"),
)
def shadow_wildfire_cycle() -> int:
    return _run_bucket(30)


@app.function(
    image=image,
    secrets=[secret],
    timeout=60 * 20,
    schedule=modal.Cron("0 */3 * * *"),
)
def shadow_typhoon_cycle() -> int:
    return _run_bucket(180)


@app.local_entrypoint()
def main() -> None:
    print("wildfire:", shadow_wildfire_cycle.remote())
    print("typhoon:", shadow_typhoon_cycle.remote())
