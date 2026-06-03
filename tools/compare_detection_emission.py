#!/usr/bin/env python3
"""
Compare detection emission: run pure run() + emit_forecasts at fixed --now.

Operator regression: capture JSON snapshot before/after skill refactor and diff
(skill_id, probability, geometry, contributing_signal_ids, trace).

Usage:
  python tools/compare_detection_emission.py --skill wildfire-risk-elevated --now 2026-05-30T12:00:00Z
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from agent.evolution.skill_loader import SKILL_FOLDERS, load_skill_run  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL")
FOLDER_TO_DB = {v: k for k, v in SKILL_FOLDERS.items()}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--skill", required=True, help="modal_skills folder name")
    p.add_argument("--now", required=True)
    p.add_argument("--write", action="store_true", help="persist to forecasts")
    args = p.parse_args()

    if not DATABASE_URL:
        print("DATABASE_URL required", file=sys.stderr)
        return 2

    db_skill = FOLDER_TO_DB.get(args.skill)
    if not db_skill:
        print(f"unknown folder {args.skill}", file=sys.stderr)
        return 2

    now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    run_fn = load_skill_run(db_skill)

    sys.path.insert(0, str(REPO_ROOT / "agent" / "lib"))
    from forecast_writer import emit_forecasts

    with psycopg.connect(DATABASE_URL, autocommit=False) as db:
        forecasts = run_fn(now, db)
        payload = [
            {
                "probability": f.probability,
                "geometry": f.geometry,
                "contributing_signal_ids": sorted(f.contributing_signal_ids),
                "trace": f.trace if isinstance(f.trace, dict) else json.loads(f.trace),
            }
            for f in forecasts
        ]
        print(json.dumps({"count": len(payload), "forecasts": payload}, indent=2))
        if args.write:
            n = emit_forecasts(forecasts, db)
            db.commit()
            print(f"wrote {n} row(s) to forecasts", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
