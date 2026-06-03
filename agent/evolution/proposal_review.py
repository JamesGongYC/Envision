"""Operator review helpers for skill_edit_proposals + shadow lineage."""
from __future__ import annotations

import difflib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from psycopg import Connection

from agent.evolution.mutator import load_parent_surface
from agent.evolution.promotion import (
    MIN_SHADOW_EVALS,
    modal_deploy_command,
    write_promoted_run_py,
)
from agent.evolution.selector import NOISE_FLOOR
from agent.evolution.shadow_stats import fetch_shadow_brier_by_lineage

PROMOTE_CONFIRM = "PROMOTE ANYWAY"


@dataclass
class ProposalRow:
    proposal_id: str
    skill_id: str
    current_version: int
    status: str
    proposed_at: datetime
    lineage_id: str | None
    lineage_status: str | None
    source_code: str | None
    curator_reasoning: str | None
    curator_trace: dict | None


def _resolve_proposal(cur, prefix: str) -> tuple | None:
    cur.execute(
        """
        SELECT p.id, p.skill_id, p.current_version, p.status, p.proposed_at,
               p.curator_reasoning, p.curator_trace, p.lineage_id,
               l.status, l.source_code
        FROM skill_edit_proposals p
        LEFT JOIN skill_lineage l ON l.id = p.lineage_id
        WHERE p.id::text LIKE %s
        ORDER BY p.proposed_at DESC
        """,
        (prefix + "%",),
    )
    rows = cur.fetchall()
    if len(rows) != 1:
        return None
    return rows[0]


def fetch_proposal(db: Connection, proposal_id_prefix: str) -> ProposalRow | None:
    with db.cursor() as cur:
        row = _resolve_proposal(cur, proposal_id_prefix)
    if not row:
        return None
    trace = row[6]
    if isinstance(trace, str):
        trace = json.loads(trace)
    return ProposalRow(
        proposal_id=str(row[0]),
        skill_id=row[1],
        current_version=int(row[2]),
        status=row[3],
        proposed_at=row[4],
        curator_reasoning=row[5],
        curator_trace=trace if isinstance(trace, dict) else None,
        lineage_id=str(row[7]) if row[7] else None,
        lineage_status=row[8],
        source_code=row[9],
    )


def parent_live_brier_14d(db: Connection, skill_id: str) -> float | None:
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT AVG(e.brier_contribution)::float
            FROM evaluations e
            JOIN forecasts f ON f.id = e.forecast_id
            WHERE f.skill_id = %s
              AND e.evaluated_at >= now() - interval '14 days'
            """,
            (skill_id,),
        )
        row = cur.fetchone()
    return float(row[0]) if row and row[0] is not None else None


def shadow_metrics(
    db: Connection, lineage_id: str | None
) -> tuple[float | None, int]:
    if not lineage_id:
        return None, 0
    for lid, brier, n in fetch_shadow_brier_by_lineage(db):
        if str(lid) == lineage_id:
            return brier, int(n)
    return None, 0


def backtest_summary(db: Connection, lineage_id: str | None) -> list[tuple]:
    if not lineage_id:
        return []
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT window_start, window_end, brier_score, forecasts_emitted
            FROM backtest_run
            WHERE lineage_id = %s
            ORDER BY window_start
            """,
            (lineage_id,),
        )
        return cur.fetchall()


def blocked_on(db: Connection, proposal: ProposalRow) -> list[str]:
    reasons: list[str] = []
    if proposal.status != "pending":
        reasons.append(f"proposal status={proposal.status}")
    if proposal.lineage_status == "candidate":
        reasons.append("not in shadow (selector pending/refused)")
    elif proposal.lineage_status not in ("shadow", "candidate"):
        reasons.append(f"lineage status={proposal.lineage_status}")

    bt = backtest_summary(db, proposal.lineage_id)
    if proposal.lineage_status == "candidate" and not bt:
        reasons.append("windows: insufficient ground truth")

    shadow_brier, n_evals = shadow_metrics(db, proposal.lineage_id)
    if proposal.lineage_status == "shadow":
        if n_evals < MIN_SHADOW_EVALS:
            reasons.append(f"evals {n_evals}/{MIN_SHADOW_EVALS}")
        parent_brier = parent_live_brier_14d(db, proposal.skill_id)
        if shadow_brier is not None and parent_brier is not None:
            if shadow_brier > parent_brier - NOISE_FLOOR:
                reasons.append(
                    f"shadow brier {shadow_brier:.3f} vs parent {parent_brier:.3f} "
                    f"(need −{NOISE_FLOOR})"
                )
        elif n_evals >= MIN_SHADOW_EVALS:
            reasons.append("shadow or parent brier unavailable")

    if os.environ.get("ENVISION_HARNESS_SANITY") == "fail":
        reasons.append("backtest pending harness")

    return reasons


