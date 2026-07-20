"""Deterministic ReAct control loop for the forecaster agent."""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from psycopg import Connection

try:
    from forecast_model import Forecast
    from health_gate import preflight_probe, should_abort_cycle
    from llm_client import DEFAULT_REASONING_MODEL, DEFAULT_HAIKU, call_messages
except ImportError:
    from agent.lib.forecast_model import Forecast  # type: ignore
    from agent.lib.health_gate import preflight_probe, should_abort_cycle  # type: ignore
    from agent.lib.llm_client import (  # type: ignore
        DEFAULT_HAIKU,
        DEFAULT_REASONING_MODEL,
        call_messages,
    )

from agents.common.agent_telemetry import (
    append_step,
    finish_run,
    start_run,
    step_to_sse_payload,
)
from agents.common.prose_scrub import scrub_coord_prose
from agents.common.react_turn import missing_text_nudge, should_retry_for_text
from agents.forecaster.tools import (
    TOOL_SCHEMAS,
    dispatch_tool,
    enrich_run_skill_action_input,
)

AGENT_MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "12"))

SYSTEM_PROMPT = """You are the Envision forecaster agent.
You reason over open weather/disaster signals and detection skills, then select
which candidate forecasts to emit. You do NOT author probabilities — the
deterministic aggregator prices the selected set.

Tools:
- inspect_signals(bbox?): catalog + freshness
- list_skills(): detection skills + recent Brier/hit_rate
- run_skill(skill_id): run a skill; returns candidates (raw output is scored independently)
- emit(selected): TERMINAL — pass selected forecast objects by id only

Each turn: you MUST write 1–2 first-person sentences in the text block beside
tool_use (intent on the first turns; sense-making after observations). Always
call exactly one tool via tool_use — never suppress tool_use because you wrote
prose. Name places in words (e.g. "northern California", "west of Luzon").
Never write raw lat/lng, decimal degree pairs, or N/S E/W numeric coordinates
in prose — geometry belongs in tool payloads only.
Prefer inspect → list → run relevant skills → emit.
If nothing is worth emitting, call emit with an empty selected list.
"""

OnStep = Callable[[dict[str, Any]], None]


@dataclass
class ForecasterResult:
    agent_run_id: UUID
    status: str
    step_count: int
    emitted_ids: list[str] = field(default_factory=list)
    error: str | None = None


def _extract_text(content: Any) -> str:
    parts: list[str] = []
    if not content:
        return ""
    for block in content:
        btype = getattr(block, "type", None) or (
            block.get("type") if isinstance(block, dict) else None
        )
        if btype == "text":
            text = getattr(block, "text", None)
            if text is None and isinstance(block, dict):
                text = block.get("text")
            if text:
                parts.append(str(text))
    return "\n".join(parts).strip()


def _extract_tool_uses(content: Any) -> list[tuple[str, str, dict]]:
    """Return list of (tool_use_id, name, input)."""
    out: list[tuple[str, str, dict]] = []
    if not content:
        return out
    for block in content:
        btype = getattr(block, "type", None) or (
            block.get("type") if isinstance(block, dict) else None
        )
        if btype != "tool_use":
            continue
        if isinstance(block, dict):
            tid = str(block.get("id") or "")
            name = str(block.get("name") or "")
            inp = block.get("input") or {}
        else:
            tid = str(getattr(block, "id", "") or "")
            name = str(getattr(block, "name", "") or "")
            inp = getattr(block, "input", None) or {}
        if not isinstance(inp, dict):
            inp = {}
        out.append((tid, name, inp))
    return out


def _assistant_message_payload(response: Any) -> dict:
    """Serialize assistant response content into an API message dict."""
    content_out: list[dict] = []
    for block in response.content or []:
        btype = getattr(block, "type", None)
        if btype == "text":
            content_out.append({"type": "text", "text": getattr(block, "text", "")})
        elif btype == "tool_use":
            content_out.append(
                {
                    "type": "tool_use",
                    "id": getattr(block, "id", ""),
                    "name": getattr(block, "name", ""),
                    "input": getattr(block, "input", {}) or {},
                }
            )
    return {"role": "assistant", "content": content_out}


def _emit_step(
    db: Connection,
    *,
    run_id: UUID,
    seq: int,
    step_type: str,
    tool: str | None = None,
    tool_input: Any = None,
    tool_output: Any = None,
    geo_focus_geojson: str | dict | None = None,
    on_step: OnStep | None,
    commit_each_step: bool,
) -> None:
    append_step(
        db,
        agent_run_id=run_id,
        seq=seq,
        step_type=step_type,
        tool=tool,
        tool_input=tool_input,
        tool_output=tool_output,
        geo_focus_geojson=geo_focus_geojson,
    )
    if commit_each_step:
        db.commit()
    if on_step is not None:
        geo: Any = None
        if geo_focus_geojson is not None:
            if isinstance(geo_focus_geojson, str):
                try:
                    geo = json.loads(geo_focus_geojson)
                except (TypeError, json.JSONDecodeError):
                    geo = geo_focus_geojson
            else:
                geo = geo_focus_geojson
        on_step(
            step_to_sse_payload(
                run_id,
                seq=seq,
                step_type=step_type,
                tool=tool,
                tool_input=tool_input,
                tool_output=tool_output,
                geo_focus=geo,
            )
        )


