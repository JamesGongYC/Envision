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

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
from shapely.geometry import shape

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


# --- query ---------------------------------------------------------------
GROWTH_QUERY = """
WITH snapped AS (
  SELECT
    s.id,
    ST_SnapToGrid(ST_Transform(s.geometry, 3857), %(cell)s) AS snap_pt,
    s.timestamp
  FROM signals s
  WHERE s.signal_type = 'hotspot'
    AND s.source LIKE 'firms%%'
    AND s.timestamp > now() - interval '72 hours'
),
counted AS (
  SELECT
    snap_pt,
    COUNT(*) FILTER (
      WHERE timestamp > now() - interval '24 hours'
    ) AS day_t,
    COUNT(*) FILTER (
      WHERE timestamp <= now() - interval '24 hours'
        AND timestamp >  now() - interval '48 hours'
    ) AS day_t1,
    COUNT(*) FILTER (
      WHERE timestamp <= now() - interval '48 hours'
    ) AS day_t2,
    array_agg(id) FILTER (
      WHERE timestamp > now() - interval '48 hours'
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


# --- scoring -------------------------------------------------------------
def score_probability(day_t: int, day_t1: int, day_t2: int) -> float:
    """Crude additive score; DB CHECK caps at 0.85."""
    base = 0.45
    # bonus for absolute current activity (caps at 20 hotspots/cell)
    count_bonus = min(0.20, 0.01 * day_t)
    # bonus for compound growth beyond the 1.5x*1.5x = 2.25x floor
    compound = (day_t / max(1, day_t1)) * (day_t1 / max(1, day_t2))
    growth_bonus = min(0.20, max(0.0, 0.05 * (compound - 2.25)))
    return round(min(0.85, base + count_bonus + growth_bonus), 3)


def build_reasoning(day_t, day_t1, day_t2, centroid_lonlat) -> str:
    lon, lat = centroid_lonlat
    return (
        f"Hotspot count in 50km cell near ({lat:.2f}, {lon:.2f}) grew "
        f"{day_t2} → {day_t1} → {day_t} over the past 72h "
        f"(>50% day-over-day for 2 consecutive days)."
    )


# --- write ---------------------------------------------------------------
def insert_forecast(conn, forecast: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO forecasts (
              id, issued_at, valid_from, valid_until,
              disaster_class, geometry, probability,
              skill_id, skill_version, contributing_signal_ids,
              reasoning, is_baseline
            ) VALUES (
              %(id)s, %(issued_at)s, %(valid_from)s, %(valid_until)s,
              %(disaster_class)s,
              ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326)),
              %(probability)s,
              %(skill_id)s, %(skill_version)s,
              %(contributing_signal_ids)s::uuid[],
              %(reasoning)s, %(is_baseline)s
            )
            """,
            forecast,
        )


# --- main ----------------------------------------------------------------
def main() -> int:
    now = datetime.now(timezone.utc)
    valid_until = now + timedelta(hours=FORECAST_VALID_HOURS)

    with psycopg.connect(DATABASE_URL, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(
                GROWTH_QUERY,
                {"cell": CELL_SIZE_M, "thresh": GROWTH_THRESHOLD},
            )
            rows = cur.fetchall()

        if not rows:
            print(f"[{SKILL_ID}] no cells matched growth rule "
                  f"(need ≥3 days of FIRMS history with sustained growth).")
            return 0

        print(f"[{SKILL_ID}] {len(rows)} growing cell(s) detected.")

        written = 0
        for day_t, day_t1, day_t2, recent_ids, cell_geom in rows:
            geom_shape = shape(cell_geom)
            centroid = geom_shape.centroid

            prob = score_probability(day_t, day_t1, day_t2)
            reasoning = build_reasoning(
                day_t, day_t1, day_t2, (centroid.x, centroid.y)
            )

            contributing = [str(u) for u in (recent_ids or [])]

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
            }
            insert_forecast(conn, forecast)
            written += 1
            print(f"[{SKILL_ID}]   cell @ ({centroid.y:.2f}, {centroid.x:.2f}): "
                  f"{day_t2}→{day_t1}→{day_t} p={prob}")

        conn.commit()
        print(f"[{SKILL_ID}] wrote {written} forecasts.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"[{SKILL_ID}] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
