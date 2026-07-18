"""Persist agent_run / agent_step rows for replay and telemetry."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from psycopg import Connection

try:
    from trace_builder import HARD_CAP_BYTES, SOFT_CAP_BYTES
except ImportError:
    from agent.lib.trace_builder import HARD_CAP_BYTES, SOFT_CAP_BYTES  # type: ignore

_ALLOWED_AGENT_TYPES = frozenset({"forecaster", "critic"})
_ALLOWED_TRIGGERS = frozenset({"button", "scheduled", "operator"})
_ALLOWED_STATUSES = frozenset({"running", "completed", "failed", "gated"})
_ALLOWED_STEP_TYPES = frozenset({"thought", "action", "observation", "gated", "terminal"})


def _cap_json(value: Any) -> Any:
    """Size-cap tool payloads to the 16KB trace discipline."""
    if value is None:
        return None
    if not isinstance(value, (dict, list)):
        return value
    obj: dict[str, Any]
    if isinstance(value, list):
        obj = {"_items": value}
    else:
        obj = dict(value)
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str)
    if len(raw.encode("utf-8")) <= SOFT_CAP_BYTES:
        return value if isinstance(value, (dict, list)) else obj
    # Progressive truncation: keep a truncated marker + head of JSON.
    truncated = {
        "_truncated": True,
        "preview": raw[: max(0, SOFT_CAP_BYTES - 64)],
    }
    hard = json.dumps(truncated, separators=(",", ":"), ensure_ascii=False)
    if len(hard.encode("utf-8")) > HARD_CAP_BYTES:
        return {"_truncated": True, "error": "tool_output_hard_cap_exceeded"}
    return truncated


def start_run(
    db: Connection,
    *,
    agent_type: str,
    trigger: str,
) -> UUID:
    if agent_type not in _ALLOWED_AGENT_TYPES:
        raise ValueError(f"agent_type must be one of {_ALLOWED_AGENT_TYPES}")
    if trigger not in _ALLOWED_TRIGGERS:
        raise ValueError(f"trigger must be one of {_ALLOWED_TRIGGERS}")
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_run (agent_type, trigger, status)
            VALUES (%s, %s, 'running')
            RETURNING id
            """,
            (agent_type, trigger),
        )
        row = cur.fetchone()
    return row[0]


def append_step(
    db: Connection,
    *,
    agent_run_id: UUID | str,
    seq: int,
    step_type: str,
    tool: str | None = None,
    tool_input: Any = None,
    tool_output: Any = None,
    geo_focus_geojson: str | dict | None = None,
) -> UUID:
    if step_type not in _ALLOWED_STEP_TYPES:
        raise ValueError(f"step_type must be one of {_ALLOWED_STEP_TYPES}")
    capped_in = _cap_json(tool_input)
    capped_out = _cap_json(tool_output)
    geo_s: str | None
    if geo_focus_geojson is None:
        geo_s = None
    elif isinstance(geo_focus_geojson, str):
        geo_s = geo_focus_geojson
    else:
        geo_s = json.dumps(geo_focus_geojson)

    with db.cursor() as cur:
        if geo_s is None:
            cur.execute(
                """
                INSERT INTO agent_step (
                  agent_run_id, seq, step_type, tool, tool_input, tool_output
                ) VALUES (
                  %s, %s, %s, %s, %s::jsonb, %s::jsonb
                )
                RETURNING id
                """,
                (
                    str(agent_run_id),
                    seq,
                    step_type,
                    tool,
                    json.dumps(capped_in) if capped_in is not None else None,
                    json.dumps(capped_out) if capped_out is not None else None,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO agent_step (
                  agent_run_id, seq, step_type, tool, tool_input, tool_output, geo_focus
                ) VALUES (
                  %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                  ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
                )
                RETURNING id
                """,
                (
                    str(agent_run_id),
                    seq,
                    step_type,
                    tool,
                    json.dumps(capped_in) if capped_in is not None else None,
                    json.dumps(capped_out) if capped_out is not None else None,
                    geo_s,
                ),
            )
        step_id = cur.fetchone()[0]
        cur.execute(
            """
            UPDATE agent_run
            SET step_count = GREATEST(step_count, %s)
            WHERE id = %s
            """,
            (seq, str(agent_run_id)),
        )
    return step_id


def finish_run(
    db: Connection,
    *,
    agent_run_id: UUID | str,
    status: str,
    outcome: dict | list | None = None,
    health_gate_state: str | None = None,
    error: str | None = None,
    step_count: int | None = None,
) -> None:
    if status not in _ALLOWED_STATUSES:
        raise ValueError(f"status must be one of {_ALLOWED_STATUSES}")
    finished = datetime.now(timezone.utc)
    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_run
            SET status = %s,
                finished_at = %s,
                outcome = %s::jsonb,
                health_gate_state = %s,
                error = %s,
                step_count = COALESCE(%s, step_count)
            WHERE id = %s
            """,
            (
                status,
                finished,
                json.dumps(outcome) if outcome is not None else None,
                health_gate_state,
                error,
                step_count,
                str(agent_run_id),
            ),
        )


def get_run(db: Connection, run_id: UUID | str) -> dict[str, Any] | None:
    """Return agent_run metadata or None if missing."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT id, agent_type, trigger, status, started_at, finished_at,
                   step_count, outcome, health_gate_state, error
            FROM agent_run
            WHERE id = %s
            """,
            (str(run_id),),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": str(row[0]),
        "agent_type": row[1],
        "trigger": row[2],
        "status": row[3],
        "started_at": row[4].isoformat() if row[4] else None,
        "finished_at": row[5].isoformat() if row[5] else None,
        "step_count": int(row[6] or 0),
        "outcome": row[7],
        "health_gate_state": row[8],
        "error": row[9],
    }


