#!/usr/bin/env python3
"""Envision ingestion: NASA FIRMS active fire hotspots -> signals.

Fetches near-real-time fire detections (MODIS/VIIRS) across six continental
bounding boxes and writes each hotspot as a point Signal in PostGIS.

FIRMS Area API:
  https://firms.modaps.eosdis.nasa.gov/api/area/csv/[KEY]/[SOURCE]/[AREA]/[DAYS]
  AREA is 'world' or a bbox 'west,south,east,north'. DAYS is 1-10.

Requires:
  - env DATABASE_URL    (Neon connection string)
  - env FIRMS_MAP_KEY   (from https://firms.modaps.eosdis.nasa.gov/api/map_key/)
Optional env:
  - FIRMS_DAYS     (default 1)
  - FIRMS_MAX_ROWS (default 8000 per bbox/source call)
  - FIRMS_AREA     (debug override: single bbox instead of 6-region loop)
  - FIRMS_SOURCE   (debug override: single source instead of VIIRS+MODIS)
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from datetime import datetime, timezone

import httpx
import psycopg
from psycopg import Connection

BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

DAYS = os.environ.get("FIRMS_DAYS", "1")
MAX_ROWS = int(os.environ.get("FIRMS_MAX_ROWS", "8000"))

SOURCES = ("VIIRS_NOAA20_NRT", "MODIS_NRT")

REGIONS: list[tuple[str, str]] = [
    ("North America", "-170,15,-50,80"),
    ("South America", "-90,-60,-30,15"),
    ("Europe", "-15,35,60,80"),
    ("Africa", "-20,-40,55,40"),
    ("Asia", "60,-10,180,80"),
    ("Oceania", "110,-50,180,10"),
]

DATABASE_URL = os.environ.get("DATABASE_URL")


def parse_now(argv: list[str] | None = None) -> datetime:
    p = argparse.ArgumentParser(description="Ingest FIRMS active fire hotspots")
    p.add_argument("--now", default=None, help="ISO8601 UTC run time (default: now)")
    args = p.parse_args(argv)
    if args.now is None:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def normalize_source(source: str) -> str:
    s = source.upper()
    if "VIIRS" in s:
        return "firms_viirs"
    if "MODIS" in s:
        return "firms_modis"
    return "firms"


def fetch_hotspots(source: str, bbox: str, region: str) -> list[dict] | None:
    """Return CSV rows or None on failure (logged, non-fatal)."""
    key = os.environ.get("FIRMS_MAP_KEY")
    if not key:
        sys.exit(
            "FIRMS_MAP_KEY is not set. Get one at "
            "https://firms.modaps.eosdis.nasa.gov/api/map_key/ and add it to ~/.hermes/.env"
        )
    url = f"{BASE}/{key}/{source}/{bbox}/{DAYS}"
    try:
        resp = httpx.get(url, timeout=60.0)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        print(f"[firms] WARNING: {region} {source} request failed: {e}", file=sys.stderr)
        return None
    text = resp.text
    first_line = text.split("\n", 1)[0].lower()
    if "latitude" not in first_line:
        print(
            f"[firms] WARNING: {region} {source} unexpected response:\n{text[:200]}",
            file=sys.stderr,
        )
        return None
    rows = list(csv.DictReader(io.StringIO(text)))
    if len(rows) > MAX_ROWS:
        print(
            f"[firms] Capping {region} {source}: {len(rows)} -> {MAX_ROWS} hotspots."
        )
        rows = rows[:MAX_ROWS]
    return rows


def to_params(row: dict, source_label: str, now: datetime) -> dict | None:
    try:
        lon = float(row["longitude"])
        lat = float(row["latitude"])
    except (KeyError, ValueError):
        return None
    hhmm = str(row.get("acq_time", "0")).zfill(4)
    try:
        ts = datetime.strptime(
            f"{row['acq_date']} {hhmm}", "%Y-%m-%d %H%M"
        ).replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        ts = now
    geometry = {"type": "Point", "coordinates": [lon, lat]}
    return {
        "timestamp": ts,
        "source": source_label,
        "signal_type": "hotspot",
        "geometry": json.dumps(geometry),
        "payload": json.dumps(row),
        "ingested_at": now,
    }


def insert_many(db: Connection, rows: list[dict]) -> int:
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


def iter_queries() -> list[tuple[str, str, str]]:
    """Return (region_name, source, bbox) for each API call."""
    debug_area = os.environ.get("FIRMS_AREA")
    debug_source = os.environ.get("FIRMS_SOURCE")
    if debug_area or debug_source:
        regions = [("debug", debug_area or REGIONS[0][1])]
        sources = [debug_source] if debug_source else list(SOURCES)
    else:
        regions = REGIONS
        sources = list(SOURCES)
    return [
        (region_name, source, bbox)
        for region_name, bbox in regions
        for source in sources
    ]


def run(now: datetime, db: Connection) -> tuple[int, int]:
    """Returns (rows_inserted, queries_succeeded)."""
    params: list[dict] = []
    succeeded = 0
    failed = 0

    for region_name, source, bbox in iter_queries():
        raw = fetch_hotspots(source, bbox, region_name)
        if raw is None:
            failed += 1
            continue
        succeeded += 1
        label = normalize_source(source)
        batch = [p for r in raw if (p := to_params(r, label, now)) is not None]
        params.extend(batch)
        print(f"[firms] {region_name} {source}: fetched {len(batch)} hotspots.")

    if succeeded == 0:
        print("[firms] All bbox/source queries failed.", file=sys.stderr)
        return 0, 0

    n = insert_many(db, params)
    print(
        f"[firms] Inserted {n} FIRMS hotspots "
        f"({succeeded} queries ok, {failed} failed)."
    )
    return n, succeeded


def main() -> int:
    if not DATABASE_URL:
        sys.exit("DATABASE_URL is not set. Add it to ~/.hermes/.env")
    now = parse_now()
    with psycopg.connect(DATABASE_URL) as db:
        _n, succeeded = run(now, db)
    return 0 if succeeded > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
