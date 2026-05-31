#!/usr/bin/env python3
"""AIFS MSLP/vorticity → cyclone_feature point signals."""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
from psycopg import Connection
from scipy.ndimage import gaussian_filter, minimum_filter
from shapely.geometry import Point, mapping

from aifs_common import (
    CYCLONE_STEPS,
    fetch_cycle_multi,
    lat_lon_from_field,
    parse_now,
    run_and_insert,
    signal_row,
    to_hpa,
)

SKILL_ID = "aifs-cyclone-feature"
SIGNAL_TYPE = "cyclone_feature"
MSLP_THRESHOLD_HPA = 1005.0
VORT_THRESHOLD = 1e-4
MATCH_KM = 300.0
MIN_PERSISTENCE = 2


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def feature_strength(mslp_hpa: float, vort: float) -> float:
    pressure_term = min(max((MSLP_THRESHOLD_HPA - mslp_hpa) / 20.0, 0.0), 1.0)
    vort_term = min(abs(vort) / 1e-3, 1.0)
    return round(0.5 * pressure_term + 0.5 * vort_term, 3)


def compute_vorticity_850(u: np.ndarray, v: np.ndarray, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Relative vorticity (s⁻¹) from 850 hPa wind components on a regular lat/lon grid."""
    lat2d, lon2d = np.meshgrid(lats, lons, indexing="ij") if lats.ndim == 1 else (lats, lons)
    lat_rad = np.radians(lat2d)
    dy_m = np.gradient(lat2d, axis=0) * 111_000.0
    dx_m = np.gradient(lon2d, axis=1) * 111_000.0 * np.maximum(np.cos(lat_rad), 0.01)
    du_dy = np.gradient(u, axis=0) / np.where(np.abs(dy_m) < 1, np.nan, dy_m)
    dv_dx = np.gradient(v, axis=1) / np.where(np.abs(dx_m) < 1, np.nan, dx_m)
    return np.nan_to_num(dv_dx - du_dy, nan=0.0)


def minima_at_step(
    msl: np.ndarray,
    vort: np.ndarray,
    lats: np.ndarray,
    lons: np.ndarray,
) -> list[dict]:
    msl_hpa = to_hpa(msl)
    smoothed = gaussian_filter(msl_hpa, sigma=2)
    local_min = smoothed == minimum_filter(smoothed, size=3, mode="nearest")
    ys, xs = np.where(local_min & (smoothed < MSLP_THRESHOLD_HPA) & (np.abs(vort) > VORT_THRESHOLD))
    out: list[dict] = []
    for y, x in zip(ys.tolist(), xs.tolist()):
        lat = float(lats[y] if lats.ndim == 1 else lats[y, x])
        lon = float(lons[x] if lons.ndim == 1 else lons[y, x])
        out.append(
            {
                "y": y,
                "x": x,
                "lat": lat,
                "lon": lon,
                "mslp_hpa": float(smoothed[y, x]),
                "vorticity_850_s-1": float(vort[y, x]),
            }
        )
    return out


def track_features(step_features: dict[int, list[dict]]) -> list[dict]:
    tracks: list[dict] = []
    for step in sorted(step_features):
        feats = step_features[step]
        used = [False] * len(feats)
        if not tracks:
            for feat in feats:
                tracks.append({"feature_id": str(uuid.uuid4()), "points": {step: feat}})
            continue
        for track in tracks:
            last_step = max(track["points"])
            last = track["points"][last_step]
            best_i = None
            best_dist = MATCH_KM
            for i, feat in enumerate(feats):
                if used[i]:
                    continue
                dist = haversine_km(last["lat"], last["lon"], feat["lat"], feat["lon"])
                if dist <= best_dist:
                    best_dist = dist
                    best_i = i
            if best_i is not None:
                used[best_i] = True
                track["points"][step] = feats[best_i]
        for i, feat in enumerate(feats):
            if not used[i]:
                tracks.append({"feature_id": str(uuid.uuid4()), "points": {step: feat}})
    return [t for t in tracks if len(t["points"]) >= MIN_PERSISTENCE]


def build_rows(
    tracks: list[dict],
    *,
    run_time: datetime,
    now: datetime,
) -> list[dict]:
    rows: list[dict] = []
    run_iso = run_time.isoformat().replace("+00:00", "Z")
    for track in tracks:
        for step, feat in track["points"].items():
            valid_time = run_time + timedelta(hours=int(step))
            payload = {
                "feature_id": track["feature_id"],
                "mslp_hpa": round(feat["mslp_hpa"], 1),
                "vorticity_850_s-1": feat["vorticity_850_s-1"],
                "feature_strength": feature_strength(feat["mslp_hpa"], feat["vorticity_850_s-1"]),
                "forecast_hour": int(step),
                "run_time": run_iso,
            }
            rows.append(
                signal_row(
                    timestamp=valid_time,
                    signal_type=SIGNAL_TYPE,
                    geometry=mapping(Point(feat["lon"], feat["lat"])),
                    payload=payload,
                    now=now,
                )
            )
    return rows


def run(now: datetime, db: Connection | None = None) -> int:
    now = parse_now(now)
    run_time, _valid_time, fields = fetch_cycle_multi(
        now,
        skill_id=SKILL_ID,
        downloads=[
            {"params": ["msl"], "steps": list(CYCLONE_STEPS)},
            {"params": ["u", "v"], "steps": list(CYCLONE_STEPS), "levelist": 850},
        ],
    )
    msl_key = next(k for k in fields if k[0] == "msl")
    lats, lons = lat_lon_from_field(fields[msl_key])

    step_features: dict[int, list[dict]] = {}
    for step in CYCLONE_STEPS:
        msl_da = fields.get(("msl", step))
        u_da = fields.get(("u", step))
        v_da = fields.get(("v", step))
        if msl_da is None or u_da is None or v_da is None:
            continue
        vort = compute_vorticity_850(
            u_da.values.astype(float),
            v_da.values.astype(float),
            lats,
            lons,
        )
        step_features[step] = minima_at_step(msl_da.values, vort, lats, lons)

    tracks = track_features(step_features)
    print(f"[{SKILL_ID}] tracks (>={MIN_PERSISTENCE} steps): {len(tracks)}")
    rows = build_rows(tracks, run_time=run_time, now=now)
    return run_and_insert(now, db, skill_id=SKILL_ID, rows=rows)
