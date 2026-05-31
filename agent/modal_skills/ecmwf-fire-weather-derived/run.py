#!/usr/bin/env python3
"""ECMWF Open Data HRES → fire weather grid polygons → signals."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import psycopg
import xarray as xr
from psycopg import Connection
from scipy import ndimage
from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.ops import unary_union
from shapely.validation import make_valid

SKILL_ID = "ecmwf-fire-weather-derived"
SOURCE = "ecmwf_open_data"
SIGNAL_TYPE = "fire_weather_grid"
FORECAST_STEP_H = 24
PUBLICATION_DELAY_H = 4
CELL_SIZE = 0.25
THRESHOLD = int(os.environ.get("ECMWF_FW_THRESHOLD", "3"))
MIN_CLUSTER_CELLS = int(os.environ.get("ECMWF_MIN_CLUSTER_CELLS", "4"))
MAX_POLYGONS = int(os.environ.get("ECMWF_MAX_POLYGONS", "200"))
INSERT_BATCH = 25
DATABASE_URL = os.environ.get("DATABASE_URL")


def parse_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def candidate_cycles(now: datetime) -> list[tuple[datetime, datetime]]:
    """Return [(run_time, valid_time), ...] newest first (00/12 UTC oper)."""
    out: list[tuple[datetime, datetime]] = []
    day = now.date()
    for offset in range(0, 4):
        d = day - timedelta(days=offset)
        for hour in (12, 0):
            run_time = datetime(d.year, d.month, d.day, hour, tzinfo=timezone.utc)
            if now < run_time + timedelta(hours=PUBLICATION_DELAY_H):
                continue
            valid_time = run_time + timedelta(hours=FORECAST_STEP_H)
            out.append((run_time, valid_time))
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def download_grib(run_time: datetime, target: Path) -> None:
    from ecmwf.opendata import Client

    client = Client(source="ecmwf")
    client.retrieve(
        date=run_time.strftime("%Y%m%d"),
        time=run_time.hour,
        step=FORECAST_STEP_H,
        stream="oper",
        type="fc",
        param=["2t", "2d", "10u", "10v", "tp"],
        target=str(target),
    )


def open_fields(grib_path: Path) -> dict[str, xr.DataArray]:
    import cfgrib

    datasets = cfgrib.open_datasets(str(grib_path), indexpath="")
    fields: dict[str, xr.DataArray] = {}
    for ds in datasets:
        for name, da in ds.data_vars.items():
            short = da.attrs.get("GRIB_shortName") or name
            if short in {"2t", "2d", "10u", "10v", "tp"} and short not in fields:
                fields[short] = da.squeeze()
    needed = {"2t", "2d", "10u", "10v", "tp"}
    missing = needed - set(fields)
    if missing:
        raise RuntimeError(f"GRIB missing variables: {sorted(missing)}")
    return fields


def to_celsius(values: np.ndarray) -> np.ndarray:
    arr = values.astype(float)
    if np.nanmedian(arr) > 150:
        arr = arr - 273.15
    return arr


def to_mm(values: np.ndarray) -> np.ndarray:
    arr = values.astype(float)
    if np.nanmax(arr) < 10:
        arr = arr * 1000.0
    return arr


def compute_score(fields: dict[str, xr.DataArray]) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    t2m = to_celsius(fields["2t"].values)
    td2m = to_celsius(fields["2d"].values)
    u = fields["10u"].values.astype(float)
    v = fields["10v"].values.astype(float)
    tp = to_mm(fields["tp"].values)
    wind = np.sqrt(u * u + v * v)
    depression = t2m - td2m
    score = (
        (t2m > 30).astype(int)
        + (depression > 15).astype(int)
        + (wind > 6.9).astype(int)
        + (tp < 1).astype(int)
    )
    return score, {
        "t2m": t2m,
        "depression": depression,
        "wind": wind,
        "tp": tp,
    }


def cell_polygon(lon: float, lat: float, half: float = CELL_SIZE / 2) -> Polygon:
    return Polygon(
        [
            (lon - half, lat - half),
            (lon + half, lat - half),
            (lon + half, lat + half),
            (lon - half, lat + half),
            (lon - half, lat - half),
        ]
    )


def approx_area_km2(geom: Polygon) -> float:
    centroid = geom.centroid
    lat_rad = np.radians(centroid.y)
    km_per_deg_lat = 111.0
    km_per_deg_lon = 111.0 * max(np.cos(lat_rad), 0.01)
    bounds = geom.bounds
    width_km = (bounds[2] - bounds[0]) * km_per_deg_lon
    height_km = (bounds[3] - bounds[1]) * km_per_deg_lat
    return max(width_km * height_km, 0.0)


def polygons_from_mask(
    mask: np.ndarray,
    score_arr: np.ndarray,
    lats: np.ndarray,
    lons: np.ndarray,
    metrics: dict[str, np.ndarray],
) -> list[tuple[Polygon, dict]]:
    labeled, n_labels = ndimage.label(mask)
    if n_labels == 0:
        return []

    half = CELL_SIZE / 2
    results: list[tuple[Polygon, dict]] = []
    for label_id in range(1, n_labels + 1):
        ys, xs = np.where(labeled == label_id)
        if len(xs) < MIN_CLUSTER_CELLS:
            continue
        polys = [cell_polygon(float(lons[x]), float(lats[y]), half) for y, x in zip(ys, xs)]
        merged = make_valid(unary_union(polys))
        if merged.is_empty:
            continue
        parts = list(merged.geoms) if isinstance(merged, MultiPolygon) else [merged]
        for part in parts:
            if part.is_empty:
                continue
            cell_scores = [int(score_arr[y, x]) for y, x in zip(ys, xs)]
            payload_metrics = {
                "mean_temp_c": float(np.mean([metrics["t2m"][y, x] for y, x in zip(ys, xs)])),
                "mean_dewpoint_depression_c": float(
                    np.mean([metrics["depression"][y, x] for y, x in zip(ys, xs)])
                ),
                "mean_wind_ms": float(np.mean([metrics["wind"][y, x] for y, x in zip(ys, xs)])),
                "mean_precip_mm": float(np.mean([metrics["tp"][y, x] for y, x in zip(ys, xs)])),
                "score": int(round(float(np.mean(cell_scores)))),
                "area_km2": round(approx_area_km2(part), 1),
            }
            results.append((part, payload_metrics))
    results.sort(key=lambda item: item[1]["area_km2"], reverse=True)
    if len(results) > MAX_POLYGONS:
        print(f"[{SKILL_ID}] capping polygons {len(results)} -> {MAX_POLYGONS}")
        results = results[:MAX_POLYGONS]
    return results


def rows_from_polygons(
    polygons: list[tuple[Polygon, dict]],
    *,
    valid_time: datetime,
    cycle_time: datetime,
    now: datetime,
) -> list[dict]:
    rows: list[dict] = []
    for geom, metrics in polygons:
        payload = {
            **metrics,
            "threshold": THRESHOLD,
            "cycle_time": cycle_time.isoformat().replace("+00:00", "Z"),
            "forecast_step_h": FORECAST_STEP_H,
        }
        rows.append(
            {
                "timestamp": valid_time,
                "source": SOURCE,
                "signal_type": SIGNAL_TYPE,
                "geometry": json.dumps(mapping(geom)),
                "payload": json.dumps(payload),
                "ingested_at": now,
            }
        )
    return rows


def insert_batch(db: Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    sql = """
        INSERT INTO signals ("timestamp", source, signal_type, geometry, payload, ingested_at)
        VALUES (
            %(timestamp)s, %(source)s, %(signal_type)s,
            ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326)),
            %(payload)s::jsonb,
            %(ingested_at)s
        );
    """
    with db.cursor() as cur:
        cur.executemany(sql, rows)
    db.commit()
    return len(rows)


def insert_all(rows: list[dict], db: Connection | None = None) -> int:
    if not rows:
        return 0
    total = 0
    for i in range(0, len(rows), INSERT_BATCH):
        batch = rows[i : i + INSERT_BATCH]
        try:
            if db is not None:
                with db.cursor() as cur:
                    cur.execute("SELECT 1")
                total += insert_batch(db, batch)
                continue
        except psycopg.OperationalError:
            pass
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set")
        with psycopg.connect(DATABASE_URL, autocommit=False) as fresh:
            total += insert_batch(fresh, batch)
    return total


def process_cycle(now: datetime) -> list[dict]:
    last_error: Exception | None = None
    for run_time, valid_time in candidate_cycles(now):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                grib_path = Path(tmp) / "ecmwf.grib2"
                print(
                    f"[{SKILL_ID}] downloading cycle {run_time.isoformat()} "
                    f"(valid {valid_time.isoformat()})..."
                )
                download_grib(run_time, grib_path)
                fields = open_fields(grib_path)
                da = fields["2t"]
                lats = da.latitude.values
                lons = da.longitude.values
                score_arr, metrics = compute_score(fields)
                mask = score_arr >= THRESHOLD
                high_count = int(mask.sum())
                print(f"[{SKILL_ID}] high-score cells (>={THRESHOLD}): {high_count}")
                polygons = polygons_from_mask(mask, score_arr, lats, lons, metrics)
                print(f"[{SKILL_ID}] polygon regions: {len(polygons)}")
                return rows_from_polygons(
                    polygons,
                    valid_time=valid_time,
                    cycle_time=run_time,
                    now=now,
                )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"[{SKILL_ID}] WARNING: cycle {run_time} failed: {exc}", file=sys.stderr)
            continue
    if last_error:
        raise RuntimeError(f"all candidate cycles failed; last error: {last_error}")
    return []


def run(now: datetime, db: Connection | None = None) -> int:
    now = parse_now(now)
    rows = process_cycle(now)
    if not rows:
        print(f"[{SKILL_ID}] no polygon signals to insert.")
        return 0
    n = insert_all(rows, db)
    print(f"[{SKILL_ID}] inserted {n} polygon signal(s).")
    return n
