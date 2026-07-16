"""Price candidates via aggregate, then persist through forecast_writer."""
from __future__ import annotations

from typing import TYPE_CHECKING

from psycopg import Connection

if TYPE_CHECKING:
    from agent.lib.forecast_model import Forecast

try:
    from forecast_writer import emit_forecasts
except ImportError:
    from agent.lib.forecast_writer import emit_forecasts  # type: ignore

from pipeline.aggregator import aggregate, default_config
from pipeline.hit_rates import fetch_skill_hit_rates


def emit_priced(
    forecasts: list[Forecast],
    db: Connection,
    *,
    producer: str = "rule",
    agent_run_id: str | None = None,
    table: str = "forecasts",
    lineage_id: str | None = None,
) -> int:
    """Fetch hit rates → aggregate → emit_forecasts. Shared by rule + agent paths."""
    if not forecasts:
        return 0
    if table == "forecasts_shadow":
        # Shadow path: price then write to shadow (no producer columns).
        rates = fetch_skill_hit_rates(db, {f.skill_id for f in forecasts})
        priced = aggregate(forecasts, rates, default_config())
        return emit_forecasts(
            priced, db, table="forecasts_shadow", lineage_id=lineage_id
        )

    rates = fetch_skill_hit_rates(db, {f.skill_id for f in forecasts})
    priced = aggregate(forecasts, rates, default_config())
    return emit_forecasts(
        priced,
        db,
        producer=producer,
        agent_run_id=agent_run_id,
    )
