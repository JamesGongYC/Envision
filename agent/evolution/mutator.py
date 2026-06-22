#!/usr/bin/env python3
"""v3 mutator: LLM rewrite + validation → skill_edit_proposals + skill_lineage."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg import Connection

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_LIB = REPO_ROOT / "agent" / "lib"
for p in (str(REPO_ROOT), str(AGENT_LIB)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent.evolution.budget import BudgetTracker  # noqa: E402
from agent.evolution.skill_loader import SKILL_FOLDERS  # noqa: E402
from agent.evolution.skill_surface import (  # noqa: E402
    assert_parent_surface_clean,
    extract_mutation_surface,
    load_parent_surface_from_disk,
    normalize_mutation_surface,
)
from agent.evolution.skill_validator import ValidationReport, validate_candidate  # noqa: E402
from agent.lib.llm_client import DEFAULT_HAIKU, call_messages  # noqa: E402
from agent.lib.repo_env import load_repo_env  # noqa: E402
from trace_builder import CuratorTraceBuilder  # noqa: E402

SONNET_MODEL = os.environ.get("ENVISION_MUTATOR_MODEL", "claude-sonnet-4-6")
HAIKU_MODEL = os.environ.get("ENVISION_MUTATOR_FALLBACK_MODEL", DEFAULT_HAIKU)
MAX_TOKENS = 16384
MAX_ATTEMPTS = 3

RETURN_CONTRACT = """Your function computes and returns `list[Forecast]`. It ends with
`return forecasts` (or `return out` / equivalent). Persistence is handled entirely by
the caller — your code never imports or calls the writer and never executes
INSERT/UPDATE/DELETE. Any database write will be rejected."""

SYSTEM_PROMPT = f"""You are the Envision skill mutator. Rewrite a detection skill surface
(pure Python module) to lower backtest Brier based on trajectory and failure traces.

{RETURN_CONTRACT}

Additional rules:
- Keep exactly: def run(now: datetime, db: Connection) -> list[Forecast]
- Rewrite the mutation surface only — no CLI main(), no emit_forecasts, no app entrypoint.
- Do not use `from __future__ import annotations` or any __future__ imports.
- Only query source/signal_type pairs from the supplied signal inventory — use those
  exact literal strings in SQL (e.g. source = 'nws_alerts'). Never placeholders like
  {{source_filter}}, %s in SQL string literals, or invented source names.
- Reasoning may use generate_reasoning() with fallback; never require LLM to emit.
- You may change thresholds, clustering params, buffers, probability maps, signal filters.

Submit the complete mutation surface via propose_skill_mutation."""

MUTATION_TOOL = {
    "name": "propose_skill_mutation",
    "description": "Submit a full rewritten detection skill mutation surface.",
    "input_schema": {
        "type": "object",
        "properties": {
            "mutated_source": {
                "type": "string",
                "description": "Complete Python source for the mutation surface.",
            },
            "rationale": {
                "type": "string",
                "description": "What changed and why, grounded in trajectory and traces.",
            },
            "targets": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags for what changed (e.g. dbscan_eps).",
            },
        },
        "required": ["mutated_source", "rationale"],
    },
}

LlmFn = Callable[[str], tuple[str, str, list[str], Any, str]]


def _validate_candidate(
    mutated_surface: str,
    parent_surface: str,
    skill_id: str,
    inventory: set[tuple[str, str]],
    db: Connection,
    now: datetime,
    db_url: str | None,
) -> tuple[ValidationReport, Connection]:
    """Validate candidate; reconnect once on transient Neon/SSL drops."""
    surface = normalize_mutation_surface(mutated_surface)
    try:
        return (
            validate_candidate(
                surface, parent_surface, skill_id, inventory, db, now
            ),
            db,
        )
    except psycopg.OperationalError:
        if not db_url:
            raise
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass
        fresh = psycopg.connect(db_url, autocommit=False)
        return (
            validate_candidate(
                surface, parent_surface, skill_id, inventory, fresh, now
            ),
            fresh,
        )


@dataclass
class MutationResult:
    accepted: bool
    proposal_id: str | None = None
    lineage_id: str | None = None
    rejection_reasons: list[str] | None = None
    rationale: str | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)


def load_parent_surface(db: Connection, skill_id: str) -> tuple[str, int]:
    """Surface-only parent from lineage (promoted) or disk run.py."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT source_code, version
            FROM skill_lineage
            WHERE skill_id = %s AND status = 'promoted'
            ORDER BY version DESC NULLS LAST
            LIMIT 1
            """,
            (skill_id,),
        )
        row = cur.fetchone()
    if row:
        surface = normalize_mutation_surface(extract_mutation_surface(row[0]))
        version = int(row[1])
    else:
        surface, version = load_parent_surface_from_disk(skill_id)
    assert_parent_surface_clean(surface)
    return surface, version


def load_brier_trajectory(
    db: Connection, skill_id: str, now: datetime
) -> list[tuple]:
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT f.skill_version,
                   AVG(e.brier_contribution)::float AS mean_brier,
                   COUNT(*)::int AS n_evals
            FROM evaluations e
            JOIN forecasts f ON f.id = e.forecast_id
            WHERE f.skill_id = %s
              AND e.evaluated_at >= %s - interval '14 days'
            GROUP BY f.skill_version
            ORDER BY f.skill_version
            """,
            (skill_id, now),
        )
        return cur.fetchall()


