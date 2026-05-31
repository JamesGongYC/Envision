#!/usr/bin/env python3
"""housekeeping-retention — delete aged signals/forecasts; refresh signal_catalog."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

import psycopg
from psycopg import Connection

SKILL_ID = "housekeeping-retention"

DATABASE_URL = os.environ.get("DATABASE_URL")


def parse_now(argv: list[str] | None = None) -> datetime:
    p = argparse.ArgumentParser(description="Run retention deletes and refresh signal_catalog")
    p.add_argument("--now", default=None, help="ISO8601 UTC cutoff (default: now)")
    args = p.parse_args(argv)
    if args.now is None:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def run(now: datetime, db: Connection) -> dict:
    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM signals WHERE ingested_at < %s - interval '30 days'",
            (now,),
        )
        signals_deleted = cur.rowcount

        cur.execute(
            "DELETE FROM forecasts WHERE issued_at < %s - interval '60 days'",
            (now,),
        )
        forecasts_deleted = cur.rowcount

        cur.execute(
            "DELETE FROM wind_fields WHERE valid_at < %s - interval '14 days'",
            (now,),
        )
        wind_fields_deleted = cur.rowcount

        cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY signal_catalog")

    db.commit()
    result = {
        "signals_deleted": signals_deleted,
        "forecasts_deleted": forecasts_deleted,
        "wind_fields_deleted": wind_fields_deleted,
    }
    print(
        f"[{SKILL_ID}] deleted {signals_deleted} signals, "
        f"{forecasts_deleted} forecasts, {wind_fields_deleted} wind_fields; "
        "refreshed signal_catalog."
    )
    return result


def main() -> int:
    if not DATABASE_URL:
        print(f"[{SKILL_ID}] DATABASE_URL not set", file=sys.stderr)
        return 2
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
