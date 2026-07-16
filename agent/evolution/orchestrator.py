"""Daily evolution pass: generator (gated) → critic → select → shadow."""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import Connection

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_LIB = REPO_ROOT / "agent" / "lib"
for p in (str(REPO_ROOT), str(AGENT_LIB)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent.evolution.budget import PASS_BUDGET_USD, BudgetTracker  # noqa: E402
from agent.evolution.generation_trigger import should_run_generator  # noqa: E402
from agent.evolution.generator import generate_skill  # noqa: E402
from agent.evolution.selector import select_candidates  # noqa: E402
from agent.evolution.skill_loader import SKILL_FOLDERS  # noqa: E402
from agent.lib.health_gate import should_abort_cycle  # noqa: E402
from agent.lib.repo_env import load_repo_env  # noqa: E402
from agents.critic.loop import run_critic_loop  # noqa: E402

SKILL_ID = "curator"
WORST_K = 3
MIN_EVALUATIONS_TO_CONSIDER = 5


@dataclass
class PassSummary:
    targeted: list[str] = field(default_factory=list)
    mutated: int = 0
    accepted: int = 0
    selected_to_shadow: list[str] = field(default_factory=list)
    skipped: int = 0
    budget: dict = field(default_factory=dict)
    generator_note: str | None = None

    def as_dict(self) -> dict:
        return {
            "targeted": self.targeted,
            "mutated": self.mutated,
            "accepted": self.accepted,
            "selected_to_shadow": self.selected_to_shadow,
            "skipped": self.skipped,
            "budget": self.budget,
            "generator_note": self.generator_note,
        }


def has_pending_proposal(db: Connection, skill_id: str) -> bool:
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM skill_edit_proposals
            WHERE skill_id = %s AND status = 'pending'
            LIMIT 1
            """,
            (skill_id,),
        )
        return cur.fetchone() is not None


def pick_worst_k_skills(
    db: Connection,
    now: datetime,
    k: int = WORST_K,
) -> list[str]:
    """Rank detection skills by 14d live Brier; tie-break by version spread."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT
              f.skill_id,
              f.skill_version,
              COUNT(*)::int AS n_evals,
              AVG(e.brier_contribution)::float AS mean_brier
            FROM evaluations e
            JOIN forecasts f ON f.id = e.forecast_id
            WHERE e.evaluated_at > %s - interval '14 days'
              AND f.skill_id = ANY(%s)
            GROUP BY f.skill_id, f.skill_version
            """,
            (now, list(SKILL_FOLDERS.keys())),
        )
        rows = cur.fetchall()

    if not rows:
        return []

    by_skill: dict[str, list[tuple[int, int, float]]] = {}
    for skill_id, version, n_evals, mean_brier in rows:
        by_skill.setdefault(skill_id, []).append(
            (int(version), int(n_evals), float(mean_brier))
        )

    ranked: list[tuple[float, float, str]] = []
    for skill_id, versions in by_skill.items():
        if has_pending_proposal(db, skill_id):
            continue
        current = max(versions, key=lambda x: x[0])
        cur_ver, n_evals, cur_brier = current
        if n_evals < MIN_EVALUATIONS_TO_CONSIDER:
            continue
        hist_briers = [b for v, n, b in versions if v != cur_ver and n >= 1]
        min_hist = min(hist_briers) if hist_briers else cur_brier
        spread = cur_brier - min_hist
        ranked.append((cur_brier, spread, skill_id))

    ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [skill_id for _, _, skill_id in ranked[:k]]


def run_evolution_pass(
    db: Connection,
    now: datetime,
    *,
    budget: BudgetTracker | None = None,
    curator_enabled: bool = True,
) -> PassSummary:
    summary = PassSummary()
    tracker = budget or BudgetTracker()

    if should_abort_cycle(db):
        summary.generator_note = "health gate: rolling 529 rate tripped; aborting cycle"
        print(f"[{SKILL_ID}] {summary.generator_note}")
        summary.budget = tracker.summary()
        return summary

    run_gen, dclass, uncovered = should_run_generator(db)
    if run_gen and dclass:
        print(
            f"[{SKILL_ID}] generator triggered for {dclass} "
            f"({len(uncovered)} uncovered signal types)"
        )
        if should_abort_cycle(db):
            summary.generator_note = "health gate tripped before generator"
            print(f"[{SKILL_ID}] {summary.generator_note}")
        else:
            gen = generate_skill(
                db,
                now,
                disaster_class=dclass,
                uncovered=uncovered,
                budget=tracker,
            )
            if gen.accepted and gen.proposal_id:
                summary.generator_note = (
                    f"generated {gen.skill_id} proposal={gen.proposal_id[:8]}"
                )
            else:
                summary.generator_note = (
                    f"generator rejected: {gen.rejection_reasons}"
                )
            print(f"[{SKILL_ID}] {summary.generator_note}")

    if curator_enabled:
        print(f"[{SKILL_ID}] running critic loop (scheduled)")
        critic = run_critic_loop(
            now,
            db,
            trigger="scheduled",
            budget=tracker,
        )
        summary.targeted = list(critic.proposal_ids)
        summary.mutated = 1 if critic.status == "completed" else 0
        summary.accepted = len(critic.proposal_ids)
        if critic.status == "gated":
            summary.skipped += 1
            print(f"[{SKILL_ID}] critic gated: {critic.error}")
        elif critic.proposal_ids:
            print(
                f"[{SKILL_ID}] critic proposals: {critic.proposal_ids} "
                f"(status={critic.status})"
            )
        else:
            print(
                f"[{SKILL_ID}] critic finished with no proposals "
                f"(status={critic.status}, error={critic.error})"
            )
    else:
        print(f"[{SKILL_ID}] curator mutation disabled; skipping critic pass")

    sel = select_candidates(db, dry_run=False)
    summary.selected_to_shadow = sel.selected_lineage_ids
    summary.budget = tracker.summary()

    print(
        f"[{SKILL_ID}] pass complete: targeted={len(summary.targeted)} "
        f"mutated={summary.mutated} accepted={summary.accepted} "
        f"shadow={len(summary.selected_to_shadow)} "
        f"spend=${summary.budget.get('spend_usd', 0):.2f}/{PASS_BUDGET_USD}"
    )
    return summary


def main() -> int:
    load_repo_env()
    now = datetime.now(timezone.utc)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL required", file=sys.stderr)
        return 2
    with psycopg.connect(url, autocommit=False) as db:
        run_evolution_pass(db, now)
    return 0


if __name__ == "__main__":
    sys.exit(main())
