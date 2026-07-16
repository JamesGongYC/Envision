"""Non-mutable forecast persistence (production + shadow)."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from psycopg import Connection

try:
    from forecast_model import Forecast
except ImportError:
    from agent.lib.forecast_model import Forecast  # type: ignore[no-redef]

_ALLOWED_TABLES = frozenset({"forecasts", "forecasts_shadow"})


_ALLOWED_PRODUCERS = frozenset({"rule", "agent"})


def emit_forecasts(
    forecasts: list[Forecast],
    db: Connection,
    *,
    table: str = "forecasts",
    lineage_id: str | None = None,
    producer: str = "rule",
    agent_run_id: str | None = None,
) -> int:
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"table must be one of {_ALLOWED_TABLES}, got {table!r}")
    if table == "forecasts_shadow" and not lineage_id:
        raise ValueError("lineage_id required when table='forecasts_shadow'")
    if producer not in _ALLOWED_PRODUCERS:
        raise ValueError(f"producer must be one of {_ALLOWED_PRODUCERS}, got {producer!r}")
    if not forecasts:
        return 0

    if table == "forecasts_shadow":
        sql = """
            INSERT INTO forecasts_shadow (
              id, issued_at, valid_from, valid_until,
              disaster_class, geometry, probability,
              skill_id, skill_version, contributing_signal_ids,
              reasoning, is_baseline, trace, lineage_id
            ) VALUES (
              %(id)s, %(issued_at)s, %(valid_from)s, %(valid_until)s,
              %(disaster_class)s,
              ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326)),
              %(probability)s,
              %(skill_id)s, %(skill_version)s,
              %(contributing_signal_ids)s::uuid[],
              %(reasoning)s, %(is_baseline)s,
              %(trace)s::jsonb,
              %(lineage_id)s
            )
        """
    else:
        sql = """
            INSERT INTO forecasts (
              id, issued_at, valid_from, valid_until,
              disaster_class, geometry, probability,
              skill_id, skill_version, contributing_signal_ids,
              reasoning, is_baseline, trace,
              producer, agent_run_id
            ) VALUES (
              %(id)s, %(issued_at)s, %(valid_from)s, %(valid_until)s,
              %(disaster_class)s,
              ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326)),
              %(probability)s,
              %(skill_id)s, %(skill_version)s,
              %(contributing_signal_ids)s::uuid[],
              %(reasoning)s, %(is_baseline)s,
              %(trace)s::jsonb,
              %(producer)s, %(agent_run_id)s
            )
        """

    rows = []
    for f in forecasts:
        trace_s = f.trace_json() if hasattr(f, "trace_json") else (
            f.trace if isinstance(f.trace, str) else json.dumps(f.trace)
        )
        row = {
            "id": str(f.id),
            "issued_at": f.issued_at,
            "valid_from": f.valid_from,
            "valid_until": f.valid_until,
            "disaster_class": f.disaster_class,
            "geometry": f.geometry if isinstance(f.geometry, str) else json.dumps(f.geometry),
            "probability": f.probability,
            "skill_id": f.skill_id,
            "skill_version": f.skill_version,
            "contributing_signal_ids": f.contributing_signal_ids,
            "reasoning": f.reasoning,
            "is_baseline": f.is_baseline,
            "trace": trace_s,
        }
        if table == "forecasts_shadow":
            row["lineage_id"] = lineage_id
        else:
            row["producer"] = producer
            row["agent_run_id"] = agent_run_id
        rows.append(row)

    with db.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)