def load_worst_traces(
    db: Connection, skill_id: str, now: datetime, limit: int = 3
) -> list[tuple]:
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT f.id, e.outcome, e.brier_contribution, f.probability, f.trace
            FROM evaluations e
            JOIN forecasts f ON f.id = e.forecast_id
            WHERE f.skill_id = %s
              AND e.evaluated_at >= %s - interval '14 days'
            ORDER BY e.brier_contribution DESC
            LIMIT %s
            """,
            (skill_id, now, limit),
        )
        return cur.fetchall()


def load_signal_inventory(db: Connection) -> set[tuple[str, str]]:
    with db.cursor() as cur:
        cur.execute(
            "SELECT source, signal_type FROM signal_catalog ORDER BY 1, 2"
        )
        return {(r[0], r[1]) for r in cur.fetchall()}


def _trim_trace(trace: Any, max_chars: int = 4000) -> Any:
    if isinstance(trace, dict):
        s = json.dumps(trace, default=str)
        if len(s) > max_chars:
            return {"_truncated": s[:max_chars]}
        return trace
    if isinstance(trace, str):
        if len(trace) > max_chars:
            return trace[:max_chars] + "..."
        try:
            return json.loads(trace)
        except json.JSONDecodeError:
            return trace
    return trace


def build_user_prompt(
    skill_id: str,
    parent_surface: str,
    trajectory: list[tuple],
    worst_traces: list[tuple],
    inventory: set[tuple[str, str]],
    *,
    feedback: list[str] | None = None,
) -> str:
    traj_lines = [
        f"  v{row[0]}: mean_brier={row[1]:.4f} n={row[2]}"
        for row in trajectory
    ] or ["  (no evaluations in last 14d)"]

    trace_blocks = []
    for fid, outcome, brier, prob, trace in worst_traces:
        trace_blocks.append(
            f"- forecast {fid}: outcome={outcome} brier={brier:.4f} p={prob}\n"
            f"  trace: {json.dumps(_trim_trace(trace), default=str)[:3500]}"
        )

    inv_lines = sorted(f"  {src} / {st}" for src, st in inventory)

    feedback_block = ""
    if feedback:
        reasons = "\n".join(f"  - {r}" for r in feedback)
        feedback_block = f"""
## Previous attempt rejected
Your previous attempt was rejected for:
{reasons}

Return a corrected mutation surface. Remember:
{RETURN_CONTRACT}
"""

    return f"""Skill: `{skill_id}`

{RETURN_CONTRACT}

{feedback_block}
## 14-day Brier trajectory (by skill_version)
{chr(10).join(traj_lines)}

## Worst 3 evaluations (highest Brier)
{chr(10).join(trace_blocks) if trace_blocks else "  (none)"}

## Signal inventory (only use these source / signal_type values)
{chr(10).join(inv_lines[:80])}

## Parent mutation surface (rewrite this module completely; surface only, no main/CLI)

