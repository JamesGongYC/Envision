#!/usr/bin/env python3
"""Envision ingestion: NASA FIRMS active fire hotspots -> signals.

Fetches near-real-time fire detections (MODIS/VIIRS) for a bounding box and
writes each hotspot as a point Signal in PostGIS.

FIRMS Area API:
  https://firms.modaps.eosdis.nasa.gov/api/area/csv/[KEY]/[SOURCE]/[AREA]/[DAYS]
  AREA is 'world' or a bbox 'west,south,east,north'. DAYS is 1-10.

Requires:
  - env DATABASE_URL    (Neon connection string)
  - env FIRMS_MAP_KEY   (from https://firms.modaps.eosdis.nasa.gov/api/map_key/)
Optional env:
  - FIRMS_SOURCE   (default VIIRS_NOAA20_NRT)
  - FIRMS_AREA     (default western US bbox; 'world' for global)
  - FIRMS_DAYS     (default 1)
  - FIRMS_MAX_ROWS (default 2000 — safety cap so 'world' can't flood the DB)
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
from datetime import datetime, timezone

import httpx
import psycopg

BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

SOURCE = os.environ.get("FIRMS_SOURCE", "VIIRS_NOAA20_NRT")
AREA = os.environ.get("FIRMS_AREA", "-125,31,-103,49")   # western US
DAYS = os.environ.get("FIRMS_DAYS", "1")
MAX_ROWS = int(os.environ.get("FIRMS_MAX_ROWS", "2000"))


def fetch_hotspots() -> list[dict]:
    key = os.environ.get("FIRMS_MAP_KEY")
    if not key:
        sys.exit(
            "FIRMS_MAP_KEY is not set. Get one at "
            "https://firms.modaps.eosdis.nasa.gov/api/map_key/ and add it to ~/.hermes/.env"
        )
    url = f"{BASE}/{key}/{SOURCE}/{AREA}/{DAYS}"
    resp = httpx.get(url, timeout=60.0)
    resp.raise_for_status()
    text = resp.text
    # A valid response is CSV whose header contains 'latitude'.
    first_line = text.split("\n", 1)[0].lower()
    if "latitude" not in first_line:
        sys.exit(
            "FIRMS returned an unexpected response (check your MAP_KEY / params):\n"
            + text[:300]
        )
    return list(csv.DictReader(io.StringIO(text)))


def normalize_source() -> str:
    s = SOURCE.upper()
    if "VIIRS" in s:
        return "firms_viirs"
    if "MODIS" in s:
        return "firms_modis"
    return "firms"


def to_params(row: dict, source_label: str) -> dict | None:
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
        ts = datetime.now(timezone.utc)
    geometry = {"type": "Point", "coordinates": [lon, lat]}
    return {
        "timestamp": ts,
        "source": source_label,
        "signal_type": "hotspot",
        "geometry": json.dumps(geometry),
        "payload": json.dumps(row),
    }


def insert_many(rows: list[dict]) -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL is not set. Add it to ~/.hermes/.env")
    sql = """
        INSERT INTO signals ("timestamp", source, signal_type, geometry, payload)
        VALUES (
            %(timestamp)s, %(source)s, %(signal_type)s,
            ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326)),
            %(payload)s::jsonb
        );
    """
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    return len(rows)


def main() -> None:
    source_label = normalize_source()
    raw = fetch_hotspots()
    params = [p for r in raw if (p := to_params(r, source_label)) is not None]
    if not params:
        print(
            f"No hotspots returned for area={AREA} source={SOURCE}. "
            "Try a larger box or FIRMS_AREA=world."
        )
        return
    if len(params) > MAX_ROWS:
        print(f"Capping {len(params)} hotspots to FIRMS_MAX_ROWS={MAX_ROWS}.")
        params = params[:MAX_ROWS]
    n = insert_many(params)
    print(f"Inserted {n} FIRMS hotspots (source={source_label}, area={AREA}).")


if __name__ == "__main__":
    main()

