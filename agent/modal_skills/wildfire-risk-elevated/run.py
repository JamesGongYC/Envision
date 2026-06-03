#!/usr/bin/env python3
"""
wildfire_risk_elevated — Envision detection skill (Day 3, v1).

Reads recent FIRMS hotspots and active NWS fire-weather alerts from `signals`,
clusters the hotspots with DBSCAN (eps=10km, min_samples=5), keeps clusters
whose convex hull intersects an active alert polygon, and writes one
Forecast row per surviving cluster.

No baseline twin in v1 (MVP). Reasoning is templated, not LLM-generated.
Probability is capped server-side at 0.85 by a CHECK constraint.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import psycopg
from psycopg import Connection
from sklearn.cluster import DBSCAN
from shapely.geometry import MultiPoint, Point, mapping

for _lib in ("/root/agent_lib", Path(__file__).resolve().parents[2] / "lib"):
    _lp = str(_lib)
    if os.path.isdir(_lp) and _lp not in sys.path:
        sys.path.insert(0, _lp)
        break
from trace_builder import TraceBuilder  # noqa: E402
from reasoning_llm import generate_reasoning  # noqa: E402
from reasoning_prompts import prompt_wildfire_risk_elevated  # noqa: E402
from forecast_model import Forecast  # noqa: E402
from signal_temporal import (  # noqa: E402
    nws_fire_warning_active_sql,
    trailing_timestamp_sql,
)

# --- config ---------------------------------------------------------------
SKILL_ID = "wildfire_risk_elevated"
SKILL_VERSION = 1

LOOKBACK_HOURS = 24
EPS_KM = 10.0
MIN_SAMPLES = 5
KMS_PER_RADIAN = 6371.0088
CLUSTER_BUFFER_DEG = 0.05  # ~5.5 km at equator; coarse but OK for v1
FORECAST_VALID_HOURS = 24  # 0–24h nowcast per plan §1

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print(f"[{SKILL_ID}] DATABASE_URL not set", file=sys.stderr)
    sys.exit(2)


def parse_now(argv: list[str] | None = None) -> datetime:
    p = argparse.ArgumentParser(description="Detect elevated wildfire risk")
    p.add_argument("--now", default=None, help="ISO8601 UTC cutoff (default: now)")
    args = p.parse_args(argv)
    if args.now is None:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --- data access ----------------------------------------------------------
def load_recent_hotspots(conn: Connection, now: datetime) -> list[tuple]:
    """Return [(id, lon, lat), ...] for FIRMS hotspots in last LOOKBACK_HOURS."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id,
                   ST_X(geometry) AS lon,
                   ST_Y(geometry) AS lat
            FROM signals
            WHERE signal_type = 'hotspot'
              AND source LIKE 'firms%%'
              AND timestamp > %s - interval '{LOOKBACK_HOURS} hours'
              AND timestamp <= %s
            """,
            (now, now),
        )
        return cur.fetchall()


def count_fire_polygons(conn: Connection, now: datetime) -> tuple[int, int]:
    """Return (nws_fire_warning_count, grid_polygon_count)."""
    ts_win = trailing_timestamp_sql(LOOKBACK_HOURS)
    nws_active = nws_fire_warning_active_sql()
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
              COUNT(*) FILTER (
                WHERE signal_type = 'fire_warning' AND source = 'nws_alerts'
              )::int AS nws_n,
              COUNT(*) FILTER (
                WHERE signal_type = 'fire_weather_grid'
                  AND source IN ('ecmwf_open_data', 'aifs')
              )::int AS grid_n
            FROM signals
            WHERE signal_type IN ('fire_warning', 'fire_weather_grid')
              AND source IN ('nws_alerts', 'ecmwf_open_data', 'aifs')
              AND {ts_win}
              AND {nws_active}
              AND geometry IS NOT NULL
            """,
            (now, now, now, now),
        )
        row = cur.fetchone()
        return (row[0] or 0, row[1] or 0)


