"""AggregatorInterface — prices via pipeline.aggregate, then writes producer='agent'.

Agent supplies the selected set only. Probabilities are authored solely by
the deterministic aggregator (T3).
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from psycopg import Connection

if TYPE_CHECKING:
    from agent.lib.forecast_model import Forecast

try:
    from forecast_writer import emit_forecasts
except ImportError:
    from agent.lib.forecast_writer import emit_forecasts  # type: ignore

from pipeline.aggregator import aggregate, default_config
from pipeline.hit_rates import fetch_skill_hit_rates


def emit_selected(
    selected: list[Forecast],
    *,
    db: Connection,
    agent_run_id: UUID | str,
) -> list[UUID]:
    """Persist agent-curated forecasts after aggregator pricing."""
    if not selected:
        return []
    rates = fetch_skill_hit_rates(db, {f.skill_id for f in selected})
    priced = aggregate(selected, rates, default_config())
    emit_forecasts(
        priced,
        db,
        producer="agent",
        agent_run_id=str(agent_run_id),
    )
    return [UUID(str(f.id)) for f in priced]
