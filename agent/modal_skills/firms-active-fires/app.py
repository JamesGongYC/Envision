"""Modal app: NASA FIRMS global hotspots (every 30m)."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import modal

APP_NAME = "firms-active-fires"
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("psycopg[binary]", "httpx")
    .add_local_dir(SKILL_DIR, remote_path="/root/skill")
)

app = modal.App(APP_NAME)
secret = modal.Secret.from_name("envision-neon")


@app.function(
    image=image,
    secrets=[secret],
    timeout=60 * 30,
    cpu=2.0,
    memory=2048,
    schedule=modal.Cron("*/30 * * * *"),
)
def ingest_cycle() -> int:
    import sys

    sys.path.insert(0, "/root/skill")
    import psycopg

    from run import run

    now = datetime.now(timezone.utc)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as conn:
        n, _succeeded = run(now, conn)
        return n


@app.local_entrypoint()
def main() -> None:
    print(ingest_cycle.remote())
