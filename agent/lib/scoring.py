"""Shared forecast vs ground-truth matching and Brier scoring (live evaluator + backtest)."""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any, Protocol

from shapely.geometry import shape

PRE_BUFFER_HOURS = 6
POST_BUFFER_HOURS = 12

CLASS_ALIASES: dict[str, tuple[str, ...]] = {
    "wildfire": ("wildfire", "WF", "wildfires", "fire"),
    "typhoon": ("typhoon", "TC", "tropical_cyclone", "cyclone", "hurricane"),
}


class _ForecastLike(Protocol):
    disaster_class: str
    probability: float
    valid_from: Any
    valid_until: Any
    geometry: str


def class_aliases(disaster_class: str) -> tuple[str, ...]:
    return CLASS_ALIASES.get(disaster_class, (disaster_class,))


def geom_geojson(forecast: _ForecastLike) -> str:
    g = forecast.geometry
    return g if isinstance(g, str) else json.dumps(g)


def match_forecast_to_truth_sql(
    conn,
    disaster_class: str,
    valid_from,
    valid_until,
    geom_geojson_str: str,
    *,
    grace_hours: int = 0,
) -> tuple[Any | None, Any | None]:
    """DB-backed match (live evaluator). Returns (gt_id, gt_occurred_at) or (None, None)."""
    aliases = list(class_aliases(disaster_class))
    post_h = POST_BUFFER_HOURS + grace_hours
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, occurred_at
            FROM ground_truth
            WHERE disaster_class = ANY(%s)
              AND occurred_at IS NOT NULL
              AND occurred_at >= %s - interval '{PRE_BUFFER_HOURS} hours'
              AND occurred_at <= %s + interval '{post_h} hours'
              AND geometry IS NOT NULL
              AND ST_Intersects(
                geometry,
                ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)
              )
            ORDER BY occurred_at ASC
            LIMIT 1
            """,
            (aliases, valid_from, valid_until, geom_geojson_str),
        )
        row = cur.fetchone()
        if row:
            return row[0], row[1]
    return None, None


def match_forecast_to_truth(
    forecast: _ForecastLike,
    ground_truth_rows: list[Any],
    *,
    grace_hours: int = 12,
) -> Any | None:
    """
    In-memory match for backtest harness.
    Rows: objects with id, disaster_class, occurred_at, geom_geojson — or 4-tuples.
    """
    if not ground_truth_rows:
        return None

    aliases = set(class_aliases(forecast.disaster_class))
    try:
        f_geom = shape(json.loads(geom_geojson(forecast)))
    except Exception:
        return None

    vfrom = forecast.valid_from
    vuntil = forecast.valid_until
    pre = vfrom - timedelta(hours=PRE_BUFFER_HOURS)
    post = vuntil + timedelta(hours=POST_BUFFER_HOURS + grace_hours)

    for row in ground_truth_rows:
        if hasattr(row, "disaster_class"):
            dclass = row.disaster_class
            occurred = row.occurred_at
            row_geom_json = row.geom_geojson
        else:
            dclass = row[1]
            occurred = row[2]
            row_geom_json = row[3]

        gt_aliases = set(class_aliases(dclass))
        if not aliases.intersection(gt_aliases):
            continue
        if occurred is None or occurred < pre or occurred > post:
            continue
        try:
            g = shape(json.loads(row_geom_json))
        except Exception:
            continue
        if f_geom.intersects(g):
            return row

    return None


def brier_contribution(
    forecast: _ForecastLike,
    matched_gt: Any | None,
) -> tuple[str, float]:
    """Return (outcome, brier_contribution). v1: hit or false_positive only."""
    if matched_gt is not None:
        outcome = "hit"
        o = 1.0
    else:
        outcome = "false_positive"
        o = 0.0
    b = round((float(forecast.probability) - o) ** 2, 6)
    return outcome, b
