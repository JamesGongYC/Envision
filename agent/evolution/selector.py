"""Cross-window backtest selector: advance top-K candidates to shadow status."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg import Connection

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_LIB = REPO_ROOT / "agent" / "lib"
for p in (str(REPO_ROOT), str(AGENT_LIB)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent.evolution.backtest_harness import backtest_skill  # noqa: E402
from agent.evolution.skill_loader import (  # noqa: E402
    load_run_from_source,
    load_skill_run,
)
from agent.evolution.skill_surface import normalize_mutation_surface  # noqa: E402
from agent.lib.repo_env import load_repo_env  # noqa: E402
from agent.lib.scoring import PRE_BUFFER_HOURS, POST_BUFFER_HOURS, class_aliases  # noqa: E402

log = logging.getLogger(__name__)

NOISE_FLOOR = 0.03
TOP_K = 3
MIN_WINDOWS = 3
MIN_GT_EVALS = 10
MIN_FORECASTS_EMITTED = 1

SKILL_DISASTER_CLASS: dict[str, str] = {
    "wildfire_risk_elevated": "wildfire",
    "wildfire_rapid_growth": "wildfire",
    "typhoon_intensifying": "typhoon",
    "typhoon_landfall_imminent": "typhoon",
}


@dataclass
class CandidateRow:
    proposal_id: str
    lineage_id: str
    skill_id: str
    source_code: str
    current_version: int


@dataclass
class SelectionResult:
    selected_lineage_ids: list[str] = field(default_factory=list)
    rejections: dict[str, list[str]] = field(default_factory=dict)
    windows: list[tuple[datetime, datetime]] = field(default_factory=list)


def _disaster_class(skill_id: str) -> str:
    d = SKILL_DISASTER_CLASS.get(skill_id)
    if not d:
        raise KeyError(f"no disaster class mapping for {skill_id!r}")
    return d


def _count_gt_in_window(
    db: Connection,
    disaster_class: str,
    window_start: datetime,
    window_end: datetime,
) -> int:
    aliases = list(class_aliases(disaster_class))
    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*)::int
            FROM ground_truth
            WHERE disaster_class = ANY(%s)
              AND occurred_at IS NOT NULL
              AND occurred_at >= %s - interval '{PRE_BUFFER_HOURS} hours'
              AND occurred_at <= %s + interval '{POST_BUFFER_HOURS} hours'
            """,
            (aliases, window_start, window_end),
        )
        return int(cur.fetchone()[0])


def build_disjoint_windows(
    db: Connection,
    skill_id: str,
) -> list[tuple[datetime, datetime]]:
    """Build MIN_WINDOWS non-overlapping windows with enough ground truth each."""
    dclass = _disaster_class(skill_id)
    aliases = list(class_aliases(dclass))
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT MIN(occurred_at), MAX(occurred_at), COUNT(*)::int
            FROM ground_truth
            WHERE disaster_class = ANY(%s)
              AND occurred_at IS NOT NULL
            """,
            (aliases,),
        )
        row = cur.fetchone()

    if not row or not row[0] or not row[1]:
        log.warning("WARN: insufficient ground truth for cross-window selection")
        return []

    t_min, t_max, total = row[0], row[1], row[2]
    if t_min.tzinfo is None:
        t_min = t_min.replace(tzinfo=timezone.utc)
    if t_max.tzinfo is None:
        t_max = t_max.replace(tzinfo=timezone.utc)

    if total < MIN_GT_EVALS * MIN_WINDOWS:
        log.warning(
            "WARN: insufficient ground truth for cross-window selection "
            f"(have {total}, need {MIN_GT_EVALS * MIN_WINDOWS})"
        )
        return []

    span = (t_max - t_min).total_seconds()
    if span <= 0:
        log.warning("WARN: insufficient ground truth for cross-window selection")
        return []

    windows: list[tuple[datetime, datetime]] = []
    for i in range(MIN_WINDOWS):
        ws = t_min + timedelta(seconds=span * i / MIN_WINDOWS)
        we = t_min + timedelta(seconds=span * (i + 1) / MIN_WINDOWS)
        if i > 0 and ws <= windows[-1][1]:
            log.warning("WARN: windows not disjoint — aborting selection")
            return []
        gt_n = _count_gt_in_window(db, dclass, ws, we)
        if gt_n < MIN_GT_EVALS:
            log.warning(
                "WARN: insufficient ground truth for cross-window selection "
                f"(window {i + 1} has {gt_n} GT, need {MIN_GT_EVALS})"
            )
            return []
        windows.append((ws, we))

    for i in range(len(windows) - 1):
        if windows[i][1] >= windows[i + 1][0]:
            log.warning("WARN: windows not disjoint — aborting selection")
            return []

    return windows


def load_pending_candidates(db: Connection) -> list[CandidateRow]:
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT p.id, l.id, l.skill_id, l.source_code, p.current_version
            FROM skill_edit_proposals p
            JOIN skill_lineage l ON l.proposal_id = p.id
            WHERE p.status = 'pending'
              AND l.status = 'candidate'
            ORDER BY p.proposed_at
            """
        )
        return [
            CandidateRow(
                proposal_id=str(r[0]),
                lineage_id=str(r[1]),
                skill_id=r[2],
                source_code=r[3],
                current_version=int(r[4]),
            )
            for r in cur.fetchall()
        ]


