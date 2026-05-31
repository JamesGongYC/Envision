"""Shared AIFS Open Data download, parsing, and Neon insert helpers."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
import xarray as xr
from psycopg import Connection

SOURCE = "aifs"
PUBLICATION_DELAY_H = 5
FORECAST_STEP_H = 24
CYCLONE_STEPS = (0, 24, 48, 72)
INSERT_BATCH = 25
DATABASE_URL = os.environ.get("DATABASE_URL")


def parse_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def candidate_cycles(
    now: datetime,
    *,
    delay_h: int = PUBLICATION_DELAY_H,
    primary_step_h: int = FORECAST_STEP_H,
) -> list[tuple[datetime, datetime]]:
    """Return [(run_time, valid_time_at_primary_step), ...] newest first."""
    out: list[tuple[datetime, datetime]] = []
    day = now.date()
    for offset in range(0, 4):
        d = day - timedelta(days=offset)
        for hour in (12, 0):
            run_time = datetime(d.year, d.month, d.day, hour, tzinfo=timezone.utc)
            if now < run_time + timedelta(hours=delay_h):
                continue
            valid_time = run_time + timedelta(hours=primary_step_h)
            out.append((run_time, valid_time))
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def to_celsius(values: np.ndarray) -> np.ndarray:
    arr = values.astype(float)
    if np.nanmedian(arr) > 150:
        arr = arr - 273.15
    return arr


def to_hpa(values: np.ndarray) -> np.ndarray:
    arr = values.astype(float)
    if np.nanmedian(arr) > 5000:
        arr = arr / 100.0
    return arr


def to_mm(values: np.ndarray) -> np.ndarray:
    arr = values.astype(float)
    if np.nanmax(arr) < 10:
        arr = arr * 1000.0
    return arr


def _step_hours(step_val: Any) -> int:
    if isinstance(step_val, np.timedelta64):
        return int(step_val / np.timedelta64(1, "h"))
    if hasattr(step_val, "total_seconds"):
        return int(step_val.total_seconds() // 3600)
    return int(step_val)


def _step_value(da: xr.DataArray) -> int | None:
    if "step" not in da.coords:
        return None
    step = da.coords["step"].values
    if hasattr(step, "tolist"):
        step = step.tolist()
    if isinstance(step, list):
        return _step_hours(step[0]) if step else None
    return _step_hours(step)


def _level_value(da: xr.DataArray) -> int | None:
    for key in ("isobaricInhPa", "level", "heightAboveGround"):
        if key not in da.coords:
            continue
        val = da.coords[key].values
        if hasattr(val, "tolist"):
            val = val.tolist()
        if isinstance(val, list):
            return int(val[0]) if val else None
        return int(val)
    return None


def download_aifs(
    run_time: datetime,
    target: Path,
    *,
    params: list[str],
    steps: list[int] | int,
    levelist: int | None = None,
) -> None:
    from ecmwf.opendata import Client

    client = Client(source="ecmwf", model="aifs-single")
    kwargs: dict[str, Any] = {
        "date": run_time.strftime("%Y%m%d"),
        "time": run_time.hour,
        "step": steps,
        "type": "fc",
        "param": params,
        "target": str(target),
    }
    if levelist is not None:
        kwargs["levelist"] = levelist
        kwargs["levtype"] = "pl"
    client.retrieve(**kwargs)


def open_fields(grib_path: Path, expected: set[str] | None = None) -> dict[tuple[str, int], xr.DataArray]:
    import cfgrib

    fields: dict[tuple[str, int], xr.DataArray] = {}
    datasets = cfgrib.open_datasets(str(grib_path), indexpath="")
    for ds in datasets:
        for _name, da in ds.data_vars.items():
            short = da.attrs.get("GRIB_shortName") or _name
            da = da.squeeze()
            if "step" in da.dims:
                for step_val in da.coords["step"].values:
                    step_h = _step_hours(step_val)
                    key = (short, step_h)
                    if key not in fields:
                        sliced = da.sel(step=step_val).drop_vars("step", errors="ignore")
                        fields[key] = sliced.squeeze()
            else:
                step = _step_value(da)
                if step is None:
                    step = FORECAST_STEP_H
                key = (short, step)
                if key not in fields:
                    fields[key] = da
    if expected:
        found = {k[0] for k in fields}
        missing = expected - found
        if missing:
            raise RuntimeError(f"GRIB missing variables: {sorted(missing)}")
    return fields


def load_fields_eager(fields: dict[tuple[str, int], xr.DataArray]) -> dict[tuple[str, int], xr.DataArray]:
    """Materialize lazy cfgrib arrays so temp GRIB files can be deleted."""
    eager: dict[tuple[str, int], xr.DataArray] = {}
    for key, da in fields.items():
        values = np.array(da.data if hasattr(da, "data") else da.values, copy=True)
        coords = {c: np.array(da.coords[c].values, copy=True) for c in da.coords}
        eager[key] = xr.DataArray(values, coords=coords, dims=da.dims, attrs=dict(da.attrs))
    return eager


def fetch_cycle(
    now: datetime,
    *,
    skill_id: str,
    params: list[str],
    steps: list[int] | int,
    levelist: int | None = None,
) -> tuple[datetime, datetime, dict[tuple[str, int], xr.DataArray]]:
    last_error: Exception | None = None
    for run_time, valid_time in candidate_cycles(now):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                grib_path = Path(tmp) / "aifs.grib2"
                print(f"[{skill_id}] downloading cycle {run_time.isoformat()}...")
                download_aifs(run_time, grib_path, params=params, steps=steps, levelist=levelist)
                fields = load_fields_eager(open_fields(grib_path, expected=set(params)))
                return run_time, valid_time, fields
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"[{skill_id}] WARNING: cycle {run_time} failed: {exc}")
            continue
    if last_error:
        raise RuntimeError(f"all candidate cycles failed; last error: {last_error}")
    raise RuntimeError("no candidate cycles available")


def fetch_cycle_multi(
    now: datetime,
    *,
    skill_id: str,
    downloads: list[dict[str, Any]],
) -> tuple[datetime, datetime, dict[tuple[str, int], xr.DataArray]]:
    """Try candidate cycles; each download spec merges into one field map."""
    last_error: Exception | None = None
    for run_time, valid_time in candidate_cycles(now):
        try:
            merged: dict[tuple[str, int], xr.DataArray] = {}
            with tempfile.TemporaryDirectory() as tmp:
                for i, spec in enumerate(downloads):
                    grib_path = Path(tmp) / f"aifs_{i}.grib2"
                    print(f"[{skill_id}] downloading cycle {run_time.isoformat()} ({spec})...")
                    download_aifs(
                        run_time,
                        grib_path,
                        params=spec["params"],
                        steps=spec["steps"],
                        levelist=spec.get("levelist"),
                    )
                    merged.update(
                        load_fields_eager(open_fields(grib_path, expected=set(spec["params"])))
                    )
            return run_time, valid_time, merged
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"[{skill_id}] WARNING: cycle {run_time} failed: {exc}")
            continue
    if last_error:
        raise RuntimeError(f"all candidate cycles failed; last error: {last_error}")
    raise RuntimeError("no candidate cycles available")


def lat_lon_from_field(da: xr.DataArray) -> tuple[np.ndarray, np.ndarray]:
    lats = da.latitude.values
    lons = da.longitude.values
    return lats, lons


def signal_row(
    *,
    timestamp: datetime,
    signal_type: str,
    geometry: dict,
    payload: dict,
    now: datetime,
) -> dict:
    return {
        "timestamp": timestamp,
        "source": SOURCE,
        "signal_type": signal_type,
        "geometry": json.dumps(geometry),
        "payload": json.dumps(payload),
        "ingested_at": now,
    }


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


def run_and_insert(
    now: datetime,
    db: Connection | None,
    *,
    skill_id: str,
    rows: list[dict],
) -> int:
    now = parse_now(now)
    if not rows:
        print(f"[{skill_id}] no signals to insert.")
        return 0
    n = insert_all(rows, db)
    print(f"[{skill_id}] inserted {n} signal(s).")
    return n
