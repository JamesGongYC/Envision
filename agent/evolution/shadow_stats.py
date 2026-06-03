"""Shadow Brier readouts for operator review (Day 4 CLI)."""
from __future__ import annotations

from psycopg import Connection


def fetch_shadow_brier_by_lineage(db: Connection) -> list[tuple]:
    """Return rows: (lineage_id, shadow_brier, n_evals)."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT fs.lineage_id,
                   AVG(se.brier_contribution)::float AS shadow_brier,
                   COUNT(*)::int AS n_evals
            FROM shadow_evaluations se
            JOIN forecasts_shadow fs ON fs.id = se.shadow_forecast_id
            WHERE fs.shadow_promotion_status = 'evaluating'
            GROUP BY fs.lineage_id
            ORDER BY shadow_brier ASC NULLS LAST
            """
        )
        return cur.fetchall()
