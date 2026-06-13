#!/usr/bin/env python3
"""Purge v1 seed demo forecasts, evaluations, and linked ground_truth rows.

Run manually against production after verifying counts. Requires DATABASE_URL.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402

from agent.evolution.constants import SEED_CUTOFF, SEED_SKILL_IDS  # noqa: E402

EXPECTED_FORECASTS_MIN = 20
EXPECTED_FORECASTS_MAX = 120


def _count(cur, sql: str, params=()) -> int:
    cur.execute(sql, params)
    row = cur.fetchone()
    return int(row[0]) if row else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Purge seeded demo data before W6 collapse")
    p.add_argument(
        "--commit",
        action="store_true",
        help="Apply deletes (default: dry-run counts only)",
    )
    args = p.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL required", file=sys.stderr)
        return 2

    with psycopg.connect(url, autocommit=False) as db:
        with db.cursor() as cur:
            forecast_ids_sql = """
                SELECT id FROM forecasts
                WHERE issued_at < %s
                  AND skill_id = ANY(%s)
            """
            cur.execute(forecast_ids_sql, (SEED_CUTOFF, list(SEED_SKILL_IDS)))
            forecast_ids = [str(r[0]) for r in cur.fetchall()]
            n_forecasts = len(forecast_ids)

            if n_forecasts < EXPECTED_FORECASTS_MIN or n_forecasts > EXPECTED_FORECASTS_MAX:
                print(
                    f"ABORT: expected ~34–68 seed forecasts, found {n_forecasts}. "
                    "Inspect before deleting.",
                    file=sys.stderr,
                )
                return 1

            gt_ids_sql = """
                SELECT DISTINCT e.matched_ground_truth_id
                FROM evaluations e
                JOIN forecasts f ON f.id = e.forecast_id
                WHERE f.issued_at < %s
                  AND f.skill_id = ANY(%s)
                  AND e.matched_ground_truth_id IS NOT NULL
            """
            cur.execute(gt_ids_sql, (SEED_CUTOFF, list(SEED_SKILL_IDS)))
            gt_ids = [str(r[0]) for r in cur.fetchall()]

            n_evals = _count(
                cur,
                """
                SELECT COUNT(*) FROM evaluations
                WHERE forecast_id = ANY(%s::uuid[])
                """,
                (forecast_ids,),
            ) if forecast_ids else 0

            n_proposals = _count(
                cur,
                """
                SELECT COUNT(*) FROM skill_edit_proposals
                WHERE proposed_at < %s
                  AND skill_id = ANY(%s)
                """,
                (SEED_CUTOFF, list(SEED_SKILL_IDS)),
            )

            print(f"Seed forecasts to delete: {n_forecasts}")
            print(f"Linked evaluations:       {n_evals}")
            print(f"Linked ground_truth:      {len(gt_ids)}")
            print(f"Seed proposals:           {n_proposals}")

            if not args.commit:
                print("Dry run — pass --commit to apply.")
                return 0

            if forecast_ids:
                cur.execute(
                    "DELETE FROM evaluations WHERE forecast_id = ANY(%s::uuid[])",
                    (forecast_ids,),
                )
                cur.execute(
                    "DELETE FROM forecasts WHERE id = ANY(%s::uuid[])",
                    (forecast_ids,),
                )
            if gt_ids:
                cur.execute(
                    "DELETE FROM ground_truth WHERE id = ANY(%s::uuid[])",
                    (gt_ids,),
                )
            cur.execute(
                """
                DELETE FROM skill_edit_proposals
                WHERE proposed_at < %s AND skill_id = ANY(%s)
                """,
                (SEED_CUTOFF, list(SEED_SKILL_IDS)),
            )

        db.commit()
        print("Purge committed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