def polygons_intersecting(
    conn: Connection, cluster_geom_geojson: dict, now: datetime
) -> list[tuple]:
    """Return [(id, payload, source, signal_type)] intersecting cluster."""
    ts_win = trailing_timestamp_sql(LOOKBACK_HOURS)
    nws_active = nws_fire_warning_active_sql()
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, payload, source, signal_type
            FROM signals
            WHERE signal_type IN ('fire_warning', 'fire_weather_grid')
              AND source IN ('nws_alerts', 'ecmwf_open_data', 'aifs')
              AND {ts_win}
              AND {nws_active}
              AND geometry IS NOT NULL
              AND ST_Intersects(
                geometry,
                ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)
              )
            """,
            (now, now, now, now, json.dumps(cluster_geom_geojson)),
        )
        return cur.fetchall()


def polygon_source_label(source: str, signal_type: str) -> str:
    if signal_type == "fire_warning":
        return "NWS Red Flag Warning / Fire Weather Watch"
    if source == "ecmwf_open_data":
        return "ECMWF fire weather index"
    if source == "aifs":
        return "AIFS fire weather grid"
    return "fire weather grid"


def polygon_summary(matches: list[tuple]) -> str:
    parts: list[str] = []
    for _id, payload, source, signal_type in matches[:3]:
        label = polygon_source_label(source, signal_type)
        if isinstance(payload, dict):
            extra = (
                payload.get("event")
                or payload.get("headline")
                or payload.get("region")
                or payload.get("index_name")
            )
            if extra:
                parts.append(f"{label}: {extra}")
                continue
        parts.append(label)
    return "; ".join(parts) if parts else "active fire-weather polygon"


# --- clustering -----------------------------------------------------------
def cluster_hotspots(hotspots: list[tuple]) -> list[tuple[int, list[tuple]]]:
    """DBSCAN on (lat, lon) in radians with haversine metric. Returns
    [(cluster_label, [(id, lon, lat), ...]), ...] excluding noise (label=-1)."""
    if len(hotspots) < MIN_SAMPLES:
        return []
    coords_deg = np.array([[h[2], h[1]] for h in hotspots])  # (lat, lon)
    coords_rad = np.radians(coords_deg)
    eps_rad = EPS_KM / KMS_PER_RADIAN
    labels = DBSCAN(
        eps=eps_rad, min_samples=MIN_SAMPLES, metric="haversine"
    ).fit_predict(coords_rad)
    clusters: dict[int, list[tuple]] = {}
    for h, lab in zip(hotspots, labels):
        if lab == -1:
            continue
        clusters.setdefault(int(lab), []).append(h)
    return list(clusters.items())


def cluster_geometry(cluster_points: list[tuple]):
    """Convex hull of cluster, buffered to a polygon."""
    pts = [Point(lon, lat) for (_id, lon, lat) in cluster_points]
    hull = MultiPoint(pts).convex_hull  # may be Point/LineString for small N
    return hull.buffer(CLUSTER_BUFFER_DEG)


# --- scoring & reasoning --------------------------------------------------
def probability_components(n_hotspots: int, n_alerts_overlap: int) -> dict:
    base = 0.40
    cluster_size_factor = min(0.30, 0.02 * max(0, n_hotspots - MIN_SAMPLES))
    polygon_overlap_factor = min(0.30, 0.15 * n_alerts_overlap)
    return {
        "base": base,
        "cluster_size_factor": cluster_size_factor,
        "polygon_overlap_factor": polygon_overlap_factor,
    }


def score_probability(n_hotspots: int, n_alerts_overlap: int) -> float:
    """Crude additive scoring; DB caps at 0.85 anyway."""
    parts = probability_components(n_hotspots, n_alerts_overlap)
    return round(
        min(
            0.85,
            parts["base"]
            + parts["cluster_size_factor"]
            + parts["polygon_overlap_factor"],
        ),
        3,
    )


def build_reasoning(
    n_hotspots: int,
    polygon_source: str,
    polygon_summary_text: str,
    centroid_xy,
) -> str:
    lon, lat = centroid_xy
    return (
        f"DBSCAN cluster of {n_hotspots} FIRMS hotspots (eps={EPS_KM:.0f}km, "
        f"min_samples={MIN_SAMPLES}) in the last {LOOKBACK_HOURS}h, centered "
        f"near ({lat:.3f}, {lon:.3f}). Intersects {polygon_source}: "
        f"{polygon_summary_text}."
    )


# --- run ------------------------------------------------------------------
def run(now: datetime, db: Connection) -> list[Forecast]:
    valid_until = now + timedelta(hours=FORECAST_VALID_HOURS)

    hotspots = load_recent_hotspots(db, now)
    if len(hotspots) < MIN_SAMPLES:
        print(f"[{SKILL_ID}] only {len(hotspots)} hotspots in last "
              f"{LOOKBACK_HOURS}h; skipping.")
        return []

    clusters = cluster_hotspots(hotspots)
    print(f"[{SKILL_ID}] {len(hotspots)} hotspots → {len(clusters)} clusters.")
    polygon_count_nws, polygon_count_ecmwf = count_fire_polygons(db, now)

    out: list[Forecast] = []
    selected_clusters = []
    cluster_bboxes: list[list[float]] = []
    for label, points in clusters:
        geom = cluster_geometry(points)
        geom_geojson = mapping(geom)

        matches = polygons_intersecting(db, geom_geojson, now)
        if not matches:
            continue

        centroid = geom.centroid
        minx, miny, maxx, maxy = geom.bounds
        cluster_bboxes.append(
            [float(minx), float(miny), float(maxx), float(maxy)]
        )
        first_source = matches[0][2]
        first_type = matches[0][3]
        selected_clusters.append({
            "cluster_id": str(label),
            "size": len(points),
            "centroid_lat_lon": [float(centroid.y), float(centroid.x)],
            "intersecting_polygon_id": str(matches[0][0]),
            "polygon_source": first_source,
            "polygon_signal_type": first_type,
        })

        src_label = polygon_source_label(first_source, first_type)
        summary_text = polygon_summary(matches)
        prob = score_probability(len(points), len(matches))
        fallback = build_reasoning(
            len(points), src_label, summary_text, (centroid.x, centroid.y)
        )

        contributing = [str(p[0]) for p in points] + [
            str(m[0]) for m in matches
        ]

        sc = selected_clusters[-1]
        tb = TraceBuilder(now, SKILL_ID)
        window_start = now - timedelta(hours=LOOKBACK_HOURS)
        tb.set_inputs(
            hotspot_count=len(hotspots),
            polygon_count_nws=polygon_count_nws,
            polygon_count_ecmwf=polygon_count_ecmwf,
            window_start=window_start.isoformat(),
            window_end=now.isoformat(),
        )
        tb.set_intermediate(
            clusters_found=len(clusters),
            selected_clusters=[sc],
        )
        tb.add_geometry_step(
            "dbscan_params",
            eps_km=EPS_KM,
            min_samples=MIN_SAMPLES,
        )
        tb.add_geometry_step(
            "cluster_bboxes",
            bboxes=[cluster_bboxes[-1]],
        )
        tb.set_probability_components(
            **probability_components(len(points), len(matches))
        )

        trace_dict = tb.build()
        cluster_radius_km = EPS_KM * 2
        prompt = prompt_wildfire_risk_elevated(
            trace_dict,
            float(centroid.y),
            float(centroid.x),
            len(points),
            cluster_radius_km,
            src_label,
            summary_text,
        )
        reasoning = generate_reasoning(prompt, fallback)

        out.append(
            Forecast(
                id=str(uuid.uuid4()),
                issued_at=now,
                valid_from=now,
                valid_until=valid_until,
                disaster_class="wildfire",
                geometry=json.dumps(geom_geojson),
                probability=prob,
                skill_id=SKILL_ID,
                skill_version=SKILL_VERSION,
                contributing_signal_ids=contributing,
                reasoning=reasoning,
                is_baseline=False,
                trace=trace_dict,
            )
        )
        print(f"[{SKILL_ID}]   cluster#{label}: "
              f"n={len(points)} p={prob} alerts={len(matches)}")

    print(f"[{SKILL_ID}] emitted {len(out)} forecast(s).")
    return out
