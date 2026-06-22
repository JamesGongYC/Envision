#!/usr/bin/env python3
"""
typhoon_landfall_imminent — Envision detection skill (Day 3, v1).

For each active NHC cyclone, projects its current position forward over
the next 72h using the bulletin's heading + speed, buffers each forecast
point with a growing radius (50→200 km, roughly matching NHC's 5-year
average track error), unions the buffers into an approximated cone, and
checks whether the cone covers any populated place with pop >= 10_000.

If yes: one forecast row per storm, geometry = cone, reasoning lists
the top at-risk cities.

Prerequisites:
  - Migration 003 applied (populated_places table)
  - bootstrap_populated_places.py run at least once
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg import Connection
from shapely.geometry import Point, mapping
from shapely.ops import unary_union

for _lib in ("/root/agent_lib", Path(__file__).resolve().parents[2] / "lib"):
    _lp = str(_lib)
    if os.path.isdir(_lp) and _lp not in sys.path:
        sys.path.insert(0, _lp)
        break
from trace_builder import TraceBuilder  # noqa: E402
from reasoning_llm import generate_reasoning  # noqa: E402
from reasoning_prompts import prompt_typhoon_landfall  # noqa: E402
from forecast_model import Forecast  # noqa: E402

# --- config ---------------------------------------------------------------
SKILL_ID = "typhoon_landfall_imminent"
SKILL_VERSION = 1

LATEST_BULLETIN_WINDOW_HOURS = 6  # bulletin must be recent enough to be "active"
HORIZON_HOURS = 72
# (forecast hour, buffer radius km) — coarse NHC-like uncertainty growth
CONE_STEPS = [
    (0,   40),
    (6,   55),
    (12,  75),
    (24, 100),
    (36, 130),
    (48, 160),
    (60, 180),
    (72, 200),
]
MIN_POPULATION = 10_000
EARTH_R_KM = 6371.0088
KM_PER_DEG_LAT = 111.0

FORECAST_VALID_HOURS = 72  # plan §1: cyclones 6–72h short-range

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print(f"[{SKILL_ID}] DATABASE_URL not set", file=sys.stderr)
    sys.exit(2)


def parse_now(argv: list[str] | None = None) -> datetime:
    p = argparse.ArgumentParser(description="Detect imminent typhoon landfall")
    p.add_argument("--now", default=None, help="ISO8601 UTC cutoff (default: now)")
    args = p.parse_args(argv)
    if args.now is None:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --- payload helpers (mirror typhoon_intensifying for consistency) ------
def storm_key(payload):
    if not isinstance(payload, dict):
        return None
    for k in ("id", "stormId", "binNumber", "atcfId", "name"):
        v = payload.get(k)
        if v:
            return str(v)
    return None


def storm_position(payload):
    if not isinstance(payload, dict):
        return None
    lat = payload.get("latitudeNumeric")
    lon = payload.get("longitudeNumeric")
    if lat is None or lon is None:
        lat_s = str(payload.get("latitude", ""))
        lon_s = str(payload.get("longitude", ""))
        try:
            lat = float(lat_s.rstrip("NSns")) * (-1 if lat_s.endswith(("S", "s")) else 1)
            lon = float(lon_s.rstrip("EWew")) * (-1 if lon_s.endswith(("W", "w")) else 1)
        except (ValueError, AttributeError):
            return None
    try:
        return (float(lon), float(lat))
    except (TypeError, ValueError):
        return None


def storm_display_name(payload):
    if not isinstance(payload, dict):
        return "Unnamed storm"
    return str(payload.get("name") or payload.get("stormName")
               or payload.get("id") or "Unnamed storm")


def storm_classification(payload):
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("classification")
               or payload.get("intensityClassification") or "")


COMPASS_TO_DEG = {
    "N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5,
    "E": 90, "ESE": 112.5, "SE": 135, "SSE": 157.5,
    "S": 180, "SSW": 202.5, "SW": 225, "WSW": 247.5,
    "W": 270, "WNW": 292.5, "NW": 315, "NNW": 337.5,
}


def storm_heading_deg(payload):
    """Compass heading in degrees true (0=N, 90=E)."""
    if not isinstance(payload, dict):
        return None
    for k in ("movementDir", "movementDirection", "heading", "bearing"):
        v = payload.get(k)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            return float(v)
        v_s = str(v).strip().upper()
        if v_s in COMPASS_TO_DEG:
            return COMPASS_TO_DEG[v_s]
        try:
            return float(v_s)
        except ValueError:
            continue
    return None


def storm_speed_kmh(payload):
    """Translation speed in km/h. NHC commonly reports mph; we convert."""
    if not isinstance(payload, dict):
        return None
    for k, unit in (("movementSpeed", "mph"),
                    ("speed", "mph"),
                    ("translationSpeed", "mph")):
        v = payload.get(k)
        if v is None or v == "":
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if unit == "mph":
            return f * 1.609344
        if unit == "kt":
            return f * 1.852
        return f
    return None


# --- geometry helpers ----------------------------------------------------
def project_forward(lon, lat, bearing_deg, distance_km):
    """Great-circle forward projection. Returns (new_lon, new_lat)."""
    bearing = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    dr = distance_km / EARTH_R_KM
    lat2 = math.asin(
        math.sin(lat1) * math.cos(dr)
        + math.cos(lat1) * math.sin(dr) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(dr) * math.cos(lat1),
        math.cos(dr) - math.sin(lat1) * math.sin(lat2),
    )
    return (math.degrees(lon2), math.degrees(lat2))


def build_cone(lon0, lat0, bearing_deg, speed_kmh):
    """Union of buffered forecast points → approximated cone polygon."""
    parts = []
    for t_hours, radius_km in CONE_STEPS:
        plon, plat = project_forward(
            lon0, lat0, bearing_deg, speed_kmh * t_hours
        )
        # Approximate radius in degrees. Use latitude correction for the
        # longitude component to avoid east–west squish at high latitudes.
        deg_lat = radius_km / KM_PER_DEG_LAT
        cos_lat = max(0.1, math.cos(math.radians(plat)))
        deg_lon = deg_lat / cos_lat
        # Build an axis-aligned ellipse via affine scaling of a unit circle
        circle = Point(plon, plat).buffer(deg_lat, resolution=24)
        # Stretch longitude
        from shapely.affinity import scale, translate
        circle = translate(
            scale(translate(circle, xoff=-plon, yoff=-plat),
                  xfact=deg_lon / deg_lat, yfact=1.0),
            xoff=plon, yoff=plat,
        )
        parts.append(circle)
    return unary_union(parts)


# --- data access ---------------------------------------------------------
def load_active_storms(conn: Connection, now: datetime):
    """Latest NHC advisory per storm, within the last
    LATEST_BULLETIN_WINDOW_HOURS hours."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH ranked AS (
              SELECT
                id, timestamp, payload,
                ROW_NUMBER() OVER (
                  PARTITION BY COALESCE(
                    payload->>'id',
                    payload->>'stormId',
                    payload->>'binNumber',
                    payload->>'atcfId',
                    payload->>'name'
                  )
                  ORDER BY timestamp DESC
                ) AS rn
              FROM signals
              WHERE source = 'nhc'
                AND signal_type = 'cyclone_advisory'
                AND timestamp > %s - interval '{LATEST_BULLETIN_WINDOW_HOURS} hours'
                AND timestamp <= %s
            )
            SELECT id, timestamp, payload
            FROM ranked
            WHERE rn = 1
            """,
            (now, now),
        )
        return cur.fetchall()


def count_populated_places_catalog(conn: Connection) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*)::int FROM populated_places WHERE population >= %s",
            (MIN_POPULATION,),
        )
        return cur.fetchone()[0]


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_R_KM * math.asin(min(1.0, math.sqrt(a)))


def cities_in_cone(conn, cone_geojson):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT geonameid, name, country_code, population,
                   ST_X(geometry) AS lon, ST_Y(geometry) AS lat
            FROM populated_places
            WHERE population >= %s
              AND ST_Intersects(
                geometry,
                ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)
              )
            ORDER BY population DESC
            """,
            (MIN_POPULATION, json.dumps(cone_geojson)),
        )
        return cur.fetchall()


