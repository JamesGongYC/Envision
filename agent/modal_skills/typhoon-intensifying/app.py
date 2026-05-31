"""Modal app: typhoon intensifying detection (every 3h)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import modal

APP_NAME = "typhoon-intensifying"
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))


def _agent_lib() -> Path | None:
    p = Path(__file__).resolve()
    if "modal_skills" not in p.parts:
        return None
    return Path(*p.parts[: p.parts.index("modal_skills")]) / "lib"


_lib = _agent_lib()
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("psycopg[binary]", "shapely", "anthropic", "numpy")
    .add_local_dir(SKILL_DIR, remote_path="/root/skill")
)
if _lib and _lib.is_dir():
    image = image.add_local_dir(str(_lib), remote_path="/root/agent_lib")

app = modal.App(APP_NAME)
secret = modal.Secret.from_name("envision-neon")


@app.function(
    image=image,
    secrets=[secret],
    timeout=60 * 15,
    schedule=modal.Cron("0 */3 * * *"),
)
def detect_cycle() -> int:
    import sys

    sys.path.insert(0, "/root/skill")
    sys.path.insert(0, "/root/agent_lib")
    import psycopg

    from run import run

    now = datetime.now(timezone.utc)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as conn:
        return run(now, conn)


@app.local_entrypoint()
def main() -> None:
    print(detect_cycle.remote())
