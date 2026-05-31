#!/usr/bin/env python3
"""AIFS +24h tp → heavy_precipitation_band polygon signals."""
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
    to_mm,
)
from grid import polygons_from_mask

SKILL_ID = "aifs-heavy-precipitation-band"
SIGNAL_TYPE = "heavy_precipitation_band"
PRECIP_THRESHOLD_MM = 50.0


def run(now: datetime, db: Connection | None = None) -> int:
    now = parse_now(now)
    run_time, valid_time, fields = fetch_cycle(
        now, skill_id=SKILL_ID, params=["tp"], steps=FORECAST_STEP_H
    )
    tp = to_mm(fields[("tp", FORECAST_STEP_H)].values)
    lats, lons = lat_lon_from_field(fields[("tp", FORECAST_STEP_H)])
    mask = tp > PRECIP_THRESHOLD_MM
    print(f"[{SKILL_ID}] heavy-precip cells (>{PRECIP_THRESHOLD_MM} mm): {int(mask.sum())}")

    def payload_for_cells(cells: list[tuple[int, int]]) -> dict:
        vals = [tp[y, x] for y, x in cells]
        return {
            "max_precip_mm": round(float(max(vals)), 1),
            "mean_precip_mm": round(float(np.mean(vals)), 1),
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
