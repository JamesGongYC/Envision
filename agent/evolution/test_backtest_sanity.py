#!/usr/bin/env python3
"""
Sanity: backtest Brier vs live evaluations for all 4 detection skills (trailing 7d).

Tolerance ±0.02 — live eval uses 12h grace after valid_until and GT arrival timing;
harness replays cadence deterministically with shared scoring.py matching logic.

Skills with fewer than MIN_EVALS live evaluations in the window are logged as
UNVERIFIED (exit 0) — do not treat as proof of harness parity.

Run from repo root with DATABASE_URL and migration 006 applied:
  python agent/evolution/test_backtest_sanity.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "agent" / "lib"))

from agent.evolution.backtest_harness import SKILL_CADENCE, backtest_skill  # noqa: E402
from agent.lib.repo_env import load_repo_env  # noqa: E402

load_repo_env()

SKILL_IDS = list(SKILL_CADENCE.keys())
TOLERANCE = 0.02
MIN_EVALS = 10
DATABASE_URL = os.environ.get("DATABASE_URL")


def live_brier_and_count(
    db, skill_id: str, window_start: datetime, window_end: datetime
) -> tuple[float | None, int]:
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT AVG(e.brier_contribution)::float, COUNT(*)::int
            FROM evaluations e
            JOIN forecasts f ON f.id = e.forecast_id
            WHERE f.skill_id = %s
              AND e.evaluated_at >= %s
              AND e.evaluated_at <= %s
            """,
            (skill_id, window_start, window_end),
        )
        row = cur.fetchone()
    if not row:
        return None, 0
    return row[0], row[1] or 0


def main() -> int:
    if not DATABASE_URL:
        print("DATABASE_URL required", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=7)
    window_end = now

    print(f"window={window_start.isoformat()} .. {window_end.isoformat()}")
    print(f"tolerance={TOLERANCE} min_evals={MIN_EVALS}")
    print()

    results: list[dict] = []
    any_fail = False
    any_verified = False

    with psycopg.connect(DATABASE_URL, autocommit=False) as db:
        for skill_id in SKILL_IDS:
            live, eval_count = live_brier_and_count(
                db, skill_id, window_start, window_end
            )
            status = "PENDING"

            if eval_count < MIN_EVALS:
                status = "UNVERIFIED"
                print(
                    f"WARN [{skill_id}] only {eval_count} live evals "
                    f"(need {MIN_EVALS}); skipping backtest comparison"
                )
                results.append({
                    "skill_id": skill_id,
                    "live": live,
                    "backtest": None,
                    "delta": None,
                    "eval_count": eval_count,
                    "status": status,
                })
                continue

            runs = backtest_skill(skill_id, [(window_start, window_end)], db)
            backtest = runs[0].brier_score if runs else None

            if live is None or backtest is None:
                status = "UNVERIFIED"
                print(
                    f"WARN [{skill_id}] insufficient data "
                    f"(live={live} backtest={backtest})"
                )
                delta = None
            else:
                any_verified = True
                delta = abs(backtest - live)
                if delta > TOLERANCE:
                    status = "FAIL"
                    any_fail = True
                else:
                    status = "PASS"

            results.append({
                "skill_id": skill_id,
                "live": live,
                "backtest": backtest,
                "delta": delta,
                "eval_count": eval_count,
                "status": status,
            })

    print()
    print(f"{'skill_id':<28} {'live':>8} {'backtest':>10} {'delta':>8} {'evals':>6}  status")
    print("-" * 72)
    for r in results:
        live_s = f"{r['live']:.4f}" if r["live"] is not None else "—"
        bt_s = f"{r['backtest']:.4f}" if r["backtest"] is not None else "—"
        d_s = f"{r['delta']:.4f}" if r["delta"] is not None else "—"
        print(
            f"{r['skill_id']:<28} {live_s:>8} {bt_s:>10} {d_s:>8} "
            f"{r['eval_count']:>6}  {r['status']}"
        )

    unverified = [r["skill_id"] for r in results if r["status"] == "UNVERIFIED"]
    if unverified:
        print()
        print(f"UNVERIFIED (not proof of parity): {', '.join(unverified)}")

    if any_fail:
        print()
        print("FAIL: one or more verifiable skills exceed tolerance")
        return 1

    if not any_verified:
        print()
        print("SKIP: no skill had enough live evals to verify")
        return 0

    print()
    print("PASS: all verifiable skills within tolerance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
