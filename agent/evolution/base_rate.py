"""Base-rate Brier for generated skill promotion (A1)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from psycopg import Connection

from agent.lib.scoring import class_aliases


def base_rate_brier(
    db: Connection,
    disaster_class: str,
    *,
    window_days: int = 14,
    now: datetime | None = None,
) -> float | None:
    """Brier score of a constant forecaster at class event frequency.

    p = n_ground_truth_events / n_evaluation_opportunities in window;
    returns p * (1 - p).
    """
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=window_days)
    aliases = list(class_aliases(disaster_class))

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)::float
            FROM ground_truth
            WHERE disaster_class = ANY(%s)
              AND occurred_at >= %s
            """,
            (aliases, since),
        )
        n_events = float(cur.fetchone()[0] or 0)

        cur.execute(
            """
            SELECT COUNT(*)::float
            FROM evaluations e
            JOIN forecasts f ON f.id = e.forecast_id
            WHERE f.disaster_class = %s
              AND e.evaluated_at >= %s
            """,
            (disaster_class, since),
        )
        n_opportunities = float(cur.fetchone()[0] or 0)

    if n_opportunities < 1:
        return None

    p = min(0.85, max(0.0, n_events / n_opportunities))
    return p * (1.0 - p)
