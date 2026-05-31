#!/usr/bin/env python3
"""AIFS +24h wind → high_wind_corridor polygon signals."""
from __future__ import annotations

from datetime import datetime

import numpy as np
from psycopg import Connection
from shapely.geometry import mapping

from aifs_common import (
    FORECAST_STEP_H,
    fetch_cycle,
    lat_lon_from_field,
    parse_now,
    run_and_insert,
    signal_row,
)
from grid import polygons_from_mask

SKILL_ID = "aifs-high-wind-corridor"
SIGNAL_TYPE = "high_wind_corridor"
WIND_THRESHOLD_MS = 16.7


def run(now: datetime, db: Connection | None = None) -> int:
    now = parse_now(now)
    run_time, valid_time, fields = fetch_cycle(
        now, skill_id=SKILL_ID, params=["10u", "10v"], steps=FORECAST_STEP_H
    )
    u = fields[("10u", FORECAST_STEP_H)].values.astype(float)
    v = fields[("10v", FORECAST_STEP_H)].values.astype(float)
    wind = np.sqrt(u * u + v * v)
    direction = (np.degrees(np.arctan2(-u, -v)) + 360) % 360
    lats, lons = lat_lon_from_field(fields[("10u", FORECAST_STEP_H)])
    mask = wind > WIND_THRESHOLD_MS
    print(f"[{SKILL_ID}] high-wind cells (>{WIND_THRESHOLD_MS} m/s): {int(mask.sum())}")

    def payload_for_cells(cells: list[tuple[int, int]]) -> dict:
        winds = [wind[y, x] for y, x in cells]
        dirs = [direction[y, x] for y, x in cells]
        return {
            "max_wind_ms": round(float(max(winds)), 2),
            "mean_wind_direction_deg": round(float(np.mean(dirs)), 1),
            "forecast_hour": FORECAST_STEP_H,
            "run_time": run_time.isoformat().replace("+00:00", "Z"),
        }

    polygons = polygons_from_mask(
        mask, lats, lons, skill_id=SKILL_ID, payload_for_cells=payload_for_cells
    )
    rows = [
        signal_row(
            timestamp=valid_time,
            signal_type=SIGNAL_TYPE,
            geometry=mapping(geom),
            payload=payload,
            now=now,
        )
        for geom, payload in polygons
    ]
    return run_and_insert(now, db, skill_id=SKILL_ID, rows=rows)
