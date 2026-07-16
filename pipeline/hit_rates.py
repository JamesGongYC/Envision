"""Fetch recent per-skill hit rates for the aggregator (I/O; not inside aggregate)."""
from __future__ import annotations

from collections.abc import Iterable

from psycopg import Connection


def fetch_skill_hit_rates(
    db: Connection,
    skill_ids: Iterable[str],
    *,
    window_days: int = 14,
) -> dict[str, float]:
    """Return skill_id -> hit_rate over the recent evaluation window.

    Missing skills (no evaluations) map to 0.0.
    """
    ids = sorted({str(s) for s in skill_ids if s})
    rates = {sid: 0.0 for sid in ids}
    if not ids:
        return rates

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT
              f.skill_id,
              SUM(CASE WHEN e.outcome = 'hit' THEN 1 ELSE 0 END)::float
                / NULLIF(COUNT(*), 0) AS hit_rate
            FROM evaluations e
            JOIN forecasts f ON f.id = e.forecast_id
            WHERE f.skill_id = ANY(%s)
              AND e.evaluated_at > now() - (%s * interval '1 day')
            GROUP BY f.skill_id
            """,
            (ids, window_days),
        )
        for skill_id, hit_rate in cur.fetchall():
            rates[str(skill_id)] = float(hit_rate or 0.0)
    return rates
