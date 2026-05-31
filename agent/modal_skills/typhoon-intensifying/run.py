#!/usr/bin/env python3
"""
typhoon_intensifying — Envision detection skill (Day 3, v1).

Reads NHC cyclone advisories from `signals` for the last ~24h, groups
them by storm id, and looks for a >5 hPa central-pressure drop over a
~12h window. Each qualifying storm produces one forecast row whose
geometry is a buffered circle around the storm's most recent position.

Detection rule (plan §7):
    p_then - p_now > 5 hPa   AND   |t_now - t_then - 12h| <= 2h tolerance

Notes:
  - Off-season the NHC feed is empty; this skill will correctly do
    nothing until storms appear (no Atlantic activity until ~June).
  - Field-name lookups are defensive because we have no NHC sample row
    in the dev DB yet. Tighten once a real bulletin lands.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg import Connection
from shapely.geometry import Point, mapping

for _lib in ("/root/agent_lib", Path(__file__).resolve().parents[2] / "lib"):
    _lp = str(_lib)
    if os.path.isdir(_lp) and _lp not in sys.path:
        sys.path.insert(0, _lp)
        break
from trace_builder import TraceBuilder  # noqa: E402
from reasoning_llm import generate_reasoning  # noqa: E402
from reasoning_prompts import prompt_typhoon_intensifying  # noqa: E402

# --- config ---------------------------------------------------------------
SKILL_ID = "typhoon_intensifying"
SKILL_VERSION = 1

LOOKBACK_HOURS = 24
WINDOW_HOURS = 12           # compare current vs ~12h earlier bulletin
WINDOW_TOLERANCE_HOURS = 2  # earlier bulletin must fall in [10h, 14h] ago
PRESSURE_DROP_THRESHOLD = 5.0  # hPa
BUFFER_DEG = 1.8            # ~200 km at equator; coarse but OK for v1
FORECAST_VALID_HOURS = 48   # within plan's 6–72h short-range envelope

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print(f"[{SKILL_ID}] DATABASE_URL not set", file=sys.stderr)
    sys.exit(2)


def parse_now(argv: list[str] | None = None) -> datetime:
    p = argparse.ArgumentParser(description="Detect typhoon intensification")
    p.add_argument("--now", default=None, help="ISO8601 UTC cutoff (default: now)")
    args = p.parse_args(argv)
    if args.now is None:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --- payload helpers (defensive) -----------------------------------------
def storm_key(payload: dict) -> str | None:
    """A stable identifier across bulletins for the same storm."""
    if not isinstance(payload, dict):
        return None
    for k in ("id", "stormId", "binNumber", "atcfId", "name"):
        v = payload.get(k)
        if v:
            return str(v)
    return None


def storm_pressure(payload: dict) -> float | None:
    """Central pressure in hPa, if present and parseable."""
    if not isinstance(payload, dict):
        return None
    for k in ("pressure", "minimumPressure", "minPressure", "centralPressure"):
        v = payload.get(k)
        if v in (None, "", 0, "0"):
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if 800.0 < f < 1100.0:  # plausible cyclone pressure range
            return f
    return None


def storm_position(payload: dict) -> tuple[float, float] | None:
    """Return (lon, lat) if extractable from the bulletin."""
    if not isinstance(payload, dict):
        return None
    lat = payload.get("latitudeNumeric")
    lon = payload.get("longitudeNumeric")
    if lat is None or lon is None:
        # try string forms like "19.6N", "78.2W"
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


def storm_display_name(payload: dict) -> str:
    if not isinstance(payload, dict):
        return "Unnamed storm"
    return str(
        payload.get("name")
        or payload.get("stormName")
        or payload.get("id")
        or "Unnamed storm"
    )


def storm_classification(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(
        payload.get("classification")
        or payload.get("intensityClassification")
        or ""
    )


# --- data access ---------------------------------------------------------
def load_recent_advisories(conn: Connection, now: datetime) -> list[tuple]:
    """[(signal_id, timestamp, payload), ...] for NHC advisories in last 24h."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, timestamp, payload
            FROM signals
            WHERE source = 'nhc'
              AND signal_type = 'cyclone_advisory'
              AND timestamp > %s - interval '{LOOKBACK_HOURS} hours'
              AND timestamp <= %s
            ORDER BY timestamp ASC
            """,
            (now, now),
        )
        return cur.fetchall()


# --- detection logic -----------------------------------------------------
def group_by_storm(rows: list[tuple]) -> dict[str, list]:
    """Returns {storm_key: [(signal_id, timestamp, pressure, payload), ...]}."""
    storms: dict[str, list] = {}
    for sig_id, ts, payload in rows:
        key = storm_key(payload)
        if not key:
            continue
        pressure = storm_pressure(payload)
        if pressure is None:
            continue
        storms.setdefault(key, []).append((sig_id, ts, pressure, payload))
    for k in storms:
        storms[k].sort(key=lambda b: b[1])
    return storms


def find_intensification(bulletins: list[tuple], now: datetime):
    """Return (earlier_bulletin, latest_bulletin, delta_hpa, elapsed_hours)
    if a >5 hPa drop over ~12h is detected; else None."""
    if len(bulletins) < 2:
        return None

    latest = bulletins[-1]
    _sig_id_now, t_now, p_now, _payload_now = latest

    target_t = now - timedelta(hours=WINDOW_HOURS)
    tolerance = timedelta(hours=WINDOW_TOLERANCE_HOURS)

    candidates = [
        b for b in bulletins[:-1]
        if abs(b[1] - target_t) <= tolerance
    ]
    if not candidates:
        return None

    earlier = min(candidates, key=lambda b: abs(b[1] - target_t))
    _sig_id_then, t_then, p_then, _payload_then = earlier

    delta = p_then - p_now  # positive = pressure dropped = intensifying
    if delta <= PRESSURE_DROP_THRESHOLD:
        return None

    elapsed_h = (t_now - t_then).total_seconds() / 3600.0
    return (earlier, latest, delta, elapsed_h)


# --- scoring & reasoning -------------------------------------------------
def probability_components(delta_hpa: float, elapsed_h: float) -> dict:
    base = 0.50
    pressure_drop_magnitude = 0.04 * max(0.0, delta_hpa - 5.0)
    recency_factor = max(0.0, 1.0 - abs(elapsed_h - WINDOW_HOURS) / WINDOW_TOLERANCE_HOURS)
    return {
        "base": base,
        "pressure_drop_magnitude": round(pressure_drop_magnitude, 4),
        "recency_factor": round(recency_factor, 4),
    }


def score_probability(delta_hpa: float, elapsed_h: float) -> float:
    """5 hPa → 0.50; +0.04 per additional hPa; DB caps at 0.85."""
    parts = probability_components(delta_hpa, elapsed_h)
    return round(
        min(0.85, parts["base"] + parts["pressure_drop_magnitude"]),
        3,
    )


def build_reasoning(name: str, classification: str,
                    p_then: float, p_now: float,
                    delta: float, elapsed_h: float) -> str:
    cls = f" ({classification})" if classification else ""
    return (
        f"Storm {name}{cls}: central pressure dropped from {p_then:.0f} hPa "
        f"to {p_now:.0f} hPa over {elapsed_h:.1f}h "
        f"({delta:.1f} hPa drop; threshold >5 hPa over 12h)."
    )


# --- write ---------------------------------------------------------------
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


# --- run -----------------------------------------------------------------
def run(now: datetime, db: Connection) -> int:
    valid_until = now + timedelta(hours=FORECAST_VALID_HOURS)

    rows = load_recent_advisories(db, now)
    if not rows:
        print(f"[{SKILL_ID}] no NHC advisories in last "
              f"{LOOKBACK_HOURS}h (likely off-season).")
        return 0

    storms = group_by_storm(rows)
    if not storms:
        print(f"[{SKILL_ID}] advisories present but no usable "
              f"pressure/id fields — check payload structure.")
        return 0

    print(f"[{SKILL_ID}] tracking {len(storms)} storm(s) "
          f"across {len(rows)} advisor{'y' if len(rows)==1 else 'ies'}.")

    active_storms = []
    pressure_history = []
    for skey, bulletins in storms.items():
        pl = bulletins[-1][3]
        active_storms.append({
            "storm_id": skey,
            "name": storm_display_name(pl),
            "source": "nhc",
        })
        pressure_history.append({
            "storm_id": skey,
            "pressures_hpa": [b[2] for b in bulletins],
            "timestamps": [b[1].isoformat() for b in bulletins],
        })

    written = 0
    for skey, bulletins in storms.items():
        result = find_intensification(bulletins, now)
        if result is None:
            continue

        earlier, latest, delta, elapsed_h = result
        sig_id_then, _t_then, p_then, _pl_then = earlier
        sig_id_now, _t_now, p_now, pl_now = latest

        pos = storm_position(pl_now)
        if pos is None:
            print(f"[{SKILL_ID}]   {skey}: intensifying but no usable "
                  f"position; skipping.")
            continue

        geom = Point(pos).buffer(BUFFER_DEG)
        geom_geojson = mapping(geom)

        name = storm_display_name(pl_now)
        cls = storm_classification(pl_now)
        prob = score_probability(delta, elapsed_h)
        fallback = build_reasoning(name, cls, p_then, p_now, delta, elapsed_h)

        tb = TraceBuilder(now, SKILL_ID)
        tb.set_inputs(active_storms=active_storms)
        tb.set_intermediate(
            pressure_history=pressure_history,
            pressure_drops=[{
                "storm_id": skey,
                "drop_hpa": round(delta, 2),
                "period_h": round(elapsed_h, 2),
            }],
        )
        tb.add_geometry_step(
            "storm_positions",
            storm_positions=[{
                "storm_id": skey,
                "lat": float(pos[1]),
                "lon": float(pos[0]),
            }],
        )
        tb.set_probability_components(**probability_components(delta, elapsed_h))

        trace_dict = tb.build()
        prompt = prompt_typhoon_intensifying(
            trace_dict,
            name,
            "nhc",
            float(pos[1]),
            float(pos[0]),
            float(delta),
            float(elapsed_h),
            float(p_now),
        )
        reasoning = generate_reasoning(prompt, fallback)

        forecast = {
            "id": str(uuid.uuid4()),
            "issued_at": now,
            "valid_from": now,
            "valid_until": valid_until,
            "disaster_class": "typhoon",
            "geometry": json.dumps(geom_geojson),
            "probability": prob,
            "skill_id": SKILL_ID,
            "skill_version": SKILL_VERSION,
            "contributing_signal_ids": [str(sig_id_then), str(sig_id_now)],
            "reasoning": reasoning,
            "is_baseline": False,
            "trace": json.dumps(trace_dict),
        }
        insert_forecast(db, forecast)
        written += 1
        print(f"[{SKILL_ID}]   {name}: {p_then:.0f}→{p_now:.0f} hPa "
              f"over {elapsed_h:.1f}h (Δ={delta:.1f}) p={prob}")

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