def load_parent_lineage(db: Connection, skill_id: str) -> tuple[str, str] | None:
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT id, source_code
            FROM skill_lineage
            WHERE skill_id = %s AND status = 'promoted'
            ORDER BY version DESC NULLS LAST
            LIMIT 1
            """,
            (skill_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return str(row[0]), row[1]


def _evaluate_candidate(
    db: Connection,
    cand: CandidateRow,
    windows: list[tuple[datetime, datetime]],
    parent_lineage_id: str | None,
) -> tuple[bool, float, list[str]]:
    """Return (qualified, mean_improvement, rejection_reasons)."""
    surface = normalize_mutation_surface(cand.source_code)
    candidate_run = load_run_from_source(surface, cand.skill_id)
    parent_run = load_skill_run(cand.skill_id)

    improvements: list[float] = []
    total_emitted = 0
    reasons: list[str] = []

    for ws, we in windows:
        parent_rows = backtest_skill(
            cand.skill_id,
            [(ws, we)],
            db,
            version=cand.current_version,
            run_fn=parent_run,
            lineage_id=parent_lineage_id,
        )
        cand_rows = backtest_skill(
            cand.skill_id,
            [(ws, we)],
            db,
            version=None,
            run_fn=candidate_run,
            lineage_id=cand.lineage_id,
        )
        if not parent_rows or not cand_rows:
            reasons.append(f"backtest failed for window {ws.isoformat()}")
            return False, 0.0, reasons

        p_brier = parent_rows[0].brier_score
        c_brier = cand_rows[0].brier_score
        total_emitted += cand_rows[0].forecasts_emitted

        if p_brier is None or c_brier is None:
            reasons.append(
                f"null brier in window {ws.date()}–{we.date()}"
            )
            return False, 0.0, reasons

        imp = p_brier - c_brier
        if imp < NOISE_FLOOR:
            reasons.append(
                f"window {ws.date()}–{we.date()}: improvement {imp:.4f} < {NOISE_FLOOR}"
            )
            return False, 0.0, reasons
        improvements.append(imp)

    if total_emitted < MIN_FORECASTS_EMITTED:
        reasons.append("candidate emitted 0 forecasts across all windows")
        return False, 0.0, reasons

    mean_imp = sum(improvements) / len(improvements)
    return True, mean_imp, reasons


def select_candidates(
    db: Connection,
    *,
    dry_run: bool = False,
) -> SelectionResult:
    """Rank pending candidates; promote top-K to shadow status."""
    candidates = load_pending_candidates(db)
    result = SelectionResult()

    if not candidates:
        log.info("no pending candidates")
        return result

    by_skill: dict[str, list[CandidateRow]] = {}
    for c in candidates:
        by_skill.setdefault(c.skill_id, []).append(c)

    qualifiers: list[tuple[float, CandidateRow]] = []

    for skill_id, skill_cands in by_skill.items():
        windows = build_disjoint_windows(db, skill_id)
        if len(windows) < MIN_WINDOWS:
            for c in skill_cands:
                result.rejections[c.lineage_id] = [
                    "insufficient ground truth for cross-window selection"
                ]
            continue

        if not result.windows:
            result.windows = windows

        parent = load_parent_lineage(db, skill_id)
        parent_lineage_id = parent[0] if parent else None

        for cand in skill_cands:
            ok, mean_imp, reasons = _evaluate_candidate(
                db, cand, windows, parent_lineage_id
            )
            if ok:
                qualifiers.append((mean_imp, cand))
            else:
                result.rejections[cand.lineage_id] = reasons
                log.info(
                    "rejected %s lineage=%s: %s",
                    skill_id,
                    cand.lineage_id[:8],
                    reasons,
                )

    qualifiers.sort(key=lambda x: x[0], reverse=True)
    top = qualifiers[:TOP_K]
    result.selected_lineage_ids = [c.lineage_id for _, c in top]

    if dry_run:
        log.info(
            "dry-run: would promote %d lineage row(s): %s",
            len(result.selected_lineage_ids),
            [x[:8] for x in result.selected_lineage_ids],
        )
        return result

    if result.selected_lineage_ids:
        with db.cursor() as cur:
            cur.execute(
                """
                UPDATE skill_lineage
                SET status = 'shadow'
                WHERE id = ANY(%s::uuid[])
                """,
                (result.selected_lineage_ids,),
            )
        db.commit()
        log.info(
            "promoted %d candidate(s) to shadow: %s",
            len(result.selected_lineage_ids),
            [x[:8] for x in result.selected_lineage_ids],
        )

    return result


def main() -> int:
    load_repo_env()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    p = argparse.ArgumentParser(description="Select top-K candidates for shadow deploy")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL required", file=sys.stderr)
        return 2

    with psycopg.connect(url, autocommit=False) as db:
        result = select_candidates(db, dry_run=args.dry_run)

    print(
        f"selected={len(result.selected_lineage_ids)} "
        f"rejected={len(result.rejections)} windows={len(result.windows)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