def source_diff(
    db: Connection,
    proposal: ProposalRow,
) -> str:
    parent_surface, _ = load_parent_surface(db, proposal.skill_id)
    candidate = proposal.source_code or ""
    lines = difflib.unified_diff(
        parent_surface.splitlines(keepends=True),
        candidate.splitlines(keepends=True),
        fromfile="parent",
        tofile="candidate",
        lineterm="",
    )
    return "".join(lines) or "(no diff)"


def list_proposals(
    db: Connection,
    *,
    status: str = "pending",
) -> list[dict[str, Any]]:
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT p.id, p.skill_id, p.current_version, p.status, p.proposed_at,
                   p.lineage_id, l.status, p.curator_reasoning
            FROM skill_edit_proposals p
            LEFT JOIN skill_lineage l ON l.id = p.lineage_id
            WHERE p.status = %s
            ORDER BY p.proposed_at DESC
            LIMIT 50
            """,
            (status,),
        )
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        prop = ProposalRow(
            proposal_id=str(row[0]),
            skill_id=row[1],
            current_version=int(row[2]),
            status=row[3],
            proposed_at=row[4],
            lineage_id=str(row[5]) if row[5] else None,
            lineage_status=row[6],
            source_code=None,
            curator_reasoning=row[7],
            curator_trace=None,
        )
        shadow_brier, n_evals = shadow_metrics(db, prop.lineage_id)
        parent_brier = parent_live_brier_14d(db, prop.skill_id)
        bt = backtest_summary(db, prop.lineage_id)
        mean_bt = (
            sum(r[2] for r in bt if r[2] is not None) / len(bt) if bt else None
        )
        out.append({
            "proposal_id": prop.proposal_id,
            "skill_id": prop.skill_id,
            "version": prop.current_version,
            "status": prop.status,
            "lineage_status": prop.lineage_status,
            "proposed_at": prop.proposed_at,
            "backtest_mean_brier": mean_bt,
            "backtest_windows": len(bt),
            "parent_live_brier_14d": parent_brier,
            "shadow_brier": shadow_brier,
            "shadow_n_evals": n_evals,
            "blocked_on": blocked_on(db, prop),
        })
    return out


def promote_proposal(
    db: Connection,
    proposal_id_prefix: str,
    *,
    force: bool = False,
    force_confirm: str | None = None,
    repo_root: Any = None,
) -> tuple[bool, str]:
    proposal = fetch_proposal(db, proposal_id_prefix)
    if not proposal:
        return False, "proposal not found or ambiguous id prefix"

    blockers = blocked_on(db, proposal)
    if blockers and not force:
        return False, "promotion refused: " + "; ".join(blockers)
    if force and force_confirm != PROMOTE_CONFIRM:
        return False, f"--force requires typing {PROMOTE_CONFIRM!r}"

    if proposal.lineage_status != "shadow" and not force:
        return False, "lineage must be in shadow status"

    new_version = proposal.current_version + 1
    now = datetime.now(timezone.utc)

    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE skill_lineage
            SET status = 'promoted', version = %s
            WHERE id = %s
            """,
            (new_version, proposal.lineage_id),
        )
        cur.execute(
            """
            UPDATE skill_edit_proposals
            SET status = 'approved', reviewed_at = %s
            WHERE id = %s
            """,
            (now, proposal.proposal_id),
        )
        cur.execute(
            """
            UPDATE forecasts_shadow
            SET shadow_promotion_status = 'promoted'
            WHERE lineage_id = %s AND shadow_promotion_status = 'evaluating'
            """,
            (proposal.lineage_id,),
        )
    db.commit()

    path = write_promoted_run_py(
        proposal.skill_id,
        proposal.source_code or "",
        new_version,
        repo_root=repo_root,
    )
    deploy = modal_deploy_command(proposal.skill_id)
    msg = (
        f"Promoted {proposal.skill_id} v{new_version}.\n"
        f"  Wrote: {path}\n"
        f"  Deploy manually: {deploy}"
    )
    return True, msg


def discard_proposal(db: Connection, proposal_id_prefix: str) -> tuple[bool, str]:
    proposal = fetch_proposal(db, proposal_id_prefix)
    if not proposal:
        return False, "proposal not found or ambiguous id prefix"
    if proposal.status != "pending":
        return False, f"proposal status is {proposal.status}, not pending"

    now = datetime.now(timezone.utc)
    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE skill_edit_proposals
            SET status = 'rejected', reviewed_at = %s
            WHERE id = %s
            """,
            (now, proposal.proposal_id),
        )
        if proposal.lineage_id:
            cur.execute(
                """
                UPDATE skill_lineage SET status = 'archived'
                WHERE id = %s
                """,
                (proposal.lineage_id,),
            )
            cur.execute(
                """
                UPDATE forecasts_shadow
                SET shadow_promotion_status = 'discarded'
                WHERE lineage_id = %s AND shadow_promotion_status = 'evaluating'
                """,
                (proposal.lineage_id,),
            )
    db.commit()
    return True, f"Discarded proposal {proposal.proposal_id[:8]}"
