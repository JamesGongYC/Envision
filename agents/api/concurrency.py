"""Bounded in-flight agent runs across button-fires + scheduled critic."""
from __future__ import annotations

import os

from psycopg import Connection

AGENT_MAX_IN_FLIGHT = int(os.environ.get("AGENT_MAX_IN_FLIGHT", "2"))


def in_flight_count(db: Connection) -> int:
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)::int
            FROM agent_run
            WHERE status = 'running'
            """
        )
        row = cur.fetchone()
    return int(row[0] or 0)


def at_capacity(db: Connection, *, limit: int | None = None) -> bool:
    cap = AGENT_MAX_IN_FLIGHT if limit is None else limit
    return in_flight_count(db) >= cap
