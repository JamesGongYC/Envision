"""Modal app: retention deletes and signal_catalog refresh (daily)."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import modal

APP_NAME = "housekeeping-retention"
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("psycopg[binary]")
    .add_local_dir(SKILL_DIR, remote_path="/root/skill")
)

app = modal.App(APP_NAME)
secret = modal.Secret.from_name("envision-neon")


@app.function(
    image=image,
    secrets=[secret],
    timeout=60 * 15,
    schedule=modal.Cron("0 6 * * *"),
)
def scheduled_run() -> dict:
    import sys

    sys.path.insert(0, "/root/skill")
    import psycopg

    from run import run

    now = datetime.now(timezone.utc)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as conn:
        return run(now, conn)


@app.local_entrypoint()
def main() -> None:
    print(scheduled_run.remote())
