"""Deterministic ReAct control loop for the critic agent."""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Connection

try:
    from health_gate import preflight_probe, should_abort_cycle
    from llm_client import DEFAULT_REASONING_MODEL, DEFAULT_HAIKU, call_messages
except ImportError:
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
from agents.critic.tools import TOOL_SCHEMAS, dispatch_tool

AGENT_MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "12"))

SYSTEM_PROMPT = """You are the Envision critic agent.
You reason over RAW per-skill forecast performance (producer=rule scoring stream),
Brier scores, and override_frequency (how often the forecaster drops a skill's
raw candidates). You target the existing mutator or generator — you do NOT
author skill code yourself, score proposals, or promote anything.

Tools:
- list_skills(): skills + Brier + hit_rate + override_frequency
- inspect_forecasts(skill_id): raw forecasts + evaluation/GT trace
- mutate_skill(skill_id): TERMINAL — invoke existing mutator; returns proposal id
- generate_skill(disaster_class, seed): TERMINAL only when operator-seeded;
  refused on a plain daily tick without the generator gate

Each turn: optionally write 1–2 first-person sentences in the text block beside
tool_use (intent on the first turns; sense-making after observations). Always
call exactly one tool via tool_use — never suppress tool_use because you wrote
prose. Name places in words when discussing geography.
Never write raw lat/lng, decimal degree pairs, or N/S E/W numeric coordinates
in prose.
Prefer mutate on underperforming or frequently-overridden skills.
Never call generate_skill unless the gate allows it.
After a successful mutate or generate, you are done.
"""

OnStep = Callable[[dict[str, Any]], None]


@dataclass
class CriticResult:
    agent_run_id: UUID
    status: str
    step_count: int
    proposal_ids: list[str] = field(default_factory=list)
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
    )
    if commit_each_step:
        db.commit()
    if on_step is not None:
        on_step(
            step_to_sse_payload(
                run_id,
                seq=seq,
                step_type=step_type,
                tool=tool,
                tool_input=tool_input,
                tool_output=tool_output,
                geo_focus=None,
            )
        )


def run_critic_loop(
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
    budget: Any = None,
) -> CriticResult:
    """Run one critic ReAct cycle (mutation/generation targeting)."""
    max_steps = max_steps if max_steps is not None else AGENT_MAX_STEPS
    call_llm = call_llm or call_messages
    preflight = preflight or preflight_probe
    abort_check = abort_check or should_abort_cycle

    run_id = start_run(db, agent_type="critic", trigger=trigger)
    if commit_each_step:
        db.commit()
    seq = 0
    proposal_ids: list[str] = []

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
        return CriticResult(
            agent_run_id=run_id,
            status="gated",
            step_count=seq,
            error="preflight_probe_failed",
        )

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                f"Run a critic cycle at {now.isoformat()}. "
                "List skills, inspect underperformers, then mutate (or generate "
                "only if the generator gate is open)."
            ),
        }
    ]

    try:
        for _ in range(max_steps):
            response, _model = call_llm(
                call_site="critic",
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
            if thought:
                _step(step_type="thought", tool_output={"text": thought})

            tool_uses = _extract_tool_uses(response.content)
            if not tool_uses:
                messages.append(_assistant_message_payload(response))
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Please call a tool (list_skills, inspect_forecasts, "
                            "mutate_skill, or generate_skill)."
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
                    return CriticResult(
                        agent_run_id=run_id,
                        status="gated",
                        step_count=seq,
                        error="rolling_529_abort",
                    )
                continue

            messages.append(_assistant_message_payload(response))
            tool_results: list[dict] = []

            for tool_use_id, name, tool_input in tool_uses:
                _step(step_type="action", tool=name, tool_input=tool_input)

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
                    return CriticResult(
                        agent_run_id=run_id,
                        status="gated",
                        step_count=seq,
                        error="rolling_529_abort",
                    )

                observation, is_terminal = dispatch_tool(
                    name,
                    tool_input,
                    db=db,
                    now=now,
                    budget=budget,
                )
                _step(
                    step_type="observation",
                    tool=name,
                    tool_output=observation,
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": json.dumps(observation, default=str),
                    }
                )

                if is_terminal:
                    if isinstance(observation, dict):
                        pid = observation.get("proposal_id")
                        if observation.get("accepted") and pid:
                            proposal_ids.append(str(pid))
                    _step(
                        step_type="terminal",
                        tool=name,
                        tool_output={
                            "proposal_ids": proposal_ids,
                            "last": observation,
                        },
                    )
                    _finish(
                        status="completed",
                        outcome={"proposal_ids": proposal_ids},
                        step_count=seq,
                    )
                    return CriticResult(
                        agent_run_id=run_id,
                        status="completed",
                        step_count=seq,
                        proposal_ids=proposal_ids,
                    )

            messages.append({"role": "user", "content": tool_results})

        _finish(
            status="completed",
            outcome={"proposal_ids": proposal_ids, "reason": "max_steps_exhausted"},
            step_count=seq,
            error="max_steps_exhausted",
        )
        return CriticResult(
            agent_run_id=run_id,
            status="completed",
            step_count=seq,
            proposal_ids=proposal_ids,
            error="max_steps_exhausted",
        )
    except Exception as exc:  # noqa: BLE001
        _finish(
            status="failed",
            error=str(exc)[:2000],
            step_count=seq,
        )
        return CriticResult(
            agent_run_id=run_id,
            status="failed",
            step_count=seq,
            proposal_ids=proposal_ids,
            error=str(exc),
        )
