"""Modal app: wildfire risk elevated detection (every 30m)."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import modal

APP_NAME = "wildfire-risk-elevated"
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))


def _agent_lib() -> Path | None:
    p = Path(__file__).resolve()
    if "modal_skills" not in p.parts:
        return None
    return Path(*p.parts[: p.parts.index("modal_skills")]) / "lib"


_lib = _agent_lib()
_shared = Path(__file__).resolve().parent.parent / "_shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from skill_exec_image import build_skill_exec_image  # noqa: E402

image = build_skill_exec_image(agent_lib=_lib, skill_dir=SKILL_DIR)

app = modal.App(APP_NAME)
secret = modal.Secret.from_name("envision-neon")


@app.function(
    image=image,
    secrets=[secret],
    timeout=60 * 20,
    schedule=modal.Cron("*/30 * * * *"),
)
def detect_cycle() -> int:
    import sys

    sys.path.insert(0, "/root")
    sys.path.insert(0, "/root/skill")
    sys.path.insert(0, "/root/agent_lib")
    import psycopg

    from pipeline.priced_emit import emit_priced
    from run import run

    now = datetime.now(timezone.utc)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as conn:
        n = emit_priced(run(now, conn), conn, producer="rule")
        conn.commit()
        return n


@app.local_entrypoint()
def main() -> None:
    print(detect_cycle.remote())
