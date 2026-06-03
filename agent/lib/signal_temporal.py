"""Temporal predicates for signals queries (backtest-safe, keyed off `now`)."""
from __future__ import annotations

from datetime import datetime, timezone


def parse_payload_ts(value: str | None, fallback: datetime) -> datetime:
    """Parse ISO8601 from NWS payload fields; return fallback if missing/invalid."""
    if not value:
        return fallback
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return fallback


def trailing_timestamp_sql(lookback_hours: int, *, table_alias: str = "") -> str:
    """SQL fragment: timestamp in (now - lookback, now]. Requires %(now)s twice."""
    prefix = f"{table_alias}." if table_alias else ""
    return (
        f"{prefix}timestamp > %s - interval '{lookback_hours} hours' "
        f"AND {prefix}timestamp <= %s"
    )


def nws_fire_warning_active_sql(*, table_alias: str = "") -> str:
    """Alerts active as of %(now)s from payload effective/expires (fire_warning only)."""
    p = f"{table_alias}." if table_alias else ""
    return f"""(
  {p}signal_type != 'fire_warning'
  OR (
    COALESCE(({p}payload->>'effective')::timestamptz, {p}timestamp) <= %s
    AND (
      NULLIF({p}payload->>'expires', '') IS NULL
      OR ({p}payload->>'expires')::timestamptz >= %s
    )
  )
)"""
