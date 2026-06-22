#!/usr/bin/env python3
"""
wildfire_rapid_growth — Envision detection skill (mutation surface).

Snaps FIRMS hotspots (MODIS + VIIRS) into a 50km grid (Web Mercator, EPSG:3857),
counts each cell's hotspots across 3 consecutive 24h windows
(day_t-2, day_t-1, day_t), and emits a forecast for any cell that
grew >50% day-over-day in BOTH transitions.

Mutation changes vs v1:
  - Raised GROWTH_THRESHOLD from 1.5 → 2.0 (require 100% growth, not 50%)
  - Raised minimum baseline from day_t2 >= 1 → day_t2 >= 3
  - Added fire weather confirmation gate: only emit forecast if at least one
    fire_weather_grid signal (aifs or ecmwf_open_data) or nws_alerts/fire_warning
    overlaps the cell's bounding box within 48h of `now`
  - Tightened probability scoring: capped base at 0.35 (down from 0.45),
    reduced max growth_factor to 0.25, persistence_factor to 0.15
  - Added a hard probability floor/ceiling: min 0.10, max 0.75 (was 0.85)
    — all 3 worst forecasts had p=0.85 as false positives
  - Raised min consecutive days needed implicitly via stricter thresholds
  - Source filter now explicitly uses firms_modis OR firms_viirs (exact literals)
    rather than LIKE 'firms%%'
"""

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg import Connection
from shapely.geometry import shape, box

for _lib in ("/root/agent_lib", Path(__file__).resolve().parents[2] / "lib"):
    _lp = str(_lib)
    if os.path.isdir(_lp) and _lp not in sys.path:
        sys.path.insert(0, _lp)
        break
from trace_builder import TraceBuilder  # noqa: E402
from reasoning_llm import generate_reasoning  # noqa: E402
from reasoning_prompts import prompt_wildfire_rapid_growth  # noqa: E402
from forecast_model import Forecast  # noqa: E402

# --- config ---------------------------------------------------------------
SKILL_ID = "wildfire_rapid_growth"
SKILL_VERSION = 2

LOOKBACK_HOURS = 72
CELL_SIZE_M = 50_000          # 50 km in EPSG:3857
GROWTH_THRESHOLD = 2.0        # 100% growth (up from 50%) — reduces false positives
MIN_BASELINE_COUNT = 3        # day_t2 must have ≥3 hotspots (up from 1)
FORECAST_VALID_HOURS = 24     # 0–24h nowcast
FIRE_WEATHER_LOOKBACK_H = 48  # window to search for corroborating fire weather signals
PROB_FLOOR = 0.10
PROB_CEIL = 0.75              # hard cap lowered from 0.85


GROWTH_QUERY = """
WITH firms AS (
  SELECT
    s.id,
    ST_SnapToGrid(ST_Transform(s.geometry, 3857), %(cell)s) AS snap_pt,
    s.timestamp
  FROM signals s
  WHERE s.signal_type = 'hotspot'
    AND s.source IN ('firms_modis', 'firms_viirs')
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
  FROM firms
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
WHERE day_t2 >= %(min_baseline)s
  AND day_t1::numeric > %(thresh)s * day_t2
  AND day_t::numeric  > %(thresh)s * day_t1
ORDER BY day_t DESC;
"""


# Query to check if a fire weather / warning signal intersects the cell bbox
FIRE_WEATHER_GATE_QUERY = """
SELECT COUNT(*)
FROM signals s
WHERE s.signal_type IN ('fire_weather_grid', 'fire_warning', 'fire_weather')
  AND s.source IN (
    'aifs', 'ecmwf_open_data', 'nws_alerts', 'open_meteo'
  )
  AND s.timestamp > %(now)s - interval '48 hours'
  AND s.timestamp <= %(now)s
  AND ST_Intersects(
    s.geometry,
    ST_MakeEnvelope(%(minx)s, %(miny)s, %(maxx)s, %(maxy)s, 4326)
  );
"""


# --- scoring -------------------------------------------------------------
def probability_components(day_t: int, day_t1: int, day_t2: int) -> dict:
    base = 0.35  # lowered from 0.45
    # persistence: scales with absolute hotspot count in current window, capped lower
    persistence_factor = min(0.15, 0.005 * day_t)
    # compound growth ratio
    compound = (day_t / max(1, day_t1)) * (day_t1 / max(1, day_t2))
    # growth_factor: needs compound > 4.0 to start contributing (stricter than old 2.25)
    growth_factor = min(0.25, max(0.0, 0.04 * (compound - 4.0)))
    return {
        "base": base,
        "growth_factor": round(growth_factor, 4),
        "persistence_factor": round(persistence_factor, 4),
    }


