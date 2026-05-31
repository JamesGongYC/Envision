#!/usr/bin/env python3
"""
bootstrap_populated_places — one-time loader for the typhoon-landfall
detector. Downloads GeoNames cities5000.zip, filters to pop >= 10_000,
and inserts into the populated_places table.

Idempotent: re-runs are safe (uses ON CONFLICT DO NOTHING).

Run once before the first run of detect_typhoon_landfall.py.
"""
from __future__ import annotations

import io
import os
import sys
import urllib.request
import zipfile

import psycopg

GEONAMES_URL = "http://download.geonames.org/export/dump/cities5000.zip"
MIN_POPULATION = 10_000  # plan §7 threshold

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("DATABASE_URL not set", file=sys.stderr)
    sys.exit(2)


def download_and_extract() -> str:
    """Return the contents of cities5000.txt as a UTF-8 string."""
    print(f"Downloading {GEONAMES_URL} ...")
    with urllib.request.urlopen(GEONAMES_URL, timeout=60) as resp:
        zip_bytes = resp.read()
    print(f"  got {len(zip_bytes):,} bytes")

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        with zf.open("cities5000.txt") as f:
            return f.read().decode("utf-8")


def parse_rows(text: str):
    """Yield (geonameid, name, country_code, population, lat, lon) tuples
    for cities meeting MIN_POPULATION. GeoNames TSV column order:
      0  geonameid
      1  name
      2  asciiname
      3  alternatenames
      4  latitude
      5  longitude
      6  feature_class
      7  feature_code
      8  country_code
      ...
      14 population
    """
    kept = 0
    seen = 0
    for line in text.splitlines():
        if not line:
            continue
        seen += 1
        parts = line.split("\t")
        if len(parts) < 15:
            continue
        try:
            geonameid = int(parts[0])
            name = parts[1]
            lat = float(parts[4])
            lon = float(parts[5])
            country_code = parts[8] or None
            population = int(parts[14]) if parts[14] else 0
        except (ValueError, IndexError):
            continue
        if population < MIN_POPULATION:
            continue
        kept += 1
        yield (geonameid, name, country_code, population, lat, lon)
    print(f"  parsed {seen:,} rows; kept {kept:,} with pop >= {MIN_POPULATION:,}.")


def insert_batch(conn, batch):
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO populated_places
              (geonameid, name, country_code, population, geometry)
            VALUES
              (%s, %s, %s, %s,
               ST_SetSRID(ST_MakePoint(%s, %s), 4326))
            ON CONFLICT (geonameid) DO UPDATE
              SET population = EXCLUDED.population,
                  geometry   = EXCLUDED.geometry,
                  name       = EXCLUDED.name
            """,
            batch,
        )


def main() -> int:
    text = download_and_extract()

    rows = []
    for geonameid, name, cc, pop, lat, lon in parse_rows(text):
        # NOTE: ST_MakePoint takes (lon, lat) order
        rows.append((geonameid, name, cc, pop, lon, lat))

    if not rows:
        print("No qualifying rows; aborting.", file=sys.stderr)
        return 1

    print(f"Inserting {len(rows):,} populated places into DB ...")
    with psycopg.connect(DATABASE_URL, autocommit=False) as conn:
        # Insert in chunks of 5_000 to keep memory bounded
        chunk = 5_000
        for i in range(0, len(rows), chunk):
            insert_batch(conn, rows[i:i + chunk])
            print(f"  inserted {min(i + chunk, len(rows)):,}/{len(rows):,}")
        conn.commit()
    print("Done.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
