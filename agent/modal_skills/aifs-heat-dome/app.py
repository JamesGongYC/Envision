"""Modal app: AIFS heat dome detection."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import modal

APP_NAME = "aifs-heat-dome"

_root = os.path.dirname(os.path.abspath(__file__))
_shared = os.path.join(_root, "shared")
if not os.path.isfile(os.path.join(_shared, "image.py")):
    _shared = os.path.join(os.path.dirname(_root), "_shared")
SKILL_DIR = os.path.join(_root, "skill") if os.path.isfile(os.path.join(_root, "skill", "run.py")) else _root
SHARED_DIR = _shared
sys.path.insert(0, SHARED_DIR)
from image import build_aifs_image

image = build_aifs_image(skill_dir=SKILL_DIR, shared_dir=SHARED_DIR)
app = modal.App(APP_NAME)
secret = modal.Secret.from_name("envision-neon")


@app.function(
    image=image,
    secrets=[secret],
    timeout=60 * 45,
    # Schedule disabled: Modal workspace cron limit (5) reached.
    # Enable after plan upgrade: schedule=modal.Cron("25 5,17 * * *"),
)
def ingest_cycle() -> int:
    sys.path.insert(0, "/root/shared")
    sys.path.insert(0, "/root/skill")
    import run as pipeline

    return pipeline.run(datetime.now(timezone.utc))


@app.local_entrypoint()
def main() -> None:
    ingest_cycle.remote()
