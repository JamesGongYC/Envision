#!/usr/bin/env python3
"""De-novo detection skill generator (v3.2)."""
from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from psycopg import Connection

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_LIB = REPO_ROOT / "agent" / "lib"
for p in (str(REPO_ROOT), str(AGENT_LIB)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent.evolution.app_scaffold import render_app_py  # noqa: E402
from agent.evolution.budget import BudgetTracker  # noqa: E402
from agent.evolution.generation_trigger import seed_prompt  # noqa: E402
from agent.evolution.mutator import load_signal_inventory  # noqa: E402
from agent.evolution.skill_metadata import (  # noqa: E402
    parse_cadence_minutes,
    skill_id_to_folder,
)
from agent.evolution.skill_surface import normalize_mutation_surface  # noqa: E402
from agent.evolution.skill_validator import (  # noqa: E402
    ValidationReport,
    validate_generated_candidate,
)
from agent.lib.llm_client import DEFAULT_SONNET, DEFAULT_HAIKU, call_messages  # noqa: E402
from trace_builder import CuratorTraceBuilder  # noqa: E402

SONNET_MODEL = os.environ.get("ENVISION_GENERATOR_MODEL", DEFAULT_SONNET)
HAIKU_MODEL = os.environ.get("ENVISION_GENERATOR_FALLBACK_MODEL", DEFAULT_HAIKU)
MAX_TOKENS = 16384
MAX_ATTEMPTS = 3

RETURN_CONTRACT = """Your function computes and returns `list[Forecast]`. It ends with
`return forecasts`. Persistence is handled by the caller — never import emit_forecasts
or execute INSERT/UPDATE/DELETE. Probability must not exceed 0.85 (DB CHECK constraint).
Do not use module-level Path(__file__) bootstrap — exec-from-string strips __file__.
Declare DISASTER_CLASS and SKILL_CADENCE_MINUTES module constants."""

SYSTEM_PROMPT = f"""You are the Envision skill generator. Propose a brand-new detection skill
from scratch using the supplied signal catalog and operator seed.

{RETURN_CONTRACT}

Allowed imports match the skill_exec_image deps: psycopg, shapely, sklearn, numpy, httpx,
datetime, json, math, re, uuid, typing, collections, dataclasses, trace_builder,
reasoning_llm, reasoning_prompts, forecast_model.

Submit via propose_new_skill with skill_id (unique snake_case), run_py, skill_md, rationale."""

GENERATION_TOOL = {
    "name": "propose_new_skill",
    "description": "Submit a de-novo detection skill.",
    "input_schema": {
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": "Unique snake_case skill identifier.",
            },
            "run_py": {
                "type": "string",
                "description": "Complete Python mutation surface (run.py body).",
            },
            "skill_md": {
                "type": "string",
                "description": "SKILL.md documentation for operators.",
            },
            "rationale": {
                "type": "string",
                "description": "Why this skill and which signals it uses.",
            },
        },
        "required": ["skill_id", "run_py", "skill_md", "rationale"],
    },
}


@dataclass
class GenerationResult:
    accepted: bool
    skill_id: str | None = None
    proposal_id: str | None = None
    lineage_id: str | None = None
    rejection_reasons: list[str] | None = None
    rationale: str | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)


def refresh_signal_catalog(db: Connection) -> None:
    with db.cursor() as cur:
        cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY signal_catalog")
    db.commit()


def skill_id_exists(db: Connection, skill_id: str) -> bool:
    with db.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM skill_lineage WHERE skill_id = %s LIMIT 1",
            (skill_id,),
        )
        if cur.fetchone():
            return True
        cur.execute(
            "SELECT 1 FROM forecasts WHERE skill_id = %s LIMIT 1",
            (skill_id,),
        )
        return cur.fetchone() is not None


def build_generator_prompt(
    disaster_class: str,
    inventory: set[tuple[str, str]],
    uncovered: list[tuple[str, str]],
    *,
    operator_seed: str = "",
) -> str:
    inv_lines = sorted(f"  {src} / {st}" for src, st in inventory)
    uncovered_lines = sorted(f"  {src} / {st}" for src, st in uncovered)
    cadence = 30 if disaster_class == "wildfire" else 180
    seed_block = f"\n## Operator seed\n{operator_seed}\n" if operator_seed else ""
    return f"""Disaster class: `{disaster_class}`
Required constants in run_py:
  DISASTER_CLASS = "{disaster_class}"
  SKILL_CADENCE_MINUTES = {cadence}

{RETURN_CONTRACT}
{seed_block}
## Uncovered signal types (prioritize these)
{chr(10).join(uncovered_lines) if uncovered_lines else "  (none)"}

## Full signal inventory
{chr(10).join(inv_lines[:80])}
"""


def call_generator_llm(
    db: Connection,
    user_prompt: str,
    *,
    budget: BudgetTracker | None = None,
) -> tuple[str, str, str, str, object, str]:
    prefer_haiku = budget.should_use_haiku() if budget else False
    primary = HAIKU_MODEL if prefer_haiku else SONNET_MODEL
    fallback = SONNET_MODEL if prefer_haiku else HAIKU_MODEL
    if prefer_haiku and budget:
        budget.note_haiku_fallback()

    response, model_used = call_messages(
        call_site="generator",
        db=db,
        messages=[{"role": "user", "content": user_prompt}],
        model=primary,
        fallback_model=fallback,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[GENERATION_TOOL],
        tool_choice={"type": "tool", "name": "propose_new_skill"},
        budget=budget,
    )
    tool_block = next(
        (b for b in response.content if b.type == "tool_use"), None
    )
    if tool_block is None:
        raise RuntimeError("no tool_use block in response")
    inp = tool_block.input
    return (
        inp["skill_id"],
        inp["run_py"],
        inp["skill_md"],
        inp["rationale"],
        response,
        model_used,
    )


