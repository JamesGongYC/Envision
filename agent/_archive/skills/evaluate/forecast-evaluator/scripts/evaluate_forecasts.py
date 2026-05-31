#!/usr/bin/env python3
"""
forecast-evaluator — Envision Day 4 skill.

Reads `forecasts` whose validity window has passed (with a grace period
for GDACS lag), looks for matching `ground_truth` events, and writes one
row per forecast to `evaluations` with the Brier contribution.

Matching rule:
  - disaster_class matches (with flexible mapping for GDACS code variants)
  - ground_truth.occurred_at ∈ (valid_from - 6h, valid_until + 12h)
  - forecast.geometry ∩ ground_truth.geometry ≠ ∅

Outcomes:
  - 'hit'             : a matching event was found
  - 'false_positive'  : forecast window closed, no event
  - 'miss'            : NOT used in v1 (we don't generate forecasts we
                        expect to fail; missed events without any forecast
                        coverage are a separate gap analysis for v2)

Brier contribution = (probability - outcome_value)² where outcome_value
is 1.0 for hit and 0.0 for false_positive.
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone

import psycopg
from psycopg import Connection

# --- config --------------------------------------------------------------
SKILL_ID = "forecast_evaluator"
SKILL_VERSION = 1

PRE_BUFFER_HOURS = 6
POST_BUFFER_HOURS = 12
EVAL_DELAY_HOURS = 12
BATCH_SIZE = 1000

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print(f"[{SKILL_ID}] DATABASE_URL not set", file=sys.stderr)
    sys.exit(2)

CLASS_ALIASES = {
    "wildfire": ("wildfire", "WF", "wildfires", "fire"),
    "typhoon":  ("typhoon", "TC", "tropical_cyclone", "cyclone", "hurricane"),
}


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


def find_matching_ground_truth(conn, disaster_class, valid_from, valid_until,
                                geom_geojson):
    aliases = CLASS_ALIASES.get(disaster_class, (disaster_class,))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, occurred_at
            FROM ground_truth
            WHERE disaster_class = ANY(%s)
              AND occurred_at IS NOT NULL
              AND occurred_at >= %s - interval '{PRE_BUFFER_HOURS} hours'
              AND occurred_at <= %s + interval '{POST_BUFFER_HOURS} hours'
              AND geometry IS NOT NULL
              AND ST_Intersects(
                geometry,
                ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)
              )
            ORDER BY occurred_at ASC
            LIMIT 1
            """,
            (list(aliases), valid_from, valid_until, geom_geojson),
        )
        row = cur.fetchone()
        return row if row else (None, None)


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


def brier(probability: float, outcome: str) -> float:
    o = 1.0 if outcome == "hit" else 0.0
    return round((float(probability) - o) ** 2, 6)


def run(now: datetime, db: Connection) -> int:
    forecasts = load_unevaluated_forecasts(db, now)
    if not forecasts:
        print(f"[{SKILL_ID}] no forecasts ready to evaluate "
              f"(valid_until + {EVAL_DELAY_HOURS}h must be in the past).")
        return 0

    print(f"[{SKILL_ID}] {len(forecasts)} forecast(s) ready to evaluate.")

    stats = defaultdict(lambda: {"hits": 0, "fp": 0, "brier_sum": 0.0})

    for fid, dclass, prob, vfrom, vuntil, skill_id, geom_geojson in forecasts:
        gt_id, gt_occurred = find_matching_ground_truth(
            db, dclass, vfrom, vuntil, geom_geojson
        )

        if gt_id is not None:
            outcome = "hit"
            stats[skill_id]["hits"] += 1
        else:
            outcome = "false_positive"
            stats[skill_id]["fp"] += 1

        b = brier(prob, outcome)
        stats[skill_id]["brier_sum"] += b

        insert_evaluation(db, {
            "id": str(uuid.uuid4()),
            "forecast_id": str(fid),
            "matched_ground_truth_id": str(gt_id) if gt_id else None,
            "outcome": outcome,
            "brier_contribution": b,
            "evaluated_at": now,
        })

    db.commit()

    total_hits = sum(s["hits"] for s in stats.values())
    total_fp = sum(s["fp"] for s in stats.values())
    for skill_id, s in sorted(stats.items()):
        n = s["hits"] + s["fp"]
        mean_brier = s["brier_sum"] / n if n else 0.0
        print(f"[{SKILL_ID}]   {skill_id}: "
              f"{n} evals ({s['hits']} hit, {s['fp']} fp), "
              f"mean Brier {mean_brier:.3f}")
    print(f"[{SKILL_ID}] wrote {len(forecasts)} evaluations "
          f"({total_hits} hits, {total_fp} false positives).")
    return len(forecasts)


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
