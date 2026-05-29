#!/usr/bin/env python3
"""Envision ingestion: NWS active fire-weather alerts -> signals.

Pulls active alerts from the National Weather Service API, keeps the
fire-weather events, resolves geometry, and writes each as a Signal.

Two NWS specifics handled here:
  - The API requires a User-Agent header identifying the app + a contact.
  - Alerts frequently have geometry == null and instead list `affectedZones`
    (URLs to forecast/county zone polygons). We resolve those, emitting one
    signal per affected zone when the alert has no direct geometry.

Requires:
  - env DATABASE_URL
Optional env:
  - NWS_EVENTS      (comma list; default fire-weather set)
  - NWS_USER_AGENT  (default placeholder; set a real app + contact email)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import httpx
import psycopg

ALERTS_URL = "https://api.weather.gov/alerts/active"
DEFAULT_EVENTS = "Fire Weather Watch,Red Flag Warning,Fire Warning"
EVENTS = {
    e.strip().lower()
    for e in os.environ.get("NWS_EVENTS", DEFAULT_EVENTS).split(",")
    if e.strip()
}
USER_AGENT = os.environ.get(
    "NWS_USER_AGENT", "envision-monitor/0.1 (set NWS_USER_AGENT with a contact)"
)
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/geo+json"}


def get_json(client: httpx.Client, url: str) -> dict | None:
    try:
        r = client.get(url, headers=HEADERS, timeout=30.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError:
        return None


def parse_ts(props: dict) -> datetime:
    for key in ("onset", "effective", "sent"):
        val = props.get(key)
        if val:
            try:
                return datetime.fromisoformat(val).astimezone(timezone.utc)
            except ValueError:
                pass
    return datetime.now(timezone.utc)


def zone_geometry(client: httpx.Client, url: str, cache: dict) -> dict | None:
    if url in cache:
        return cache[url]
    data = get_json(client, url)
    geom = (data or {}).get("geometry")
    cache[url] = geom
    return geom


def collect_signals(client: httpx.Client) -> list[dict]:
    fc = get_json(client, ALERTS_URL)
    if not fc or "features" not in fc:
        sys.exit("Could not fetch NWS active alerts (check NWS_USER_AGENT).")
    out: list[dict] = []
    zone_cache: dict = {}
    for feat in fc["features"]:
        props = feat.get("properties", {})
        event = (props.get("event") or "").strip()
        if event.lower() not in EVENTS:
            continue
        base = {
            "timestamp": parse_ts(props),
            "source": "nws_alerts",
            "signal_type": "fire_warning",
        }
        geom = feat.get("geometry")
        if geom:
            out.append({**base, "geometry": json.dumps(geom), "payload": json.dumps(props)})
            continue
        # No direct geometry: emit one signal per resolved affected zone.
        for zurl in props.get("affectedZones") or []:
            zgeom = zone_geometry(client, zurl, zone_cache)
            if not zgeom:
                continue
            payload = {**props, "_zone": zurl}
            out.append({**base, "geometry": json.dumps(zgeom), "payload": json.dumps(payload)})
    return out


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
    with httpx.Client() as client:
        rows = collect_signals(client)
    if not rows:
        print(
            f"No active alerts matched events {sorted(EVENTS)}. "
            "(Fire-weather alerts are seasonal/regional — an empty result can be normal.)"
        )
        return
    n = insert_many(rows)
    print(f"Inserted {n} NWS fire-weather signals.")


if __name__ == "__main__":
    main()
