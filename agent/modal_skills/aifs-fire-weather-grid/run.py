#!/usr/bin/env python3
"""AIFS +24h fields → fire_weather_grid polygon signals."""
from __future__ import annotations

import os
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
    to_celsius,
    to_mm,
)
from grid import polygons_from_mask

SKILL_ID = "aifs-fire-weather-grid"
SIGNAL_TYPE = "fire_weather_grid"
THRESHOLD = int(os.environ.get("AIFS_FW_THRESHOLD", "3"))


def compute_score(fields: dict) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    t2m = to_celsius(fields[("2t", FORECAST_STEP_H)].values)
    td2m = to_celsius(fields[("2d", FORECAST_STEP_H)].values)
    u = fields[("10u", FORECAST_STEP_H)].values.astype(float)
    v = fields[("10v", FORECAST_STEP_H)].values.astype(float)
    tp = to_mm(fields[("tp", FORECAST_STEP_H)].values)
    wind = np.sqrt(u * u + v * v)
    depression = t2m - td2m
    score = (
        (t2m > 30).astype(int)
        + (depression > 15).astype(int)
        + (wind > 6.9).astype(int)
        + (tp < 1).astype(int)
    )
    return score, {"t2m": t2m, "depression": depression, "wind": wind, "tp": tp}


def run(now: datetime, db: Connection | None = None) -> int:
    now = parse_now(now)
    params = ["2t", "2d", "10u", "10v", "tp"]
    run_time, valid_time, fields = fetch_cycle(
        now, skill_id=SKILL_ID, params=params, steps=FORECAST_STEP_H
    )
    lats, lons = lat_lon_from_field(fields[("2t", FORECAST_STEP_H)])
    score_arr, metrics = compute_score(fields)
    mask = score_arr >= THRESHOLD
    print(f"[{SKILL_ID}] high-score cells (>={THRESHOLD}): {int(mask.sum())}")

    def payload_for_cells(cells: list[tuple[int, int]]) -> dict:
        cell_scores = [int(score_arr[y, x]) for y, x in cells]
        return {
            "mean_temp_c": float(np.mean([metrics["t2m"][y, x] for y, x in cells])),
            "mean_dewpoint_depression_c": float(
                np.mean([metrics["depression"][y, x] for y, x in cells])
            ),
            "mean_wind_ms": float(np.mean([metrics["wind"][y, x] for y, x in cells])),
            "mean_precip_mm": float(np.mean([metrics["tp"][y, x] for y, x in cells])),
            "score": int(round(float(np.mean(cell_scores)))),
            "threshold": THRESHOLD,
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