def score_probability(day_t: int, day_t1: int, day_t2: int) -> float:
    parts = probability_components(day_t, day_t1, day_t2)
    raw = parts["base"] + parts["persistence_factor"] + parts["growth_factor"]
    return round(min(PROB_CEIL, max(PROB_FLOOR, raw)), 3)


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
              AND source IN ('firms_modis', 'firms_viirs')
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


def cell_has_fire_weather_support(
    conn: Connection, now: datetime, minx: float, miny: float, maxx: float, maxy: float
) -> bool:
    """Return True if any fire weather or warning signal intersects the cell."""
    with conn.cursor() as cur:
        cur.execute(
            FIRE_WEATHER_GATE_QUERY,
            {"now": now, "minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy},
        )
        row = cur.fetchone()
        return (row[0] or 0) > 0


def build_reasoning(day_t, day_t1, day_t2, centroid_lonlat, fire_wx_confirmed) -> str:
    lon, lat = centroid_lonlat
    conf_str = " Fire weather conditions confirmed by grid/warning signals." if fire_wx_confirmed else ""
    return (
        f"Hotspot count in 50km cell near ({lat:.2f}, {lon:.2f}) grew "
        f"{day_t2} → {day_t1} → {day_t} over the past 72h "
        f"(>100% day-over-day for 2 consecutive days, baseline ≥{MIN_BASELINE_COUNT}).{conf_str}"
    )


# --- run -----------------------------------------------------------------
def run(now: datetime, db: Connection) -> list[Forecast]:
    valid_until = now + timedelta(hours=FORECAST_VALID_HOURS)

    with db.cursor() as cur:
        cur.execute(
            GROWTH_QUERY,
            {
                "cell": CELL_SIZE_M,
                "thresh": GROWTH_THRESHOLD,
                "now": now,
                "min_baseline": MIN_BASELINE_COUNT,
            },
        )
        rows = cur.fetchall()

    if not rows:
        print(
            f"[{SKILL_ID}] no cells matched growth rule "
            f"(need ≥3 days of FIRMS history with sustained >100% growth "
            f"and baseline ≥{MIN_BASELINE_COUNT})."
        )
        return []

    print(f"[{SKILL_ID}] {len(rows)} candidate growing cell(s) before fire-weather gate.")

    last_24h, prior_24h = hotspot_window_counts(db, now)

    growing_cells = []
    for idx, (day_t, day_t1, day_t2, _recent_ids, _cell_geom) in enumerate(rows):
        ratio = float(day_t) / max(1, day_t1)
        growing_cells.append({
            "cell_id": str(idx),
            "growth_ratio": round(ratio, 3),
            "days_consecutive": 2,
        })

    out: list[Forecast] = []
    emitted = 0
    for idx, (day_t, day_t1, day_t2, recent_ids, cell_geom) in enumerate(rows):
        geom_shape = shape(cell_geom)
        centroid = geom_shape.centroid
        minx, miny, maxx, maxy = geom_shape.bounds

        # Fire-weather confirmation gate — skip cell if no supporting signal
        fire_wx_confirmed = cell_has_fire_weather_support(
            db, now, minx, miny, maxx, maxy
        )
        if not fire_wx_confirmed:
            print(
                f"[{SKILL_ID}]   cell @ ({centroid.y:.2f}, {centroid.x:.2f}): "
                f"skipped — no fire weather/warning signal in bbox"
            )
            continue

        prob = score_probability(day_t, day_t1, day_t2)
        fallback = build_reasoning(
            day_t, day_t1, day_t2, (centroid.x, centroid.y), fire_wx_confirmed
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
            fire_wx_gate_passed=fire_wx_confirmed,
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
        reasoning = generate_reasoning(prompt, fallback, db=db)

        out.append(
            Forecast(
                id=str(uuid.uuid4()),
                issued_at=now,
                valid_from=now,
                valid_until=valid_until,
                disaster_class="wildfire",
                geometry=json.dumps(cell_geom),
                probability=prob,
                skill_id=SKILL_ID,
                skill_version=SKILL_VERSION,
                contributing_signal_ids=contributing,
                reasoning=reasoning,
                is_baseline=False,
                trace=trace_dict,
            )
        )
        emitted += 1
        print(
            f"[{SKILL_ID}]   cell @ ({centroid.y:.2f}, {centroid.x:.2f}): "
            f"{day_t2}→{day_t1}→{day_t} p={prob} fire_wx_gate=passed"
        )

    print(f"[{SKILL_ID}] emitted {emitted} forecast(s) (of {len(rows)} candidate cells).")
    return out