def iter_steps(db: Connection, run_id: UUID | str) -> list[dict[str, Any]]:
    """Return ordered agent_step rows with geo_focus as GeoJSON text."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT seq, step_type, tool, tool_input, tool_output,
                   ST_AsGeoJSON(geo_focus) AS geo_focus, created_at
            FROM agent_step
            WHERE agent_run_id = %s
            ORDER BY seq ASC
            """,
            (str(run_id),),
        )
        rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for seq, step_type, tool, tool_input, tool_output, geo_focus, created_at in rows:
        geo: Any = None
        if geo_focus:
            try:
                geo = json.loads(geo_focus)
            except (TypeError, json.JSONDecodeError):
                geo = geo_focus
        out.append(
            {
                "seq": int(seq),
                "step_type": step_type,
                "tool": tool,
                "tool_input": tool_input,
                "tool_output": tool_output,
                "geo_focus": geo,
                "created_at": created_at,
            }
        )
    return out


def _promote_enrichment_fields(
    payload: dict[str, Any],
    tool_input: Any,
    tool_output: Any,
) -> dict[str, Any]:
    """Lift known T11 fields from input/output onto the SSE top level."""
    for bag in (tool_input, tool_output):
        if not isinstance(bag, dict):
            continue
        if "skill_id" in bag and bag["skill_id"] is not None:
            payload["skill_id"] = bag["skill_id"]
        if "input_layers" in bag and bag["input_layers"] is not None:
            payload["input_layers"] = bag["input_layers"]
        if "candidates" in bag and bag["candidates"] is not None:
            payload["candidates"] = bag["candidates"]
    return payload


def step_to_sse_payload(
    run_id: UUID | str | None,
    *,
    seq: int,
    step_type: str,
    tool: str | None = None,
    tool_input: Any = None,
    tool_output: Any = None,
    geo_focus: Any = None,
    ts: datetime | None = None,
) -> dict[str, Any]:
    """v4 §5 SSE step payload (plus T11 promoted enrichment fields)."""
    when = ts or datetime.now(timezone.utc)
    if isinstance(geo_focus, str):
        try:
            geo_focus = json.loads(geo_focus)
        except (TypeError, json.JSONDecodeError):
            pass
    payload: dict[str, Any] = {
        "run_id": str(run_id) if run_id is not None else None,
        "seq": int(seq),
        "step_type": step_type,
        "tool": tool,
        "input": tool_input,
        "output": tool_output,
        "geo_focus": geo_focus,
        "ts": when.isoformat() if hasattr(when, "isoformat") else str(when),
    }
    return _promote_enrichment_fields(payload, tool_input, tool_output)


def step_row_to_sse_payload(run_id: UUID | str, row: dict[str, Any]) -> dict[str, Any]:
    """Convert an iter_steps row into an SSE payload."""
    return step_to_sse_payload(
        run_id,
        seq=row["seq"],
        step_type=row["step_type"],
        tool=row.get("tool"),
        tool_input=row.get("tool_input"),
        tool_output=row.get("tool_output"),
        geo_focus=row.get("geo_focus"),
        ts=row.get("created_at"),
    )