# --- scoring & reasoning -------------------------------------------------
def probability_components(cities: list, total_pop: int) -> dict:
    base = 0.45
    n_bonus = min(0.20, 0.02 * len(cities))
    pop_bonus = min(0.20, 0.05 * math.log10(max(1, total_pop / 100_000)))
    return {
        "base": base,
        "population_at_risk": round(n_bonus + max(0.0, pop_bonus), 4),
        "time_to_landfall_h": float(HORIZON_HOURS),
    }


def score_probability(cities):
    if not cities:
        return None
    total_pop = sum(c[3] for c in cities)
    parts = probability_components(cities, total_pop)
    return round(
        min(0.85, parts["base"] + parts["population_at_risk"]),
        3,
    )


def build_reasoning(name, classification, n_cities, top_cities,
                    total_pop, speed_kmh, bearing):
    cls = f" ({classification})" if classification else ""
    top_str = ", ".join(
        f"{c[1]}{f' ({c[2]})' if c[2] else ''}" for c in top_cities[:5]
    )
    return (
        f"Storm {name}{cls}: 72h projected track (heading "
        f"{bearing:.0f}°, {speed_kmh:.0f} km/h) intersects {n_cities} "
        f"populated area(s) with ~{total_pop:,} total population. "
        f"Top affected: {top_str}."
    )


