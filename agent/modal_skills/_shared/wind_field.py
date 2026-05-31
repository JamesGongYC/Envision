"""Build and store leaflet-velocity wind fields from AIFS 10u/10v grids."""
from __future__ import annotations

import gzip
import json
import os
import sys
from datetime import datetime

import numpy as np
import xarray as xr
from psycopg import Connection, errors as pg_errors

SOURCE = "aifs"
MAX_COMPRESSED_BYTES = 5 * 1024 * 1024


def _normalize_lons(lons: np.ndarray) -> np.ndarray:
    out = np.asarray(lons, dtype=float)
    if np.nanmax(out) > 180:
        out = ((out + 180) % 360) - 180
    return out


def build_wind_field_json(
    ds_u: xr.DataArray,
    ds_v: xr.DataArray,
    run_time: datetime,
    valid_at: datetime,
    *,
    round_decimals: int | None = 2,
) -> list[dict]:
    """Return leaflet-velocity [U, V] records from +24h 10m wind components."""
    lats = np.asarray(ds_u.latitude.values, dtype=float)
    lons = _normalize_lons(ds_u.longitude.values)
    u = np.asarray(ds_u.values, dtype=float)
    v = np.asarray(ds_v.values, dtype=float)

    if lats[0] < lats[-1]:
        lats = lats[::-1]
        u = u[::-1, :]
        v = v[::-1, :]

    if lons[0] > lons[-1]:
        order = np.argsort(lons)
        lons = lons[order]
        u = u[:, order]
        v = v[:, order]

    la1 = float(lats[0])
    la2 = float(lats[-1])
    lo1 = float(lons[0])
    lo2 = float(lons[-1])
    if lons.size > 1:
        dx = float(abs(lons[1] - lons[0]))
        dy = float(abs(lats[0] - lats[1]))
    else:
        dx = dy = 0.25

    ref = run_time.isoformat().replace("+00:00", "Z")
    header_base = {
        "parameterUnit": "m.s-1",
        "dx": dx,
        "dy": dy,
        "la1": la1,
        "lo1": lo1,
        "la2": la2,
        "lo2": lo2,
        "nx": int(len(lons)),
        "ny": int(len(lats)),
        "refTime": ref,
        "forecastTime": int((valid_at - run_time).total_seconds() // 3600),
    }

    def flatten(arr: np.ndarray) -> list[float]:
        flat = arr.flatten(order="C").tolist()
        if round_decimals is not None:
            return [round(float(x), round_decimals) for x in flat]
        return [float(x) for x in flat]

    return [
        {
            "header": {
                **header_base,
                "parameterCategory": 2,
                "parameterNumber": 2,
                "parameterNumberName": "U-component_of_wind",
            },
            "data": flatten(u),
        },
        {
            "header": {
                **header_base,
                "parameterCategory": 2,
                "parameterNumber": 3,
                "parameterNumberName": "V-component_of_wind",
            },
            "data": flatten(v),
        },
    ]


def emit_wind_field(
    db: Connection,
    *,
    run_time: datetime,
    valid_at: datetime,
    ds_u: xr.DataArray,
    ds_v: xr.DataArray,
    skill_id: str = "aifs-fire-weather-grid",
) -> int:
    """Insert one gzipped wind_fields row; returns size_bytes."""
    payload = build_wind_field_json(ds_u, ds_v, run_time, valid_at, round_decimals=2)
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    compressed = gzip.compress(raw, compresslevel=6)
    if len(compressed) > MAX_COMPRESSED_BYTES:
        payload = build_wind_field_json(ds_u, ds_v, run_time, valid_at, round_decimals=1)
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        compressed = gzip.compress(raw, compresslevel=6)

    size_bytes = len(compressed)
    try:
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO wind_fields (run_time, valid_at, source, data_compressed, size_bytes)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (run_time, valid_at, SOURCE, compressed, size_bytes),
            )
        db.commit()
    except pg_errors.UndefinedTable:
        db.rollback()
        print(
            f"[{skill_id}] wind_fields table missing — apply db/migrations/005_wind_fields.sql",
            file=sys.stderr,
        )
        return 0
    print(f"[{skill_id}] wind_fields inserted: {size_bytes} bytes (valid_at={valid_at.isoformat()})")
    return size_bytes


def should_emit_wind_field() -> bool:
    return os.environ.get("AIFS_EMIT_WIND_FIELD", "true").lower() not in (
        "0",
        "false",
        "no",
    )
