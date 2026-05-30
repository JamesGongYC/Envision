#!/usr/bin/env python3
"""One-shot validation pass for the six v2 ingestion sources (read-only)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field

import psycopg

DATABASE_URL = os.environ.get("DATABASE_URL")

# Each rule is a list of alias groups; at least one key per group must be present.
PAYLOAD_RULES: dict[str, list[list[str]]] = {
    "firms_viirs": [
        ["brightness", "bright_ti4", "bright_ti5"],
        ["frp"],
        ["confidence"],
    ],
    "firms_modis": [
        ["brightness", "bright_ti4", "bright_ti5"],
        ["frp"],
        ["confidence"],
    ],
    "nws_alerts": [
        ["event"],
        ["affectedZones", "geometry"],
    ],
    "nhc": [
        ["name", "stormName"],
        ["pressure", "minimumPressure", "minPressure", "centralPressure"],
        ["maximumWind", "winds", "maxWind"],
    ],
    "open_meteo": [
        ["temp_max", "temp_max_c"],
        ["rh_min", "rh_min_pct"],
        ["wind_max", "wind_max_kmh"],
        ["precip_sum", "precip_sum_mm"],
        ["score"],
        ["region", "region_name"],
    ],
    "jtwc": [
        ["name", "stormName"],
        ["lat", "latitude", "latitudeNumeric"],
        ["lon", "longitude", "longitudeNumeric"],
        ["pressure", "minimumPressure", "minPressure", "centralPressure"],
        ["maximumWind", "winds", "maxWind"],
    ],
}

PRE_SEASON = {"nhc", "jtwc"}
SOURCES = (
    "firms_viirs",
    "firms_modis",
    "nws_alerts",
    "nhc",
    "open_meteo",
    "jtwc",
)


@dataclass
class SourceResult:
    source: str
    rows_24h: int = 0
    invalid_geom: int = 0
    payload_ok: bool = True
    payload_notes: list[str] = field(default_factory=list)
    dedup_ok: bool = True
    dedup_total: int = 0
    dedup_distinct: int = 0
    status: str = "PASS"
    hard_fail: bool = False

    def finalize(self) -> None:
        if self.invalid_geom > 0 or not self.dedup_ok or not self.payload_ok:
            self.status = "FAIL"
            self.hard_fail = True
        elif self.source in PRE_SEASON and self.rows_24h == 0:
            self.status = "INFO"
        elif self.rows_24h == 0:
            self.status = "WARN"
            self.hard_fail = True
        else:
            self.status = "PASS"


def has_key(payload: dict, keys: list[str]) -> bool:
    for k in keys:
        if k in payload and payload[k] not in (None, "", [], {}):
            return True
    return False


def check_payload_samples(
    cur: psycopg.Cursor, source: str, hours: int
) -> tuple[bool, list[str]]:
    rules = PAYLOAD_RULES[source]
    if source == "nws_alerts":
        cur.execute(
            """
            SELECT payload, ST_IsValid(geometry) AS geom_valid
            FROM signals
            WHERE source = %s
              AND ingested_at > now() - make_interval(hours => %s)
            ORDER BY random()
            LIMIT 5
            """,
            (source, hours),
        )
    else:
        cur.execute(
            """
            SELECT payload, NULL::boolean AS geom_valid
            FROM signals
            WHERE source = %s
              AND ingested_at > now() - make_interval(hours => %s)
            ORDER BY random()
            LIMIT 5
            """,
            (source, hours),
        )
    rows = cur.fetchall()
    if not rows:
        if source in PRE_SEASON:
            return True, ["no rows in window (pre-season OK)"]
        return True, ["no rows in window (skip payload sample)"]

    notes: list[str] = []
    ok = True
    for i, (payload, geom_valid) in enumerate(rows, 1):
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            ok = False
            notes.append(f"sample {i}: payload not an object")
            continue

        if source == "nws_alerts":
            has_event = has_key(payload, ["event"])
            has_geom_hint = has_key(payload, ["affectedZones"]) or geom_valid is True
            if not has_event:
                ok = False
                notes.append(f"sample {i}: missing event")
            if not has_geom_hint:
                ok = False
                notes.append(f"sample {i}: missing affectedZones/geometry")
            continue

        missing_groups: list[str] = []
        for group in rules:
            if not has_key(payload, group):
                missing_groups.append("/".join(group))
        if missing_groups:
            ok = False
            notes.append(f"sample {i}: missing {', '.join(missing_groups)}")

    if ok and not notes:
        notes.append(f"{len(rows)} sample(s) OK")
    return ok, notes


def validate_source(cur: psycopg.Cursor, source: str, hours: int) -> SourceResult:
    res = SourceResult(source=source)

    cur.execute(
        """
        SELECT count(*)
        FROM signals
        WHERE source = %s
          AND ingested_at > now() - make_interval(hours => %s)
        """,
        (source, hours),
    )
    res.rows_24h = cur.fetchone()[0]

    cur.execute(
        """
        SELECT count(*)
        FROM signals
        WHERE source = %s
          AND ingested_at > now() - make_interval(hours => %s)
          AND NOT ST_IsValid(geometry)
        """,
        (source, hours),
    )
    res.invalid_geom = cur.fetchone()[0]

    res.payload_ok, res.payload_notes = check_payload_samples(cur, source, hours)

    cur.execute(
        """
        SELECT count(*), count(DISTINCT dedup_key)
        FROM signals
        WHERE source = %s
          AND ingested_at > now() - make_interval(hours => %s)
        """,
        (source, hours),
    )
    res.dedup_total, res.dedup_distinct = cur.fetchone()
    res.dedup_ok = res.dedup_total == res.dedup_distinct

    res.finalize()
    return res


def print_table(results: list[SourceResult]) -> None:
    print()
    print("| source | rows_24h | invalid_geom | payload_ok | dedup_ok | status |")
    print("|---|---:|---:|---|---|---|")
    for r in results:
        payload_cell = "yes" if r.payload_ok else "no"
        dedup_cell = "yes" if r.dedup_ok else f"no ({r.dedup_total}!={r.dedup_distinct})"
        print(
            f"| {r.source} | {r.rows_24h} | {r.invalid_geom} | {payload_cell} | "
            f"{dedup_cell} | {r.status} |"
        )
    print()
    for r in results:
        if r.payload_notes:
            print(f"**{r.source}** payload: {'; '.join(r.payload_notes)}")
    print()


def main() -> int:
    p = argparse.ArgumentParser(description="Validate six ingestion signal sources")
    p.add_argument("--hours", type=int, default=24, help="Lookback window (default: 24)")
    args = p.parse_args()

    if not DATABASE_URL:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    results: list[SourceResult] = []
    with psycopg.connect(DATABASE_URL) as db:
        with db.cursor() as cur:
            for source in SOURCES:
                results.append(validate_source(cur, source, args.hours))

    print_table(results)

    hard_failures = [r for r in results if r.hard_fail]
    warns = [r for r in results if r.status == "WARN"]
    if hard_failures:
        names = ", ".join(r.source for r in hard_failures)
        print(f"Validation FAILED for: {names}", file=sys.stderr)
        return 1
    if warns:
        names = ", ".join(r.source for r in warns)
        print(f"Validation warnings: {names}", file=sys.stderr)
    print("Validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