def run_forecaster_loop(
    now: datetime,
    db: Connection,
    *,
    trigger: str = "operator",
    max_steps: int | None = None,
    call_llm=None,
    preflight=None,
    abort_check=None,
    on_step: OnStep | None = None,
    commit_each_step: bool = False,
) -> ForecasterResult:
    """
    Run one forecaster ReAct cycle.

    call_llm / preflight / abort_check are injectable for tests.
    on_step receives SSE payloads after each persisted step.
    commit_each_step=True commits after each step (ASGI live stream).
    """
    max_steps = max_steps if max_steps is not None else AGENT_MAX_STEPS
    call_llm = call_llm or call_messages
    preflight = preflight or preflight_probe
    abort_check = abort_check or should_abort_cycle

    run_id = start_run(db, agent_type="forecaster", trigger=trigger)
    if commit_each_step:
        db.commit()
    seq = 0
    candidate_cache: dict[str, Forecast] = {}
    emitted_ids: list[str] = []

    def _step(**kwargs: Any) -> None:
        nonlocal seq
        seq += 1
        _emit_step(
            db,
            run_id=run_id,
            seq=seq,
            on_step=on_step,
            commit_each_step=commit_each_step,
            **kwargs,
        )

    def _finish(**kwargs: Any) -> None:
        finish_run(db, agent_run_id=run_id, **kwargs)
        if commit_each_step:
            db.commit()

    if not preflight(db):
        _step(step_type="gated", tool_output={"reason": "preflight_probe_failed"})
        _finish(
            status="gated",
            health_gate_state="preflight_failed",
            step_count=seq,
        )
        return ForecasterResult(
            agent_run_id=run_id,
            status="gated",
            step_count=seq,
            error="preflight_probe_failed",
        )

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                f"Run a forecasting cycle at {now.isoformat()}. "
                "Inspect signals, consider skills, run relevant skills, then emit."
            ),
        }
    ]

    try:
        for _ in range(max_steps):
            text_retries = 0
            while True:
                response, _model = call_llm(
                    call_site="forecaster",
                    db=db,
                    messages=messages,
                    model=DEFAULT_REASONING_MODEL,
                    fallback_model=DEFAULT_HAIKU,
                    max_tokens=2048,
                    system=SYSTEM_PROMPT,
                    tools=TOOL_SCHEMAS,
                    tool_choice={"type": "any"},
                )
                thought = scrub_coord_prose(_extract_text(response.content))
                tool_uses = _extract_tool_uses(response.content)
                if should_retry_for_text(
                    thought, tool_uses, text_retries=text_retries
                ):
                    messages.append(_assistant_message_payload(response))
                    messages.append(
                        {"role": "user", "content": missing_text_nudge()}
                    )
                    text_retries += 1
                    continue
                break

            if thought:
                _step(step_type="thought", tool_output={"text": thought})

            if not tool_uses:
                messages.append(_assistant_message_payload(response))
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Please call a tool (inspect_signals, list_skills, "
                            "run_skill, or emit)."
                        ),
                    }
                )
                if abort_check(db):
                    _step(
                        step_type="gated",
                        tool_output={"reason": "rolling_529_abort"},
                    )
                    _finish(
                        status="gated",
                        health_gate_state="rolling_529",
                        step_count=seq,
                    )
                    return ForecasterResult(
                        agent_run_id=run_id,
                        status="gated",
                        step_count=seq,
                        error="rolling_529_abort",
                    )
                continue

            messages.append(_assistant_message_payload(response))
            tool_results: list[dict] = []
            terminal = False

            for tool_use_id, name, tool_input in tool_uses:
                action_input = tool_input
                if name == "run_skill":
                    action_input = enrich_run_skill_action_input(tool_input)
                _step(step_type="action", tool=name, tool_input=action_input)

                if abort_check(db):
                    _step(
                        step_type="gated",
                        tool_output={"reason": "rolling_529_abort"},
                    )
                    _finish(
                        status="gated",
                        health_gate_state="rolling_529",
                        step_count=seq,
                    )
                    return ForecasterResult(
                        agent_run_id=run_id,
                        status="gated",
                        step_count=seq,
                        error="rolling_529_abort",
                    )

                observation, geo_focus, is_terminal = dispatch_tool(
                    name,
                    tool_input,
                    db=db,
                    now=now,
                    agent_run_id=run_id,
                    candidate_cache=candidate_cache,
                )
                _step(
                    step_type="observation",
                    tool=name,
                    tool_output=observation,
                    geo_focus_geojson=geo_focus,
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": json.dumps(observation, default=str),
                    }
                )

                if is_terminal:
                    terminal = True
                    emitted_ids = list(observation.get("emitted_ids") or [])
                    _step(
                        step_type="terminal",
                        tool="emit",
                        tool_output={
                            "emitted_ids": emitted_ids,
                            "candidates": list(observation.get("candidates") or []),
                            "count": int(observation.get("count") or len(emitted_ids)),
                        },
                    )
                    _finish(
                        status="completed",
                        outcome={"forecast_ids": emitted_ids},
                        step_count=seq,
                    )
                    return ForecasterResult(
                        agent_run_id=run_id,
                        status="completed",
                        step_count=seq,
                        emitted_ids=emitted_ids,
                    )

            messages.append({"role": "user", "content": tool_results})
            if terminal:
                break

        _finish(
            status="completed",
            outcome={"forecast_ids": [], "reason": "max_steps_exhausted"},
            step_count=seq,
            error="max_steps_exhausted",
        )
        return ForecasterResult(
            agent_run_id=run_id,
            status="completed",
            step_count=seq,
            emitted_ids=[],
            error="max_steps_exhausted",
        )
    except Exception as exc:  # noqa: BLE001
        _finish(
            status="failed",
            error=str(exc)[:2000],
            step_count=seq,
        )
        return ForecasterResult(
            agent_run_id=run_id,
            status="failed",
            step_count=seq,
            error=str(exc),
        )
