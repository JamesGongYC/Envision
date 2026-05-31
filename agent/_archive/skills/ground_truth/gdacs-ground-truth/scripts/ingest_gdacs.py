#!/usr/bin/env python3
"""Envision ground truth: GDACS disaster alerts -> ground_truth.

Polls the GDACS GeoRSS feed and records confirmed disaster events that the
evaluator (Day 4) scores forecasts against. By default keeps tropical-cyclone
(TC) and wildfire (WF) events, matching Envision's forecast classes.

Requires:
  - env DATABASE_URL
Optional env:
  - GDACS_EVENT_TYPES  (comma list of short codes; default 'TC,WF')
  - GDACS_FEED_URL     (default https://www.gdacs.org/xml/rss.xml)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
import psycopg
from psycopg import Connection

FEED_URL = os.environ.get("GDACS_FEED_URL", "https://www.gdacs.org/xml/rss.xml")
TYPES = {
    t.strip().upper()
    for t in os.environ.get("GDACS_EVENT_TYPES", "TC,WF").split(",")
    if t.strip()
}
CLASS_MAP = {
    "TC": "typhoon", "WF": "wildfire", "EQ": "earthquake",
    "FL": "flood", "DR": "drought", "VO": "volcano", "TS": "tsunami",
}
NS = {
    "gdacs": "http://www.gdacs.org",
    "geo": "http://www.w3.org/2003/01/geo/wgs84_pos#",
    "georss": "http://www.georss.org/georss",
}

DATABASE_URL = os.environ.get("DATABASE_URL")


def parse_now(argv: list[str] | None = None) -> datetime:
    p = argparse.ArgumentParser(description="Ingest GDACS ground truth events")
    p.add_argument("--now", default=None, help="ISO8601 UTC run time (default: now)")
    args = p.parse_args(argv)
    if args.now is None:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def text(item, path: str) -> str | None:
    el = item.find(path, NS)
    return el.text.strip() if el is not None and el.text else None


def parse_when(*candidates: str | None, now: datetime) -> datetime:
    for val in candidates:
        if not val:
            continue
        try:
            return parsedate_to_datetime(val).astimezone(timezone.utc)
        except (TypeError, ValueError, IndexError):
            pass
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            pass
    return now


def point(item) -> tuple[float, float] | None:
    lat, lon = text(item, ".//geo:lat"), text(item, ".//geo:long")
    if lat and lon:
        try:
            return float(lon), float(lat)
        except ValueError:
            pass
    pt = text(item, ".//georss:point")  # "lat lon"
    if pt:
        try:
            a, b = pt.split()
            return float(b), float(a)
        except ValueError:
            pass
    return None


def fetch_items() -> list:
    r = httpx.get(FEED_URL, timeout=30.0, headers={"User-Agent": "envision-monitor/0.1"})
    r.raise_for_status()
    return list(ET.fromstring(r.content).iter("item"))


def to_params(item, now: datetime) -> dict | None:
    etype = (text(item, "gdacs:eventtype") or "").upper()
    if etype not in TYPES:
        return None
    pt = point(item)
    if pt is None:
        return None
    lon, lat = pt
    payload = {
        "eventtype": etype,
        "eventid": text(item, "gdacs:eventid"),
        "eventname": text(item, "gdacs:eventname"),
        "alertlevel": text(item, "gdacs:alertlevel"),
        "alertscore": text(item, "gdacs:alertscore"),
        "country": text(item, "gdacs:country"),
        "fromdate": text(item, "gdacs:fromdate"),
        "todate": text(item, "gdacs:todate"),
        "title": text(item, "title"),
        "link": text(item, "link"),
    }
    geometry = {"type": "Point", "coordinates": [lon, lat]}
    return {
        "occurred_at": parse_when(payload["fromdate"], text(item, "pubDate"), now=now),
        "source": "gdacs",
        "disaster_class": CLASS_MAP.get(etype, etype.lower()),
        "geometry": json.dumps(geometry),
        "severity": payload["alertlevel"],
        "payload": json.dumps(payload),
    }


def insert_many(db: Connection, rows: list[dict]) -> int:
    sql = """
        INSERT INTO ground_truth (occurred_at, source, disaster_class, geometry, severity, payload)
        VALUES (
            %(occurred_at)s, %(source)s, %(disaster_class)s,
            ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326)),
            %(severity)s, %(payload)s::jsonb
        );
    """
    with db.cursor() as cur:
        cur.executemany(sql, rows)
    db.commit()
    return len(rows)


def run(now: datetime, db: Connection) -> int:
    items = fetch_items()
    rows = [p for it in items if (p := to_params(it, now)) is not None]
    if not rows:
        print(f"No GDACS events matched types {sorted(TYPES)} (feed had {len(items)} items).")
        return 0
    n = insert_many(db, rows)
    print(f"Inserted {n} GDACS ground-truth events (from {len(items)} feed items).")
    return n


def main() -> int:
    if not DATABASE_URL:
        sys.exit("DATABASE_URL is not set. Add it to ~/.hermes/.env")
    now = parse_now()
    with psycopg.connect(DATABASE_URL) as db:
        run(now, db)
    return 0


if __name__ == "__main__":
    main()
