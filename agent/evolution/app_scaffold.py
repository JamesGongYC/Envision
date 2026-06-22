"""Deterministic Modal app.py scaffold for generated detection skills."""
from __future__ import annotations


def cron_for_cadence_minutes(minutes: int) -> str:
    if minutes <= 30:
        return "*/30 * * * *"
    if minutes <= 180:
        return "0 */3 * * *"
    return f"0 */{max(1, minutes // 60)} * * *"


def render_app_py(*, folder_name: str, cadence_minutes: int) -> str:
    cron = cron_for_cadence_minutes(cadence_minutes)
    return f'''"""Modal app: {folder_name} (generated detection skill)."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import modal

APP_NAME = "{folder_name}"
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
    schedule=modal.Cron("{cron}"),
)
def detect_cycle() -> int:
    import sys

    sys.path.insert(0, "/root/skill")
    sys.path.insert(0, "/root/agent_lib")
    import psycopg

    from forecast_writer import emit_forecasts
    from run import run

    now = datetime.now(timezone.utc)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as conn:
        n = emit_forecasts(run(now, conn), conn)
        conn.commit()
        return n


@app.local_entrypoint()
def main() -> None:
    print(detect_cycle.remote())
'''
