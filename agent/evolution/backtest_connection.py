"""Connection proxy: enforce per-skill signal lookback during backtest replay."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
from psycopg import Connection, Cursor

_SIGNALS_FROM = re.compile(r"\bfrom\s+signals\b", re.IGNORECASE)

SKILL_LOOKBACK: dict[str, timedelta] = {
    "wildfire_risk_elevated": timedelta(hours=24),
    "wildfire_rapid_growth": timedelta(hours=72),
    "typhoon_intensifying": timedelta(hours=14),
    "typhoon_landfall_imminent": timedelta(hours=6),
}


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _audit_rows(
    conn: Connection,
    skill_id: str,
    t: datetime,
    rows: list[tuple],
    description: list[Any] | None,
) -> None:
    if not rows or description is None:
        return
    lookback = SKILL_LOOKBACK.get(skill_id)
    if lookback is None:
        return

    t = _ensure_utc(t)
    window_start = t - lookback
    names = [d[0] for d in description]

    if "timestamp" in names:
        ts_idx = names.index("timestamp")
        for row in rows:
            ts = row[ts_idx]
            if ts is None:
                continue
            ts = _ensure_utc(ts)
            if ts > t or ts < window_start:
                rid = row[names.index("id")] if "id" in names else "?"
                raise RuntimeError(
                    f"signal window violation: skill={skill_id} t={t.isoformat()} "
                    f"allowed=[{window_start.isoformat()}, {t.isoformat()}] "
                    f"got id={rid} timestamp={ts.isoformat()}"
                )
        return

    if "id" not in names:
        return

    id_idx = names.index("id")
    ids = [row[id_idx] for row in rows if row[id_idx] is not None]
    if not ids:
        return

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, timestamp
            FROM signals
            WHERE id = ANY(%s::uuid[])
            """,
            (ids,),
        )
        for rid, ts in cur.fetchall():
            if ts is None:
                continue
            ts = _ensure_utc(ts)
            if ts > t or ts < window_start:
                raise RuntimeError(
                    f"signal window violation: skill={skill_id} t={t.isoformat()} "
                    f"allowed=[{window_start.isoformat()}, {t.isoformat()}] "
                    f"got id={rid} timestamp={ts.isoformat()}"
                )


class BacktestCursor:
    """Wraps a psycopg cursor; audits signals SELECT results."""

    def __init__(
        self,
        inner: Cursor,
        conn: Connection,
        skill_id: str,
        t: datetime,
    ) -> None:
        self._inner = inner
        self._conn = conn
        self._skill_id = skill_id
        self._t = t
        self._audit_signals = False

    def execute(self, query, params=None, **kwargs):
        self._audit_signals = bool(
            isinstance(query, str) and _SIGNALS_FROM.search(query)
        )
        return self._inner.execute(query, params, **kwargs)

    def fetchone(self):
        row = self._inner.fetchone()
        if row is not None and self._audit_signals:
            _audit_rows(
                self._conn,
                self._skill_id,
                self._t,
                [row],
                self._inner.description,
            )
        return row

    def fetchall(self):
        rows = self._inner.fetchall()
        if rows and self._audit_signals:
            _audit_rows(
                self._conn,
                self._skill_id,
                self._t,
                rows,
                self._inner.description,
            )
        return rows

    def fetchmany(self, size=0):
        rows = self._inner.fetchmany(size)
        if rows and self._audit_signals:
            _audit_rows(
                self._conn,
                self._skill_id,
                self._t,
                rows,
                self._inner.description,
            )
        return rows

    def __enter__(self):
        self._inner.__enter__()
        return self

    def __exit__(self, *args):
        return self._inner.__exit__(*args)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


class BacktestConnection:
    """Thin wrapper; skills call cursor() and get audited cursors."""

    def __init__(self, inner: Connection, skill_id: str, t: datetime) -> None:
        self._inner = inner
        self._skill_id = skill_id
        self._t = t

    def cursor(self, *args, **kwargs) -> BacktestCursor:
        return BacktestCursor(
            self._inner.cursor(*args, **kwargs),
            self._inner,
            self._skill_id,
            self._t,
        )

    def __getattr__(self, name: str):
        return getattr(self._inner, name)