```python
{parent_surface}
```
"""


def _serialize_response(response) -> str:
    content = getattr(response, "content", None)
    if content is None:
        return str(response)
    parts: list[str] = []
    for block in content:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
        elif getattr(block, "type", None) == "tool_use":
            parts.append(json.dumps(block.input, ensure_ascii=False)[:8000])
    return "\n".join(parts) or str(response)


def call_mutation_llm(
    db: Connection,
    user_prompt: str,
    *,
    prefer_haiku: bool = False,
    budget: BudgetTracker | None = None,
) -> tuple[str, str, list[str], object, str]:
    """Returns (mutated_source, rationale, targets, response, model_used)."""
    primary = HAIKU_MODEL if prefer_haiku else SONNET_MODEL
    fallback = SONNET_MODEL if prefer_haiku else HAIKU_MODEL
    response, model_used = call_messages(
        call_site="mutator",
        db=db,
        messages=[{"role": "user", "content": user_prompt}],
        model=primary,
        fallback_model=fallback,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[MUTATION_TOOL],
        tool_choice={"type": "tool", "name": "propose_skill_mutation"},
        budget=budget,
    )
    tool_block = next(
        (b for b in response.content if b.type == "tool_use"), None
    )
    if tool_block is None:
        raise RuntimeError("no tool_use block in response")
    inp = tool_block.input
    targets = inp.get("targets") or []
    if isinstance(targets, str):
        targets = [targets]
    return (
        inp["mutated_source"],
        inp["rationale"],
        list(targets),
        response,
        model_used,
    )


def persist_accepted(
    db: Connection,
    skill_id: str,
    current_version: int,
    mutated_surface: str,
    rationale: str,
    curator_trace: dict,
    now: datetime,
) -> tuple[str, str]:
    proposal_id = str(uuid.uuid4())
    lineage_id = str(uuid.uuid4())
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO skill_edit_proposals (
              id, proposed_at, skill_id, current_version,
              proposed_code, curator_reasoning, status, curator_trace
            ) VALUES (
              %s, %s, %s, %s, %s, %s, 'pending', %s::jsonb
            )
            """,
            (
                proposal_id,
                now,
                skill_id,
                current_version,
                mutated_surface,
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
              %s, %s, %s, NULL, %s, '', 'mutated', 'candidate', %s
            )
            """,
            (lineage_id, skill_id, skill_id, mutated_surface, proposal_id),
        )
        cur.execute(
            """
            UPDATE skill_edit_proposals
            SET lineage_id = %s
            WHERE id = %s
            """,
            (lineage_id, proposal_id),
        )
    db.commit()
    return proposal_id, lineage_id


def mutate_skill(
    skill_id: str,
    db: Connection,
    *,
    now: datetime | None = None,
    llm_fn: LlmFn | None = None,
    budget: BudgetTracker | None = None,
) -> MutationResult:
    if skill_id not in SKILL_FOLDERS:
        raise KeyError(f"unknown skill_id {skill_id!r}")

    now = now or datetime.now(timezone.utc)
    parent_surface, current_version = load_parent_surface(db, skill_id)
    trajectory = load_brier_trajectory(db, skill_id, now)
    worst_traces = load_worst_traces(db, skill_id, now)
    inventory = load_signal_inventory(db)

    if not inventory:
        return MutationResult(
            accepted=False,
            rejection_reasons=["signal_catalog empty — refresh materialized view"],
        )

    db_url = os.environ.get("DATABASE_URL")
    if llm_fn is None and not os.environ.get("ANTHROPIC_API_KEY"):
        return MutationResult(
            accepted=False,
            rejection_reasons=["ANTHROPIC_API_KEY not set"],
        )

    ctb = CuratorTraceBuilder()
    ctb.set_brier_stats({
        skill_id: {
            "trajectory_14d": [
                {"version": r[0], "mean_brier": r[1], "n_evals": r[2]}
                for r in trajectory
            ],
            "worst_traces_count": len(worst_traces),
        }
    })

    attempt_records: list[dict[str, Any]] = []
    feedback: list[str] | None = None
    rationale = ""
    targets: list[str] = []
    mutated_surface = ""
    response: Any = None
    model_used = ""
    report: ValidationReport | None = None
    first_prompt_hash: str | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if budget is not None and not budget.can_afford_next_call():
            return MutationResult(
                accepted=False,
                rejection_reasons=["evolution pass budget exhausted"],
                attempts=attempt_records,
            )

        user_prompt = build_user_prompt(
            skill_id,
            parent_surface,
            trajectory,
            worst_traces,
            inventory,
            feedback=feedback,
        )
        if attempt == 1:
            first_prompt_hash = hashlib.sha256(user_prompt.encode()).hexdigest()[:16]

        try:
            if llm_fn is not None:
                mutated_surface, rationale, targets, response, model_used = llm_fn(
                    user_prompt
                )
            else:
                prefer_haiku = budget.should_use_haiku() if budget else False
                if prefer_haiku and budget:
                    budget.note_haiku_fallback()
                mutated_surface, rationale, targets, response, model_used = (
                    call_mutation_llm(
                        db,
                        user_prompt,
                        prefer_haiku=prefer_haiku,
                        budget=budget,
                    )
                )
        except Exception as e:  # noqa: BLE001
            attempt_records.append({
                "n": attempt,
                "rejection_reasons": [f"llm_error: {e}"],
                "accepted": False,
            })
            ctb.set_mutation_attempts(attempt_records)
            return MutationResult(
                accepted=False,
                rejection_reasons=[f"llm_error: {e}"],
                attempts=attempt_records,
            )

        report, db = _validate_candidate(
            mutated_surface,
            parent_surface,
            skill_id,
            inventory,
            db,
            now,
            db_url,
        )
        attempt_records.append({
            "n": attempt,
            "rejection_reasons": list(report.rejection_reasons),
            "accepted": report.accepted,
        })

        if report.accepted:
            break
        feedback = list(report.rejection_reasons)
        print(
            f"[mutator] {skill_id}: attempt {attempt}/{MAX_ATTEMPTS} rejected — "
            f"{report.rejection_reasons}",
            file=sys.stderr,
        )

    ctb.set_rationale(rationale)
    ctb.set_mutation_targets(targets)
    ctb.set_mutation_attempts(attempt_records)
    if model_used:
        ctb.set_llm_model(model_used)
    if first_prompt_hash:
        ctb.set_llm_hash(first_prompt_hash)
    if response is not None:
        ctb.set_llm_response(_serialize_response(response))

    assert report is not None
    ctb.set_validation_stages(report.stages)
    for reason in report.rejection_reasons:
        ctb.add_rejection_reason(reason)

    ctb.set_ast_validation(
        passed=report.accepted,
        warnings=[],
        errors=report.rejection_reasons if not report.accepted else [],
    )

    if not report.accepted:
        print(
            f"[mutator] {skill_id}: gave up after {MAX_ATTEMPTS} attempts — "
            f"{report.rejection_reasons}",
            file=sys.stderr,
        )
        return MutationResult(
            accepted=False,
            rejection_reasons=report.rejection_reasons,
            rationale=rationale,
            attempts=attempt_records,
        )

    proposal_id, lineage_id = persist_accepted(
        db,
        skill_id,
        current_version,
        normalize_mutation_surface(mutated_surface),
        rationale,
        ctb.build(),
        now,
    )
    print(
        f"[mutator] {skill_id}: accepted on attempt {attempt_records[-1]['n']} "
        f"proposal={proposal_id[:8]} lineage={lineage_id[:8]}"
    )
    return MutationResult(
        accepted=True,
        proposal_id=proposal_id,
        lineage_id=lineage_id,
        rejection_reasons=[],
        rationale=rationale,
        attempts=attempt_records,
    )


def main() -> int:
    load_repo_env()
    p = argparse.ArgumentParser(description="Run v3 skill mutator")
    p.add_argument("--skill-id", required=True)
    args = p.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL required", file=sys.stderr)
        return 2

    with psycopg.connect(url, autocommit=False) as db:
        result = mutate_skill(args.skill_id, db)
    return 0 if result.accepted else 1


if __name__ == "__main__":
    sys.exit(main())
