#!/usr/bin/env python3
"""Envision ingestion: NHC active tropical cyclones -> signals.

Reads the National Hurricane Center current-storms feed (Atlantic + East
Pacific) and writes one point Signal per active storm at its current center.
The full storm record (intensity, pressure, movement, forecast/cone URLs) is
kept in the payload for the Day-3 cyclone detection skills.

Off-season this feed is legitimately empty — zero inserts is normal.

Requires:
  - env DATABASE_URL
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import httpx
import psycopg

CURRENT_STORMS_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"
HEADERS = {"User-Agent": "envision-monitor/0.1"}


def parse_coord(value) -> float | None:
    """Parse strings like '20.5N' / '94.5W' (W and S are negative)."""
    v = str(value).strip().upper()
    if not v:
        return None
    hemi = ""
    if v[-1] in "NSEW":
        hemi, v = v[-1], v[:-1]
    try:
        num = float(v)
    except ValueError:
        return None
    return -num if hemi in ("S", "W") else num


def storm_point(storm: dict) -> tuple[float, float] | None:
    lat, lon = storm.get("latitudeNumeric"), storm.get("longitudeNumeric")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return float(lon), float(lat)
    lat, lon = parse_coord(storm.get("latitude", "")), parse_coord(storm.get("longitude", ""))
    if lat is None or lon is None:
        return None
    return lon, lat


def parse_ts(storm: dict) -> datetime:
    for key in ("lastUpdate", "lastUpdated"):
        val = storm.get(key)
        if val:
            try:
                return datetime.fromisoformat(
                    str(val).replace("Z", "+00:00")
                ).astimezone(timezone.utc)
            except ValueError:
                pass
    return datetime.now(timezone.utc)


def fetch_storms() -> list[dict]:
    r = httpx.get(CURRENT_STORMS_URL, timeout=30.0, headers=HEADERS)
    r.raise_for_status()
    return r.json().get("activeStorms") or []


def to_params(storm: dict) -> dict | None:
    pt = storm_point(storm)
    if pt is None:
        return None
    lon, lat = pt
    geometry = {"type": "Point", "coordinates": [lon, lat]}
    return {
        "timestamp": parse_ts(storm),
        "source": "nhc",
        "signal_type": "cyclone_advisory",
        "geometry": json.dumps(geometry),
        "payload": json.dumps(storm),
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
    storms = fetch_storms()
    if not storms:
        print("NHC lists 0 active storms right now (normal outside hurricane season).")
        return
    rows = [p for s in storms if (p := to_params(s)) is not None]
    n = insert_many(rows)
    names = ", ".join(s.get("name", "?") for s in storms)
    print(f"Inserted {n} NHC cyclone signals ({len(storms)} active: {names}).")


if __name__ == "__main__":
    main()