# --- run -----------------------------------------------------------------
def run(now: datetime, db: Connection) -> list[Forecast]:
    valid_until = now + timedelta(hours=FORECAST_VALID_HOURS)

    storms = load_active_storms(db, now)
    if not storms:
        print(f"[{SKILL_ID}] no active NHC advisories in last "
              f"{LATEST_BULLETIN_WINDOW_HOURS}h.")
        return []

    print(f"[{SKILL_ID}] {len(storms)} active storm(s).")
    places_queried = count_populated_places_catalog(db)

    out: list[Forecast] = []
    for sig_id, _ts, payload in storms:
        name = storm_display_name(payload)
        cls = storm_classification(payload)
        pos = storm_position(payload)
        bearing = storm_heading_deg(payload)
        speed = storm_speed_kmh(payload)

        if pos is None or bearing is None or speed is None:
            print(f"[{SKILL_ID}]   {name}: missing position/heading/speed "
                  f"(pos={pos}, bearing={bearing}, speed={speed}); skip.")
            continue

        lon0, lat0 = pos
        cone = build_cone(lon0, lat0, bearing, speed)
        cone_geojson = mapping(cone)

        cities = cities_in_cone(db, cone_geojson)
        if not cities:
            print(f"[{SKILL_ID}]   {name}: cone covers no populated "
                  f"places with pop >= {MIN_POPULATION}.")
            continue

        total_pop = sum(c[3] for c in cities)
        prob = score_probability(cities)
        fallback = build_reasoning(
            name, cls, len(cities), cities, total_pop, speed, bearing
        )
        top_names = [c[1] for c in cities[:3]]

        minx, miny, maxx, maxy = cone.bounds
        area_km2 = cone.area * (KM_PER_DEG_LAT ** 2)
        places_in_cone = []
        for geonameid, _name, _cc, pop, plon, plat in cities[:5]:
            places_in_cone.append({
                "place_id": int(geonameid),
                "population": int(pop),
                "distance_km": round(
                    haversine_km(lon0, lat0, float(plon), float(plat)), 1
                ),
            })

        tb = TraceBuilder(now, SKILL_ID)
        tb.set_inputs(
            active_storms=len(storms),
            populated_places_queried_count=places_queried,
        )
        tb.set_intermediate(
            cone_polygon_summary={
                "bbox": [float(minx), float(miny), float(maxx), float(maxy)],
                "area_km2": round(area_km2, 1),
            },
            intersected_population_total=int(total_pop),
            populated_places_in_cone=places_in_cone,
        )
        tb.add_geometry_step(
            "cone_construction",
            heading_deg=round(float(bearing), 1),
            speed_kmh=round(float(speed), 1),
            buffer_km_at_horizons=[[int(h), int(r)] for h, r in CONE_STEPS],
        )
        tb.set_probability_components(
            **probability_components(cities, total_pop)
        )

        trace_dict = tb.build()
        prompt = prompt_typhoon_landfall(
            trace_dict,
            name,
            "nhc",
            int(total_pop),
            top_names,
            float(HORIZON_HOURS),
        )
        reasoning = generate_reasoning(prompt, fallback, db=db)

        out.append(
            Forecast(
                id=str(uuid.uuid4()),
                issued_at=now,
                valid_from=now,
                valid_until=valid_until,
                disaster_class="typhoon",
                geometry=json.dumps(cone_geojson),
                probability=prob,
                skill_id=SKILL_ID,
                skill_version=SKILL_VERSION,
                contributing_signal_ids=[str(sig_id)],
                reasoning=reasoning,
                is_baseline=False,
                trace=trace_dict,
            )
        )
        print(f"[{SKILL_ID}]   {name}: cone covers {len(cities)} cities, "
              f"~{total_pop:,} pop, p={prob}")

    print(f"[{SKILL_ID}] emitted {len(out)} forecast(s).")
    return out
