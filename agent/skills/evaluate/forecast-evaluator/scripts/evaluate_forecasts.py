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

import os
import sys
import uuid
from datetime import datetime, timezone
from collections import defaultdict

import psycopg

# --- config --------------------------------------------------------------
SKILL_ID = "forecast_evaluator"
SKILL_VERSION = 1

# Tolerance windows around the forecast validity window
PRE_BUFFER_HOURS = 6    # ground truth slightly before valid_from still counts
POST_BUFFER_HOURS = 12  # GDACS publication lag

# Don't evaluate a forecast until this much time has passed since valid_until.
# Must be >= POST_BUFFER_HOURS so we don't prematurely declare false positives.
EVAL_DELAY_HOURS = 12

BATCH_SIZE = 1000

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print(f"[{SKILL_ID}] DATABASE_URL not set", file=sys.stderr)
    sys.exit(2)


# --- disaster class mapping ---------------------------------------------
# Map our canonical forecast classes to possible ground_truth values.
# GDACS uses 2-letter codes; some ingesters normalize, some don't.
CLASS_ALIASES = {
    "wildfire": ("wildfire", "WF", "wildfires", "fire"),
    "typhoon":  ("typhoon", "TC", "tropical_cyclone", "cyclone", "hurricane"),
}


# --- data access --------------------------------------------------------
def load_unevaluated_forecasts(conn):
    """Forecasts whose valid_until + EVAL_DELAY_HOURS has passed and which
    have no row in evaluations yet. Oldest first."""
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
              AND f.valid_until + interval '{EVAL_DELAY_HOURS} hours' < now()
            ORDER BY f.valid_until ASC
            LIMIT {BATCH_SIZE}
            """
        )
        return cur.fetchall()


def find_matching_ground_truth(conn, disaster_class, valid_from, valid_until,
                                geom_geojson):
    """Return (ground_truth_id, occurred_at) of the first matching event,
    or (None, None) if none."""
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


# --- scoring ------------------------------------------------------------
def brier(probability: float, outcome: str) -> float:
    """Standard Brier component: (p - o)²."""
    o = 1.0 if outcome == "hit" else 0.0
    return round((float(probability) - o) ** 2, 6)


# --- main ---------------------------------------------------------------
def main() -> int:
    now = datetime.now(timezone.utc)

    with psycopg.connect(DATABASE_URL, autocommit=False) as conn:
        forecasts = load_unevaluated_forecasts(conn)
        if not forecasts:
            print(f"[{SKILL_ID}] no forecasts ready to evaluate "
                  f"(valid_until + {EVAL_DELAY_HOURS}h must be in the past).")
            return 0

        print(f"[{SKILL_ID}] {len(forecasts)} forecast(s) ready to evaluate.")

        # Per-skill aggregates for the closing summary
        stats = defaultdict(lambda: {"hits": 0, "fp": 0, "brier_sum": 0.0})

        for fid, dclass, prob, vfrom, vuntil, skill_id, geom_geojson in forecasts:
            gt_id, gt_occurred = find_matching_ground_truth(
                conn, dclass, vfrom, vuntil, geom_geojson
            )

            if gt_id is not None:
                outcome = "hit"
                stats[skill_id]["hits"] += 1
            else:
                outcome = "false_positive"
                stats[skill_id]["fp"] += 1

            b = brier(prob, outcome)
            stats[skill_id]["brier_sum"] += b

            insert_evaluation(conn, {
                "id": str(uuid.uuid4()),
                "forecast_id": str(fid),
                "matched_ground_truth_id": str(gt_id) if gt_id else None,
                "outcome": outcome,
                "brier_contribution": b,
                "evaluated_at": now,
            })

        conn.commit()

        # Closing summary
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
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"[{SKILL_ID}] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
