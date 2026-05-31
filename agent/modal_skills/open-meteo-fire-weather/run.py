#!/usr/bin/env python3
"""Envision ingestion: Open-Meteo fire weather index -> signals."""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx
import psycopg
from psycopg import Connection

SKILL_ID = "open-meteo-fire-weather"
FORECAST_API = "https://api.open-meteo.com/v1/forecast"
SCORE_THRESHOLD = 3
FORECAST_DAYS = 3

REGIONS_FILE = Path(__file__).resolve().parent / "fire_regions.json"
DATABASE_URL = os.environ.get("DATABASE_URL")


def parse_now(argv: list[str] | None = None) -> datetime:
    p = argparse.ArgumentParser(description="Ingest Open-Meteo fire weather signals")
    p.add_argument("--now", default=None, help="ISO8601 UTC run time (default: now)")
    args = p.parse_args(argv)
    if args.now is None:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load_regions() -> list[dict]:
    with open(REGIONS_FILE, encoding="utf-8") as f:
        return json.load(f)


def daily_rh_min(hourly_times: list[str], rh_values: list) -> dict[str, float]:
    """Map UTC date (YYYY-MM-DD) -> minimum RH that day."""
    by_day: dict[str, list[float]] = defaultdict(list)
    for t, rh in zip(hourly_times, rh_values):
        if rh is None:
            continue
        day = t[:10]
        by_day[day].append(float(rh))
    return {day: min(vals) for day, vals in by_day.items()}


def fire_score(temp_max: float, rh_min: float, wind_max: float, precip_sum: float) -> int:
    return (
        int(temp_max > 30)
        + int(rh_min < 30)
        + int(wind_max > 25)
        + int(precip_sum < 1)
    )


def fetch_forecast(lat: float, lon: float) -> dict | None:
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,precipitation_sum,wind_speed_10m_max",
        "hourly": "relative_humidity_2m",
        "forecast_days": FORECAST_DAYS,
        "timezone": "UTC",
    }
    try:
        resp = httpx.get(FORECAST_API, params=params, timeout=30.0)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        print(f"[{SKILL_ID}] WARNING: forecast failed for ({lat}, {lon}): {e}", file=sys.stderr)
        return None


def signals_for_region(region: dict, fc: dict, now: datetime) -> list[dict]:
    daily = fc.get("daily") or {}
    hourly = fc.get("hourly") or {}
    dates = daily.get("time") or []
    temps = daily.get("temperature_2m_max") or []
    precips = daily.get("precipitation_sum") or []
    winds = daily.get("wind_speed_10m_max") or []
    rh_by_day = daily_rh_min(
        hourly.get("time") or [],
        hourly.get("relative_humidity_2m") or [],
    )

    out: list[dict] = []
    name = region["name"]
    lat, lon = region["lat"], region["lon"]

    for i, date_str in enumerate(dates):
        if i >= len(temps) or temps[i] is None:
            continue
        temp_max = float(temps[i])
        precip_sum = float(precips[i] if i < len(precips) and precips[i] is not None else 0)
        wind_max = float(winds[i] if i < len(winds) and winds[i] is not None else 0)
        rh_min = rh_by_day.get(date_str, 100.0)
        score = fire_score(temp_max, rh_min, wind_max, precip_sum)
        if score < SCORE_THRESHOLD:
            continue

        ts = datetime.fromisoformat(f"{date_str}T00:00:00+00:00")
        payload = {
            "region": name,
            "lat": lat,
            "lon": lon,
            "valid_date": date_str,
            "temp_max_c": temp_max,
            "rh_min_pct": rh_min,
            "wind_max_kmh": wind_max,
            "precip_sum_mm": precip_sum,
            "score": score,
            "threshold": SCORE_THRESHOLD,
        }
        out.append({
            "timestamp": ts,
            "source": "open_meteo",
            "signal_type": "fire_weather",
            "geometry": json.dumps({"type": "Point", "coordinates": [lon, lat]}),
            "payload": json.dumps(payload),
            "ingested_at": now,
        })
    return out


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


def insert_batch(rows: list[dict], db: Connection | None = None) -> int:
    """Insert rows, reconnecting if the idle Neon connection dropped during fetch."""
    if not rows:
        return 0
    if db is not None:
        try:
            with db.cursor() as cur:
                cur.execute("SELECT 1")
            return insert_many(db, rows)
        except psycopg.OperationalError:
            pass
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    with psycopg.connect(DATABASE_URL) as fresh:
        return insert_many(fresh, rows)


def run(now: datetime, db: Connection) -> int:
    regions = load_regions()
    total = 0
    for region in regions:
        fc = fetch_forecast(region["lat"], region["lon"])
        if fc is None:
            continue
        batch = signals_for_region(region, fc, now)
        if batch:
            print(f"[{SKILL_ID}] {region['name']}: {len(batch)} alert day(s).")
            total += insert_batch(batch, db)
    print(f"[{SKILL_ID}] Inserted {total} fire_weather signals from {len(regions)} regions.")
    return total


def main() -> int:
    if not DATABASE_URL:
        sys.exit("DATABASE_URL is not set. Add it to ~/.hermes/.env")
    now = parse_now()
    with psycopg.connect(DATABASE_URL) as db:
        run(now, db)
    return 0


if __name__ == "__main__":
    main()
