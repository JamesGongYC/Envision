"""Critic agent tools — orchestration only; mutator/generator unchanged."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Connection

from agent.evolution.generation_trigger import (
    find_uncovered_signals,
    is_generator_seeded,
    seed_prompt,
    seeded_disaster_class,
    should_run_generator,
)
from agent.evolution.generator import generate_skill as evolution_generate_skill
from agent.evolution.mutator import mutate_skill as evolution_mutate_skill
from agents.forecaster.tools import list_skills as shared_list_skills

# Re-export for callers / tests
list_skills = shared_list_skills

RAW_PRODUCER_FILTER = "rule"


def inspect_forecasts(db: Connection, skill_id: str) -> dict[str, Any]:
    """Raw per-skill forecasts (producer='rule') + GT matches + Brier + override."""
    skills = {s["skill_id"]: s for s in list_skills(db)}
    meta = skills.get(skill_id, {})

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT
              f.id,
              f.issued_at,
              f.valid_from,
              f.valid_until,
              f.disaster_class,
              f.probability,
              f.skill_version,
              f.producer,
              e.outcome,
              e.brier_contribution,
              e.matched_ground_truth_id,
              gt.occurred_at AS gt_occurred_at
            FROM forecasts f
            LEFT JOIN evaluations e ON e.forecast_id = f.id
            LEFT JOIN ground_truth gt ON gt.id = e.matched_ground_truth_id
            WHERE f.skill_id = %s
              AND f.producer = %s
              AND f.issued_at > now() - interval '14 days'
            ORDER BY f.issued_at DESC
            LIMIT 40
            """,
            (skill_id, RAW_PRODUCER_FILTER),
        )
        rows = cur.fetchall()

    forecasts: list[dict[str, Any]] = []
    for r in rows:
        forecasts.append(
            {
                "id": str(r[0]),
                "issued_at": r[1].isoformat() if r[1] else None,
                "valid_from": r[2].isoformat() if r[2] else None,
                "valid_until": r[3].isoformat() if r[3] else None,
                "disaster_class": r[4],
                "probability": float(r[5]) if r[5] is not None else None,
                "skill_version": int(r[6]) if r[6] is not None else None,
                "producer": r[7],
                "outcome": r[8],
                "brier_contribution": float(r[9]) if r[9] is not None else None,
                "matched_ground_truth_id": str(r[10]) if r[10] else None,
                "gt_occurred_at": r[11].isoformat() if r[11] else None,
            }
        )

    return {
        "skill_id": skill_id,
        "producer_filter": RAW_PRODUCER_FILTER,
        "mean_brier": meta.get("mean_brier"),
        "hit_rate": meta.get("hit_rate"),
        "n_evaluations": meta.get("n_evaluations", 0),
        "override_frequency": meta.get("override_frequency", 0.0),
        "summary": meta.get("summary", ""),
        "forecasts": forecasts,
        "count": len(forecasts),
    }


def tool_mutate_skill(
    db: Connection,
    *,
    skill_id: str,
    now: datetime,
    budget: Any = None,
) -> dict[str, Any]:
    result = evolution_mutate_skill(skill_id, db, now=now, budget=budget)
    return {
        "accepted": result.accepted,
        "proposal_id": result.proposal_id,
        "lineage_id": result.lineage_id,
        "rejection_reasons": result.rejection_reasons,
        "rationale": result.rationale,
        "terminal": True,
    }


def tool_generate_skill(
    db: Connection,
    *,
    now: datetime,
    disaster_class: str,
    seed: str = "",
    budget: Any = None,
) -> dict[str, Any]:
    """Refuse unless operator/condition gate is satisfied (no daily spray)."""
    if not is_generator_seeded():
        return {
            "refused": True,
            "reason": "generator not seeded (ENVISION_GENERATOR_ENABLED)",
            "terminal": False,
        }
    run_ok, dclass, uncovered = should_run_generator(db)
    if not run_ok:
        return {
            "refused": True,
            "reason": "generator condition gate not satisfied",
            "terminal": False,
        }
    cls = (disaster_class or dclass or seeded_disaster_class() or "").strip().lower()
    if cls not in ("wildfire", "typhoon"):
        return {
            "refused": True,
            "reason": f"invalid disaster_class {disaster_class!r}",
            "terminal": False,
        }
    if not uncovered:
        uncovered = find_uncovered_signals(db, cls)
    # Seed prompt is env-driven; tool seed is advisory note only.
    _ = seed or seed_prompt()
    result = evolution_generate_skill(
        db,
        now,
        disaster_class=cls,
        uncovered=uncovered,
        budget=budget,
    )
    return {
        "refused": False,
        "accepted": result.accepted,
        "skill_id": result.skill_id,
        "proposal_id": result.proposal_id,
        "lineage_id": result.lineage_id,
        "rejection_reasons": result.rejection_reasons,
        "rationale": result.rationale,
        "terminal": True,
    }


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "list_skills",
        "description": (
            "List detection skills with summaries, Brier, hit_rate, override_frequency."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "inspect_forecasts",
        "description": (
            "Inspect RAW per-skill forecasts (producer=rule scoring stream) plus "
            "evaluation outcomes, Brier, and override_frequency. Not agent-curated rows."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"skill_id": {"type": "string"}},
            "required": ["skill_id"],
        },
    },
    {
        "name": "mutate_skill",
        "description": (
            "TERMINAL targeting. Invoke the existing mutator on skill_id. "
            "Returns proposal id; does not promote."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"skill_id": {"type": "string"}},
            "required": ["skill_id"],
        },
    },
    {
        "name": "generate_skill",
        "description": (
            "TERMINAL targeting when generator is operator-seeded. "
            "Refused on a plain daily tick without the condition gate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "disaster_class": {
                    "type": "string",
                    "enum": ["wildfire", "typhoon"],
                },
                "seed": {"type": "string"},
            },
            "required": ["disaster_class"],
        },
    },
]


def dispatch_tool(
    name: str,
    tool_input: dict,
    *,
    db: Connection,
    now: datetime,
    budget: Any = None,
) -> tuple[Any, bool]:
    """
    Dispatch a critic tool.
    Returns (observation, is_terminal).
    """
    if name == "list_skills":
        return list_skills(db), False
    if name == "inspect_forecasts":
        skill_id = str(tool_input.get("skill_id") or "")
        return inspect_forecasts(db, skill_id), False
    if name == "mutate_skill":
        skill_id = str(tool_input.get("skill_id") or "")
        out = tool_mutate_skill(db, skill_id=skill_id, now=now, budget=budget)
        return out, True
    if name == "generate_skill":
        out = tool_generate_skill(
            db,
            now=now,
            disaster_class=str(tool_input.get("disaster_class") or ""),
            seed=str(tool_input.get("seed") or ""),
            budget=budget,
        )
        return out, bool(out.get("terminal"))
    raise ValueError(f"unknown tool {name!r}")
