#!/usr/bin/env python3
"""Document evaluator regression: run twice and compare evaluation batches (operator)."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent" / "lib"))
sys.path.insert(0, str(REPO_ROOT / "agent" / "modal_skills" / "forecast-evaluator"))

from run import run  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL")


def snapshot(db, label: str) -> list[tuple]:
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT forecast_id::text, outcome, brier_contribution
            FROM evaluations
            ORDER BY evaluated_at DESC
            LIMIT 500
            """
        )
        rows = cur.fetchall()
    print(f"[{label}] {len(rows)} evaluation row(s) sampled")
    return rows


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="only print instructions")
    args = p.parse_args()
    if args.dry_run:
        print(
            "Run evaluator once, export evaluations to CSV, refactor scoring.py, "
            "run again on same DB snapshot; diff forecast_id,outcome,brier_contribution."
        )
        return 0
    if not DATABASE_URL:
        print("DATABASE_URL required", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc)
    with psycopg.connect(DATABASE_URL, autocommit=False) as db:
        before = snapshot(db, "before")
        n = run(now, db)
        after = snapshot(db, "after")
    print(f"evaluator run inserted/processed {n} row(s)")
    if before == after:
        print("OK: evaluation sample unchanged (no new unevaluated forecasts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
