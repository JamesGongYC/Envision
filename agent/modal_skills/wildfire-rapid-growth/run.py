#!/usr/bin/env python3
"""
wildfire_rapid_growth — Envision detection skill (Day 3, v1).

Snaps FIRMS hotspots into a 50km grid (Web Mercator, EPSG:3857),
counts each cell's hotspots across 3 consecutive 24h windows
(day_t-2, day_t-1, day_t), and emits a forecast for any cell that
grew >50% day-over-day in BOTH transitions.

Triggering rule (plan §7):
    day_t1 > 1.5 * day_t2  AND  day_t > 1.5 * day_t1
    AND day_t2 >= 1        (must have a baseline to grow from)

Notes:
  - Web Mercator distorts at high latitudes; cells are smaller than
    50km near the poles. For mid-latitude wildfire activity this is
    acceptable for v1.
  - Needs ~3 days of FIRMS data to ever fire. Early in deployment
    expect "no growth cells" on every run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg import Connection
from shapely.geometry import shape

for _lib in ("/root/agent_lib", Path(__file__).resolve().parents[2] / "lib"):
    _lp = str(_lib)
    if os.path.isdir(_lp) and _lp not in sys.path:
        sys.path.insert(0, _lp)
        break
from trace_builder import TraceBuilder  # noqa: E402
from reasoning_llm import generate_reasoning  # noqa: E402
from reasoning_prompts import prompt_wildfire_rapid_growth  # noqa: E402

# --- config ---------------------------------------------------------------
SKILL_ID = "wildfire_rapid_growth"
SKILL_VERSION = 1

LOOKBACK_HOURS = 72
CELL_SIZE_M = 50_000  # 50 km in EPSG:3857
GROWTH_THRESHOLD = 1.5  # 50% growth
FORECAST_VALID_HOURS = 24  # 0–24h nowcast

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print(f"[{SKILL_ID}] DATABASE_URL not set", file=sys.stderr)
    sys.exit(2)


GROWTH_QUERY = """
WITH snapped AS (
  SELECT
    s.id,
    ST_SnapToGrid(ST_Transform(s.geometry, 3857), %(cell)s) AS snap_pt,
    s.timestamp
  FROM signals s
  WHERE s.signal_type = 'hotspot'
    AND s.source LIKE 'firms%%'
    AND s.timestamp > %(now)s - interval '72 hours'
    AND s.timestamp <= %(now)s
),
counted AS (
  SELECT
    snap_pt,
    COUNT(*) FILTER (
      WHERE timestamp > %(now)s - interval '24 hours'
    ) AS day_t,
    COUNT(*) FILTER (
      WHERE timestamp <= %(now)s - interval '24 hours'
        AND timestamp >  %(now)s - interval '48 hours'
    ) AS day_t1,
    COUNT(*) FILTER (
      WHERE timestamp <= %(now)s - interval '48 hours'
    ) AS day_t2,
    array_agg(id) FILTER (
      WHERE timestamp > %(now)s - interval '48 hours'
    ) AS recent_ids
  FROM snapped
  GROUP BY snap_pt
)
SELECT
  day_t,
  day_t1,
  day_t2,
  recent_ids,
  ST_AsGeoJSON(
    ST_Transform(
      ST_MakeEnvelope(
        ST_X(snap_pt),               ST_Y(snap_pt),
        ST_X(snap_pt) + %(cell)s,    ST_Y(snap_pt) + %(cell)s,
        3857
      ),
      4326
    )
  )::jsonb AS cell_geom
FROM counted
WHERE day_t2 >= 1
  AND day_t1::numeric > %(thresh)s * day_t2
  AND day_t::numeric  > %(thresh)s * day_t1
ORDER BY day_t DESC;
"""


def parse_now(argv: list[str] | None = None) -> datetime:
    p = argparse.ArgumentParser(description="Detect wildfire rapid growth")
    p.add_argument("--now", default=None, help="ISO8601 UTC cutoff (default: now)")
    args = p.parse_args(argv)
    if args.now is None:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --- scoring -------------------------------------------------------------
def probability_components(day_t: int, day_t1: int, day_t2: int) -> dict:
    base = 0.45
    persistence_factor = min(0.20, 0.01 * day_t)
    compound = (day_t / max(1, day_t1)) * (day_t1 / max(1, day_t2))
    growth_factor = min(0.20, max(0.0, 0.05 * (compound - 2.25)))
    return {
        "base": base,
        "growth_factor": growth_factor,
        "persistence_factor": persistence_factor,
    }


def score_probability(day_t: int, day_t1: int, day_t2: int) -> float:
    """Crude additive score; DB CHECK caps at 0.85."""
    parts = probability_components(day_t, day_t1, day_t2)
    return round(
        min(
            0.85,
            parts["base"] + parts["persistence_factor"] + parts["growth_factor"],
        ),
        3,
    )


def hotspot_window_counts(conn: Connection, now: datetime) -> tuple[int, int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              COUNT(*) FILTER (
                WHERE timestamp > %s - interval '24 hours'
              )::int AS last_24h,
              COUNT(*) FILTER (
                WHERE timestamp <= %s - interval '24 hours'
                  AND timestamp > %s - interval '48 hours'
              )::int AS prior_24h
            FROM signals
            WHERE signal_type = 'hotspot'
              AND source LIKE 'firms%%'
              AND timestamp > %s - interval '72 hours'
              AND timestamp <= %s
            """,
            (now, now, now, now, now),
        )
        row = cur.fetchone()
        return (row[0] or 0, row[1] or 0)


