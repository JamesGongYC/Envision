#!/usr/bin/env python3
"""
forecast-evaluator — match closed forecasts to ground_truth; write evaluations.
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import Connection

for _lib in ("/root/agent_lib", Path(__file__).resolve().parents[2] / "lib"):
    _lp = str(_lib)
    if os.path.isdir(_lp) and _lp not in sys.path:
        sys.path.insert(0, _lp)
        break

from scoring import (  # noqa: E402
    brier_contribution,
    match_forecast_to_truth_sql,
)

SKILL_ID = "forecast_evaluator"
SKILL_VERSION = 1
EVAL_DELAY_HOURS = 12
BATCH_SIZE = 1000

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print(f"[{SKILL_ID}] DATABASE_URL not set", file=sys.stderr)
    sys.exit(2)


def parse_now(argv: list[str] | None = None) -> datetime:
    p = argparse.ArgumentParser(description="Evaluate closed forecasts")
    p.add_argument("--now", default=None, help="ISO8601 UTC cutoff (default: now)")
    args = p.parse_args(argv)
    if args.now is None:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load_unevaluated_forecasts(conn: Connection, now: datetime):
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT f.id,
                   f.disaster_class,
                   f.probability,
                   f.valid_from,
                   f.valid_until,
                   f.skill_id,
                   ST_AsGeoJSON(f.geometry)::text AS geom_geojson
            FROM forecasts f
            LEFT JOIN evaluations e ON e.forecast_id = f.id
            WHERE e.id IS NULL
              AND f.valid_until + interval '{EVAL_DELAY_HOURS} hours' < %s
            ORDER BY f.valid_until ASC
            LIMIT {BATCH_SIZE}
            """,
            (now,),
        )
        return cur.fetchall()


def load_unevaluated_shadow_forecasts(conn: Connection, now: datetime):
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT f.id,
                   f.disaster_class,
                   f.probability,
                   f.valid_from,
                   f.valid_until,
                   f.skill_id,
                   ST_AsGeoJSON(f.geometry)::text AS geom_geojson
            FROM forecasts_shadow f
            LEFT JOIN shadow_evaluations e ON e.shadow_forecast_id = f.id
            WHERE e.id IS NULL
              AND f.shadow_promotion_status = 'evaluating'
              AND f.valid_until + interval '{EVAL_DELAY_HOURS} hours' < %s
            ORDER BY f.valid_until ASC
            LIMIT {BATCH_SIZE}
            """,
            (now,),
        )
        return cur.fetchall()


def insert_evaluation(conn, evaluation):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluations (
              id, forecast_id, matched_ground_truth_id,
              outcome, brier_contribution, evaluated_at
            ) VALUES (
              %(id)s, %(forecast_id)s, %(matched_ground_truth_id)s,
              %(outcome)s, %(brier_contribution)s, %(evaluated_at)s
            )
            """,
            evaluation,
        )


def insert_shadow_evaluation(conn, evaluation):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO shadow_evaluations (
              id, shadow_forecast_id, matched_ground_truth_id,
              outcome, brier_contribution, evaluated_at
            ) VALUES (
              %(id)s, %(shadow_forecast_id)s, %(matched_ground_truth_id)s,
              %(outcome)s, %(brier_contribution)s, %(evaluated_at)s
            )
            """,
            evaluation,
        )


def _score_forecast_row(
    db: Connection,
    fid,
    dclass,
    prob,
    vfrom,
    vuntil,
    skill_id,
    geom_geojson,
    now: datetime,
) -> dict:
    gt_id, _gt_occurred = match_forecast_to_truth_sql(
        db, dclass, vfrom, vuntil, geom_geojson
    )

    class _F:
        pass

    f = _F()
    f.probability = prob

    outcome, b = brier_contribution(f, gt_id)
    return {
        "outcome": outcome,
        "brier_contribution": b,
        "matched_ground_truth_id": str(gt_id) if gt_id else None,
        "gt_id": gt_id,
        "skill_id": skill_id,
        "evaluated_at": now,
        "forecast_id": str(fid),
    }


def evaluate_live_forecasts(now: datetime, db: Connection) -> int:
    """Score live forecasts only (unchanged behavior)."""
    forecasts = load_unevaluated_forecasts(db, now)
    if not forecasts:
        print(f"[{SKILL_ID}] no live forecasts ready to evaluate "
              f"(valid_until + {EVAL_DELAY_HOURS}h must be in the past).")
        return 0

    print(f"[{SKILL_ID}] {len(forecasts)} live forecast(s) ready to evaluate.")

    stats = defaultdict(lambda: {"hits": 0, "fp": 0, "brier_sum": 0.0})

    for fid, dclass, prob, vfrom, vuntil, skill_id, geom_geojson in forecasts:
        scored = _score_forecast_row(
            db, fid, dclass, prob, vfrom, vuntil, skill_id, geom_geojson, now
        )

        if scored["gt_id"] is not None:
            stats[skill_id]["hits"] += 1
        else:
            stats[skill_id]["fp"] += 1
        stats[skill_id]["brier_sum"] += scored["brier_contribution"]

        insert_evaluation(db, {
            "id": str(uuid.uuid4()),
            "forecast_id": scored["forecast_id"],
            "matched_ground_truth_id": scored["matched_ground_truth_id"],
            "outcome": scored["outcome"],
            "brier_contribution": scored["brier_contribution"],
            "evaluated_at": scored["evaluated_at"],
        })

    total_hits = sum(s["hits"] for s in stats.values())
    total_fp = sum(s["fp"] for s in stats.values())
    for sid, s in sorted(stats.items()):
        n = s["hits"] + s["fp"]
        mean_brier = s["brier_sum"] / n if n else 0.0
        print(f"[{SKILL_ID}]   {sid}: "
              f"{n} evals ({s['hits']} hit, {s['fp']} fp), "
              f"mean Brier {mean_brier:.3f}")
    print(f"[{SKILL_ID}] wrote {len(forecasts)} live evaluations "
          f"({total_hits} hits, {total_fp} false positives).")
    return len(forecasts)


def evaluate_shadow_forecasts(now: datetime, db: Connection) -> int:
    """Score shadow forecasts into shadow_evaluations."""
    forecasts = load_unevaluated_shadow_forecasts(db, now)
    if not forecasts:
        print(f"[{SKILL_ID}] no shadow forecasts ready to evaluate.")
        return 0

    print(f"[{SKILL_ID}] {len(forecasts)} shadow forecast(s) ready to evaluate.")

    for fid, dclass, prob, vfrom, vuntil, skill_id, geom_geojson in forecasts:
        scored = _score_forecast_row(
            db, fid, dclass, prob, vfrom, vuntil, skill_id, geom_geojson, now
        )
        insert_shadow_evaluation(db, {
            "id": str(uuid.uuid4()),
            "shadow_forecast_id": scored["forecast_id"],
            "matched_ground_truth_id": scored["matched_ground_truth_id"],
            "outcome": scored["outcome"],
            "brier_contribution": scored["brier_contribution"],
            "evaluated_at": scored["evaluated_at"],
        })

    print(f"[{SKILL_ID}] wrote {len(forecasts)} shadow evaluations.")
    return len(forecasts)


def run(now: datetime, db: Connection) -> int:
    live_n = evaluate_live_forecasts(now, db)
    shadow_n = evaluate_shadow_forecasts(now, db)
    if live_n or shadow_n:
        db.commit()
    return live_n + shadow_n


def main() -> int:
    now = parse_now()
    with psycopg.connect(DATABASE_URL, autocommit=False) as db:
        run(now, db)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"[{SKILL_ID}] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
