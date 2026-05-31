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

_AGENT_LIB = Path(__file__).resolve().parents[4] / "lib"
if str(_AGENT_LIB) not in sys.path:
    sys.path.insert(0, str(_AGENT_LIB))
from trace_builder import TraceBuilder  # noqa: E402

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


def count_nws_polygons(conn: Connection, now: datetime) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)::int
            FROM signals
            WHERE source = 'nws_alerts'
              AND signal_type = 'fire_warning'
              AND ingested_at > %s - interval '24 hours'
              AND timestamp <= %s
              AND geometry IS NOT NULL
            """,
            (now, now),
        )
        return cur.fetchone()[0]


def alerts_intersecting(
    conn: Connection, cluster_geom_geojson: dict, now: datetime
) -> list[tuple]:
    """Return [(id, payload)] for active fire-weather alerts intersecting geom."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, payload
            FROM signals
            WHERE source = 'nws_alerts'
              AND signal_type = 'fire_warning'
              AND ingested_at > %s - interval '24 hours'
              AND timestamp <= %s
              AND geometry IS NOT NULL
              AND ST_Intersects(
                geometry,
                ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)
              )
            """,
            (now, now, json.dumps(cluster_geom_geojson)),
        )
        return cur.fetchall()


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


def build_reasoning(n_hotspots: int, alert_names: list[str], centroid_xy) -> str:
    names = sorted({n for n in alert_names if n}) or ["unnamed fire-weather alert"]
    lon, lat = centroid_xy
    return (
        f"DBSCAN cluster of {n_hotspots} FIRMS hotspots (eps={EPS_KM:.0f}km, "
        f"min_samples={MIN_SAMPLES}) in the last {LOOKBACK_HOURS}h, centered "
        f"near ({lat:.3f}, {lon:.3f}). Intersects active NWS fire-weather "
        f"alert(s): {', '.join(names)}."
    )


# --- write ----------------------------------------------------------------
def insert_forecast(conn: Connection, forecast: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO forecasts (
              id, issued_at, valid_from, valid_until,
              disaster_class, geometry, probability,
              skill_id, skill_version, contributing_signal_ids,
              reasoning, is_baseline, trace
            ) VALUES (
              %(id)s, %(issued_at)s, %(valid_from)s, %(valid_until)s,
              %(disaster_class)s,
              ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326)),
              %(probability)s,
              %(skill_id)s, %(skill_version)s,
              %(contributing_signal_ids)s::uuid[],
              %(reasoning)s, %(is_baseline)s,
              %(trace)s::jsonb
            )
            """,
            forecast,
        )


# --- run ------------------------------------------------------------------
def run(now: datetime, db: Connection) -> int:
    valid_until = now + timedelta(hours=FORECAST_VALID_HOURS)

    hotspots = load_recent_hotspots(db, now)
    if len(hotspots) < MIN_SAMPLES:
        print(f"[{SKILL_ID}] only {len(hotspots)} hotspots in last "
              f"{LOOKBACK_HOURS}h; skipping.")
        return 0

    clusters = cluster_hotspots(hotspots)
    print(f"[{SKILL_ID}] {len(hotspots)} hotspots → {len(clusters)} clusters.")
    polygon_count_nws = count_nws_polygons(db, now)

    written = 0
    selected_clusters = []
    cluster_bboxes: list[list[float]] = []
    for label, points in clusters:
        geom = cluster_geometry(points)
        geom_geojson = mapping(geom)

        matches = alerts_intersecting(db, geom_geojson, now)
        if not matches:
            continue

        centroid = geom.centroid
        minx, miny, maxx, maxy = geom.bounds
        cluster_bboxes.append(
            [float(minx), float(miny), float(maxx), float(maxy)]
        )
        selected_clusters.append({
            "cluster_id": str(label),
            "size": len(points),
            "centroid_lat_lon": [float(centroid.y), float(centroid.x)],
            "intersecting_polygon_id": str(matches[0][0]),
        })

        alert_names: list[str] = []
        for _aid, payload in matches:
            if isinstance(payload, dict):
                alert_names.append(
                    payload.get("event")
                    or payload.get("headline")
                    or "fire alert"
                )

        prob = score_probability(len(points), len(matches))
        reasoning = build_reasoning(
            len(points), alert_names, (centroid.x, centroid.y)
        )

        contributing = [str(p[0]) for p in points] + [
            str(aid) for aid, _ in matches
        ]

        sc = selected_clusters[-1]
        tb = TraceBuilder(now, SKILL_ID)
        tb.set_inputs(
            hotspot_count=len(hotspots),
            polygon_count_nws=polygon_count_nws,
            polygon_count_ecmwf=0,
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

        forecast = {
            "id": str(uuid.uuid4()),
            "issued_at": now,
            "valid_from": now,
            "valid_until": valid_until,
            "disaster_class": "wildfire",
            "geometry": json.dumps(geom_geojson),
            "probability": prob,
            "skill_id": SKILL_ID,
            "skill_version": SKILL_VERSION,
            "contributing_signal_ids": contributing,
            "reasoning": reasoning,
            "is_baseline": False,
            "trace": json.dumps(tb.build()),
        }
        insert_forecast(db, forecast)
        written += 1
        print(f"[{SKILL_ID}]   cluster#{label}: "
              f"n={len(points)} p={prob} alerts={len(matches)}")

    db.commit()
    print(f"[{SKILL_ID}] wrote {written} forecasts.")
    return written


def main() -> int:
    now = parse_now()
    with psycopg.connect(DATABASE_URL, autocommit=False) as db:
        run(now, db)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"[{SKILL_ID}] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
