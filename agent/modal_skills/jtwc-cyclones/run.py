#!/usr/bin/env python3
"""Envision ingestion: JTWC Western Pacific cyclones -> signals (ATCF a-deck)."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import psycopg
from psycopg import Connection

SKILL_ID = "jtwc-cyclones"
PRODUCTS_URL = "https://www.metoc.navy.mil/jtwc/products/"
HEADERS = {
    "User-Agent": os.environ.get(
        "JTWC_USER_AGENT",
        "Mozilla/5.0 (compatible; envision-monitor/0.1; +https://github.com/)",
    )
}
SKILL_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.environ.get("DATABASE_URL")


def parse_now(argv: list[str] | None = None) -> datetime:
    p = argparse.ArgumentParser(description="Ingest JTWC cyclone advisories")
    p.add_argument("--now", default=None, help="ISO8601 UTC run time (default: now)")
    p.add_argument("--fixture", default=None, help="Path to local .dat file (skip live fetch)")
    args = p.parse_args(argv)
    if args.now is None:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_atcf_latlon(lat_str: str, lon_str: str) -> tuple[float, float] | None:
    def one(val: str, pos: str, neg: str) -> float | None:
        val = val.strip().upper()
        if not val:
            return None
        hemi = val[-1]
        if hemi not in pos + neg:
            return None
        try:
            num = float(val[:-1]) / 10.0
        except ValueError:
            return None
        return -num if hemi in neg else num

    lat = one(lat_str, "N", "S")
    lon = one(lon_str, "E", "W")
    if lat is None or lon is None:
        return None
    return lon, lat


def parse_init_time(s: str) -> datetime | None:
    s = s.strip()
    if len(s) != 10 or not s.isdigit():
        return None
    try:
        return datetime.strptime(s, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_atcf_dat(text: str) -> list[dict]:
    """Parse ATCF a-deck lines into one dict per storm (grouped by basin+cy+init)."""
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 10:
            continue
        basin, cy, init_s = parts[0], parts[1], parts[2]
        if basin != "WP":
            continue
        try:
            tau = int(parts[5])
        except ValueError:
            continue
        pos = parse_atcf_latlon(parts[6], parts[7])
        if pos is None:
            continue
        lon, lat = pos
        vmax = int(parts[8]) if parts[8].strip().isdigit() else None
        mslp = int(parts[9]) if parts[9].strip().isdigit() else None
        storm_type = parts[10].strip() if len(parts) > 10 else ""
        name = ""
        for p in parts[10:]:
            token = p.strip()
            if len(token) >= 3 and token.isalpha() and token.upper() not in {
                "NEQ", "JTWC", "TD", "TS", "TY", "ST", "HU", "SD", "SS", "EX", "PT"
            }:
                name = token
                break
        if not name:
            name = f"WP{cy.zfill(2)}"
        key = (basin, cy, init_s)
        groups.setdefault(key, []).append({
            "tau": tau,
            "lon": lon,
            "lat": lat,
            "vmax_kt": vmax,
            "mslp_hpa": mslp,
            "classification": storm_type,
            "name": name,
            "init_time": init_s,
            "basin": basin,
            "cyclone_number": cy,
        })

    storms: list[dict] = []
    for key, rows in groups.items():
        rows.sort(key=lambda r: r["tau"])
        current = next((r for r in rows if r["tau"] == 0), rows[0])
        init_dt = parse_init_time(key[2])
        if init_dt is None:
            continue
        forecast_track = [
            {
                "tau_hours": r["tau"],
                "latitude": r["lat"],
                "longitude": r["lon"],
                "max_wind_kt": r["vmax_kt"],
                "mslp_hpa": r["mslp_hpa"],
            }
            for r in rows if r["tau"] > 0
        ]
        storms.append({
            "name": current["name"],
            "basin": current["basin"],
            "cyclone_number": current["cyclone_number"],
            "atcf_id": f"{current['basin']}{current['cyclone_number'].zfill(2)}",
            "timestamp": init_dt,
            "lon": current["lon"],
            "lat": current["lat"],
            "latitudeNumeric": current["lat"],
            "longitudeNumeric": current["lon"],
            "maximumWind": current["vmax_kt"],
            "minimumPressure": current["mslp_hpa"],
            "classification": current["classification"],
            "forecast_track": forecast_track,
            "source_agency": "jtwc",
        })
    return storms


def fetch_active_dat_urls() -> list[str]:
    try:
        resp = httpx.get(PRODUCTS_URL, timeout=30.0, headers=HEADERS, follow_redirects=True)
        print(f"[{SKILL_ID}] JTWC index HTTP {resp.status_code} from {PRODUCTS_URL}")
        resp.raise_for_status()
    except httpx.HTTPError as e:
        print(f"[{SKILL_ID}] WARNING: could not fetch JTWC index: {e}", file=sys.stderr)
        return []
    html = resp.text
    urls: list[str] = []
    for m in re.finditer(r'href=["\']([^"\']+\.dat)["\']', html, re.I):
        href = m.group(1)
        if "wp" in href.lower() or "/wp" in href.lower():
            if href.startswith("http"):
                urls.append(href)
            else:
                base = PRODUCTS_URL.rstrip("/") + "/"
                urls.append(base + href.lstrip("/"))
    if not urls:
        for m in re.finditer(r'href=["\']([^"\']+\.dat)["\']', html, re.I):
            href = m.group(1)
            if href.startswith("http"):
                urls.append(href)
            else:
                urls.append(PRODUCTS_URL.rstrip("/") + "/" + href.lstrip("/"))
    return list(dict.fromkeys(urls))


def fetch_dat_text(url: str) -> str | None:
    try:
        resp = httpx.get(url, timeout=30.0, headers=HEADERS, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError as e:
        print(f"[{SKILL_ID}] WARNING: failed to fetch {url}: {e}", file=sys.stderr)
        return None


def to_signal(storm: dict, now: datetime) -> dict:
    lon, lat = storm["lon"], storm["lat"]
    geometry = {"type": "Point", "coordinates": [lon, lat]}
    ts = storm["timestamp"]
    payload = {**storm}
    if isinstance(ts, datetime):
        payload["timestamp"] = ts.isoformat().replace("+00:00", "Z")
    return {
        "timestamp": ts if isinstance(ts, datetime) else parse_init_time(str(ts)) or now,
        "source": "jtwc",
        "signal_type": "cyclone_advisory",
        "geometry": json.dumps(geometry),
        "payload": json.dumps(payload),
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


def collect_storms(fixture: str | None) -> list[dict]:
    if fixture:
        path = Path(fixture)
        if not path.is_absolute():
            path = SKILL_DIR / fixture
        text = path.read_text(encoding="utf-8")
        return parse_atcf_dat(text)

    storms: list[dict] = []
    urls = fetch_active_dat_urls()
    if not urls:
        print(f"[{SKILL_ID}] No active WP .dat URLs found on JTWC index (pre-season is normal).")
        return []
    for url in urls:
        text = fetch_dat_text(url)
        if text:
            storms.extend(parse_atcf_dat(text))
    return storms


def run(now: datetime, db: Connection, fixture: str | None = None) -> int:
    storms = collect_storms(fixture)
    if not storms:
        print(f"[{SKILL_ID}] No storms to insert.")
        return 0
    params = [to_signal(s, now) for s in storms]
    n = insert_many(db, params)
    names = ", ".join(s["name"] for s in storms)
    print(f"[{SKILL_ID}] Inserted {n} JTWC cyclone signal(s): {names}.")
    return n


def main() -> int:
    p = argparse.ArgumentParser(description="Ingest JTWC cyclone advisories")
    p.add_argument("--now", default=None, help="ISO8601 UTC run time (default: now)")
    p.add_argument("--fixture", default=None, help="Path to local .dat file")
    args = p.parse_args()
    now = parse_now()
    if args.now:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
    if args.fixture:
        storms = collect_storms(args.fixture)
        if not storms:
            print(f"[{SKILL_ID}] Fixture parsed 0 storms.", file=sys.stderr)
            return 1
        print(f"[{SKILL_ID}] Fixture parsed {len(storms)} storm(s): "
              f"{', '.join(s['name'] for s in storms)}.")
        if not DATABASE_URL:
            return 0
        with psycopg.connect(DATABASE_URL) as db:
            run(now, db, fixture=args.fixture)
        return 0
    if not DATABASE_URL:
        sys.exit("DATABASE_URL is not set. Add it to ~/.hermes/.env")
    with psycopg.connect(DATABASE_URL) as db:
        run(now, db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
