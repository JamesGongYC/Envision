#!/usr/bin/env python3
"""AIFS multi-horizon 2t → heat_dome polygon signals."""
from __future__ import annotations

import os
from datetime import datetime

import numpy as np
from psycopg import Connection
from shapely.geometry import mapping

from aifs_common import (
    CYCLONE_STEPS,
    fetch_cycle,
    lat_lon_from_field,
    parse_now,
    run_and_insert,
    signal_row,
    to_celsius,
)
from grid import polygons_from_mask

SKILL_ID = "aifs-heat-dome"
SIGNAL_TYPE = "heat_dome"
TEMP_THRESHOLD_C = float(os.environ.get("AIFS_HEAT_DOME_TEMP_C", "35"))
MIN_STEPS = int(os.environ.get("AIFS_HEAT_DOME_MIN_STEPS", "3"))


def run(now: datetime, db: Connection | None = None) -> int:
    now = parse_now(now)
    run_time, valid_time, fields = fetch_cycle(
        now, skill_id=SKILL_ID, params=["2t"], steps=list(CYCLONE_STEPS)
    )
    ref = fields.get(("2t", CYCLONE_STEPS[0]))
    if ref is None:
        ref = fields.get(("2t", 24))
    if ref is None:
        raise RuntimeError("no 2t field in GRIB")
    lats, lons = lat_lon_from_field(ref)

    hot_counts = np.zeros(ref.shape, dtype=int)
    hot_steps: dict[tuple[int, int], list[int]] = {}
    temps_stack: list[np.ndarray] = []
    for step in CYCLONE_STEPS:
        da = fields.get(("2t", step))
        if da is None:
            continue
        t2m = to_celsius(da.values)
        temps_stack.append(t2m)
        hot = t2m > TEMP_THRESHOLD_C
        hot_counts += hot.astype(int)
        ys, xs = np.where(hot)
        for y, x in zip(ys.tolist(), xs.tolist()):
            hot_steps.setdefault((y, x), []).append(int(step))

    mask = hot_counts >= MIN_STEPS
    print(f"[{SKILL_ID}] persistent hot cells (>={MIN_STEPS} steps): {int(mask.sum())}")
    mean_temp = np.mean(np.stack(temps_stack, axis=0), axis=0) if temps_stack else ref.values
    max_temp = np.max(np.stack(temps_stack, axis=0), axis=0) if temps_stack else ref.values

    def payload_for_cells(cells: list[tuple[int, int]]) -> dict:
        steps_seen: set[int] = set()
        for y, x in cells:
            steps_seen.update(hot_steps.get((y, x), []))
        return {
            "mean_temp_c": round(float(np.mean([mean_temp[y, x] for y, x in cells])), 1),
            "max_temp_c": round(float(np.max([max_temp[y, x] for y, x in cells])), 1),
            "persistence_steps": int(round(float(np.mean([hot_counts[y, x] for y, x in cells])))),
            "forecast_hours": sorted(steps_seen),
            "forecast_hour": 24,
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
