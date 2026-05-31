"""Modal app: ECMWF fire weather derived index (12h cadence)."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import modal

APP_NAME = "ecmwf-fire-weather-derived"
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libeccodes-dev", "libeccodes0")
    .pip_install(
        "cfgrib==0.9.15.0",
        "eccodes==2.39.1",
        "xarray",
        "numpy",
        "scipy",
        "shapely",
        "psycopg[binary]",
        "httpx",
        "ecmwf-opendata",
    )
    .add_local_dir(SKILL_DIR, remote_path="/root/skill")
)

app = modal.App(APP_NAME)
secret = modal.Secret.from_name("envision-neon")


@app.function(
    image=image,
    secrets=[secret],
    timeout=60 * 45,
    schedule=modal.Cron("0 4,16 * * *"),
)
def ingest_cycle() -> int:
    import sys

    sys.path.insert(0, "/root/skill")

    import run as pipeline

    now = datetime.now(timezone.utc)
    return pipeline.run(now)


@app.local_entrypoint()
def main() -> None:
    ingest_cycle.remote()