def cell_bbox(cell_geom) -> list[float]:
    geom_shape = shape(cell_geom)
    minx, miny, maxx, maxy = geom_shape.bounds
    return [float(minx), float(miny), float(maxx), float(maxy)]


def build_reasoning(day_t, day_t1, day_t2, centroid_lonlat) -> str:
    lon, lat = centroid_lonlat
    return (
        f"Hotspot count in 50km cell near ({lat:.2f}, {lon:.2f}) grew "
        f"{day_t2} → {day_t1} → {day_t} over the past 72h "
        f"(>50% day-over-day for 2 consecutive days)."
    )


# --- write ---------------------------------------------------------------
def insert_forecast(conn: Connection, forecast: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO forecasts (
              id, issued_at, valid_from, valid_until,
              disaster_class, geometry, probability,
              skill_id, skill_version, contributing_signal_ids,
              reasoning, is_baseline, trace
            ) VALUES (
              %(id)s, %(issued_at)s, %(valid_from)s, %(valid_until)s,
              %(disaster_class)s,
              ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326)),
              %(probability)s,
              %(skill_id)s, %(skill_version)s,
              %(contributing_signal_ids)s::uuid[],
              %(reasoning)s, %(is_baseline)s,
              %(trace)s::jsonb
            )
            """,
            forecast,
        )


# --- run -----------------------------------------------------------------
def run(now: datetime, db: Connection) -> int:
    valid_until = now + timedelta(hours=FORECAST_VALID_HOURS)

    with db.cursor() as cur:
        cur.execute(
            GROWTH_QUERY,
            {"cell": CELL_SIZE_M, "thresh": GROWTH_THRESHOLD, "now": now},
        )
        rows = cur.fetchall()

    if not rows:
        print(f"[{SKILL_ID}] no cells matched growth rule "
              f"(need ≥3 days of FIRMS history with sustained growth).")
        return 0

    print(f"[{SKILL_ID}] {len(rows)} growing cell(s) detected.")

    last_24h, prior_24h = hotspot_window_counts(db, now)
    growing_cells = []
    for idx, (day_t, day_t1, day_t2, _recent_ids, _cell_geom) in enumerate(rows):
        ratio = float(day_t) / max(1, day_t1)
        growing_cells.append({
            "cell_id": str(idx),
            "growth_ratio": round(ratio, 3),
            "days_consecutive": 2,
        })

    written = 0
    for idx, (day_t, day_t1, day_t2, recent_ids, cell_geom) in enumerate(rows):
        geom_shape = shape(cell_geom)
        centroid = geom_shape.centroid

        prob = score_probability(day_t, day_t1, day_t2)
        fallback = build_reasoning(
            day_t, day_t1, day_t2, (centroid.x, centroid.y)
        )

        contributing = [str(u) for u in (recent_ids or [])]

        tb = TraceBuilder(now, SKILL_ID)
        tb.set_inputs(
            hotspot_count_last_24h=last_24h,
            hotspot_count_prior_24h=prior_24h,
        )
        tb.set_intermediate(
            growing_cells=[growing_cells[idx]],
            threshold_met_count=len(rows),
        )
        tb.add_geometry_step(
            "cell_boundaries_emitted",
            bboxes=[cell_bbox(cell_geom)],
        )
        tb.set_probability_components(**probability_components(day_t, day_t1, day_t2))

        trace_dict = tb.build()
        prompt = prompt_wildfire_rapid_growth(
            trace_dict, centroid.y, centroid.x, day_t, day_t1, day_t2
        )
        reasoning = generate_reasoning(prompt, fallback)

        forecast = {
            "id": str(uuid.uuid4()),
            "issued_at": now,
            "valid_from": now,
            "valid_until": valid_until,
            "disaster_class": "wildfire",
            "geometry": json.dumps(cell_geom),
            "probability": prob,
            "skill_id": SKILL_ID,
            "skill_version": SKILL_VERSION,
            "contributing_signal_ids": contributing,
            "reasoning": reasoning,
            "is_baseline": False,
            "trace": json.dumps(trace_dict),
        }
        insert_forecast(db, forecast)
        written += 1
        print(f"[{SKILL_ID}]   cell @ ({centroid.y:.2f}, {centroid.x:.2f}): "
              f"{day_t2}→{day_t1}→{day_t} p={prob}")

    db.commit()
    print(f"[{SKILL_ID}] wrote {written} forecasts.")
    return written


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