def persist_generated(
    db: Connection,
    skill_id: str,
    run_py: str,
    skill_md: str,
    app_py: str,
    rationale: str,
    curator_trace: dict,
    now: datetime,
) -> tuple[str, str]:
    proposal_id = str(uuid.uuid4())
    lineage_id = str(uuid.uuid4())
    full_md = skill_md.rstrip() + f"\n\n<!-- ENVISION_APP_PY\n{app_py}\n-->\n"
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO skill_edit_proposals (
              id, proposed_at, skill_id, current_version,
              proposed_code, curator_reasoning, status, curator_trace
            ) VALUES (
              %s, %s, %s, 0, %s, %s, 'pending', %s::jsonb
            )
            """,
            (
                proposal_id,
                now,
                skill_id,
                run_py,
                rationale,
                json.dumps(curator_trace),
            ),
        )
        cur.execute(
            """
            INSERT INTO skill_lineage (
              id, skill_id, parent_skill_id, version,
              source_code, skill_md, generation_method,
              status, proposal_id
            ) VALUES (
              %s, %s, NULL, NULL, %s, %s, 'generated', 'candidate', %s
            )
            """,
            (lineage_id, skill_id, run_py, full_md, proposal_id),
        )
        cur.execute(
            """
            UPDATE skill_edit_proposals SET lineage_id = %s WHERE id = %s
            """,
            (lineage_id, proposal_id),
        )
    db.commit()
    return proposal_id, lineage_id


def generate_skill(
    db: Connection,
    now: datetime,
    *,
    disaster_class: str,
    uncovered: list[tuple[str, str]],
    budget: BudgetTracker | None = None,
) -> GenerationResult:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return GenerationResult(
            accepted=False,
            rejection_reasons=["ANTHROPIC_API_KEY not set"],
        )

    try:
        refresh_signal_catalog(db)
    except Exception as exc:  # noqa: BLE001
        return GenerationResult(
            accepted=False,
            rejection_reasons=[f"signal_catalog refresh failed: {exc}"],
        )

    inventory = load_signal_inventory(db)
    if not inventory:
        return GenerationResult(
            accepted=False,
            rejection_reasons=["signal_catalog empty after refresh"],
        )

    ctb = CuratorTraceBuilder()
    ctb.set_brier_stats({"generator": {"disaster_class": disaster_class}})

    attempt_records: list[dict[str, Any]] = []
    feedback: list[str] | None = None
    report: ValidationReport | None = None
    skill_id = ""
    run_py = ""
    skill_md = ""
    rationale = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if budget is not None and not budget.can_afford_next_call():
            return GenerationResult(
                accepted=False,
                rejection_reasons=["evolution pass budget exhausted"],
                attempts=attempt_records,
            )

        user_prompt = build_generator_prompt(
            disaster_class,
            inventory,
            uncovered,
            operator_seed=seed_prompt(),
        )
        if feedback:
            user_prompt += "\n## Previous attempt rejected\n" + "\n".join(
                f"- {r}" for r in feedback
            )

        try:
            skill_id, run_py, skill_md, rationale, _resp, model_used = (
                call_generator_llm(db, user_prompt, budget=budget)
            )
            ctb.set_llm_model(model_used)
        except Exception as exc:  # noqa: BLE001
            attempt_records.append({
                "n": attempt,
                "rejection_reasons": [f"llm_error: {exc}"],
                "accepted": False,
            })
            return GenerationResult(
                accepted=False,
                rejection_reasons=[f"llm_error: {exc}"],
                attempts=attempt_records,
            )

        if skill_id_exists(db, skill_id):
            feedback = [f"skill_id {skill_id!r} already exists"]
            attempt_records.append({
                "n": attempt,
                "rejection_reasons": feedback,
                "accepted": False,
            })
            continue

        surface = normalize_mutation_surface(run_py)
        report = validate_generated_candidate(
            surface,
            skill_id,
            inventory,
            db,
            now,
            disaster_class=disaster_class,
        )
        attempt_records.append({
            "n": attempt,
            "rejection_reasons": list(report.rejection_reasons),
            "accepted": report.accepted,
        })
        if report.accepted:
            run_py = surface
            break
        feedback = list(report.rejection_reasons)
        print(
            f"[generator] attempt {attempt}/{MAX_ATTEMPTS} rejected — {feedback}",
            file=sys.stderr,
        )

    ctb.set_rationale(rationale)
    ctb.set_mutation_attempts(attempt_records)
    if report is not None:
        ctb.set_validation_stages(report.stages)

    if report is None or not report.accepted:
        return GenerationResult(
            accepted=False,
            skill_id=skill_id or None,
            rejection_reasons=report.rejection_reasons if report else ["no attempts"],
            rationale=rationale,
            attempts=attempt_records,
        )

    cadence_minutes = parse_cadence_minutes(run_py, skill_id)
    folder = skill_id_to_folder(skill_id)
    app_py = render_app_py(folder_name=folder, cadence_minutes=cadence_minutes)

    proposal_id, lineage_id = persist_generated(
        db,
        skill_id,
        run_py,
        skill_md,
        app_py,
        rationale,
        ctb.build(),
        now,
    )
    print(
        f"[generator] accepted {skill_id} proposal={proposal_id[:8]} "
        f"lineage={lineage_id[:8]}"
    )
    return GenerationResult(
        accepted=True,
        skill_id=skill_id,
        proposal_id=proposal_id,
        lineage_id=lineage_id,
        rationale=rationale,
        attempts=attempt_records,
    )
