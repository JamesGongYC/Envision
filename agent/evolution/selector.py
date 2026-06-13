"""Selector: advance validated candidates to shadow via light viability gate."""
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

from agent.evolution.backtest_harness import SKILL_CADENCE, backtest_skill  # noqa: E402
from agent.evolution.constants import BACKTEST_EPOCH  # noqa: E402
from agent.evolution.skill_loader import (  # noqa: E402
    load_run_from_source,
    load_skill_run,
)
from agent.evolution.skill_surface import normalize_mutation_surface  # noqa: E402
from agent.lib.repo_env import load_repo_env  # noqa: E402
from agent.lib.scoring import PRE_BUFFER_HOURS, POST_BUFFER_HOURS, class_aliases  # noqa: E402

log = logging.getLogger(__name__)

NOISE_FLOOR = 0.03
MIN_WINDOWS = 3
MIN_GT_EVALS = 10
MIN_FORECASTS_EMITTED = 1
PARENT_SPAM_MULTIPLIER = 3
MIN_GT_FOR_PATHOLOGY = MIN_GT_EVALS * MIN_WINDOWS

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


def _count_gt_post_epoch(db: Connection, skill_id: str) -> int:
    dclass = _disaster_class(skill_id)
    aliases = list(class_aliases(dclass))
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)::int
            FROM ground_truth
            WHERE disaster_class = ANY(%s)
              AND occurred_at IS NOT NULL
              AND occurred_at >= %s
            """,
            (aliases, BACKTEST_EPOCH),
        )
        return int(cur.fetchone()[0])


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
              AND occurred_at >= %s
            """,
            (aliases, BACKTEST_EPOCH),
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


def build_viability_window(
    db: Connection,
    skill_id: str,
    *,
    now: datetime | None = None,
) -> tuple[datetime, datetime] | None:
    """One cadence tick at the latest signal time — fast emit check vs parent."""
    from agent.evolution.skill_validator import _pick_smoke_time

    now = now or datetime.now(timezone.utc)
    if skill_id not in SKILL_CADENCE:
        return None
    t = _pick_smoke_time(db, now)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    if t < BACKTEST_EPOCH:
        t = BACKTEST_EPOCH
    step = SKILL_CADENCE[skill_id]
    t_end = t + step
    if t_end <= t:
        return None
    return t, t_end


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


def _compare_emissions(parent_n: int, cand_n: int) -> list[str]:
    reasons: list[str] = []
    if cand_n < MIN_FORECASTS_EMITTED:
        reasons.append("candidate emitted 0 forecasts on window")
    cap = PARENT_SPAM_MULTIPLIER * max(1, parent_n)
    if cand_n > cap:
        reasons.append(
            f"forecast spam: {cand_n} > {cap} (parent emitted {parent_n})"
        )
    return reasons


def _viability_gate(
    db: Connection,
    cand: CandidateRow,
    window: tuple[datetime, datetime],
    parent_lineage_id: str | None,
) -> tuple[bool, list[str]]:
    """Light gate: emit >0 and within 3x parent volume on one cadence tick."""
    del parent_lineage_id
    from unittest.mock import patch

    from agent.evolution.backtest_connection import BacktestConnection
    from agent.evolution.backtest_harness import _backtest_llm_guard, _blocked_execute

    t = window[0]
    surface = normalize_mutation_surface(cand.source_code)
    candidate_run = load_run_from_source(surface, cand.skill_id)
    parent_run = load_skill_run(cand.skill_id)

    try:
        with _backtest_llm_guard(), patch.object(
            psycopg.Cursor, "execute", _blocked_execute
        ):
            db_parent = BacktestConnection(db, cand.skill_id, t)
            db_cand = BacktestConnection(db, cand.skill_id, t)
            parent_out = parent_run(t, db_parent)
            cand_out = candidate_run(t, db_cand)
    except Exception as exc:
        return False, [f"viability run failed: {type(exc).__name__}: {exc}"]
    finally:
        db.rollback()

    if not isinstance(cand_out, list):
        return False, ["run() must return a list"]
    parent_n = len(parent_out) if isinstance(parent_out, list) else 0
    reasons = _compare_emissions(parent_n, len(cand_out))
    return len(reasons) == 0, reasons


def _pathology_filter(
    db: Connection,
    cand: CandidateRow,
    windows: list[tuple[datetime, datetime]],
    parent_lineage_id: str | None,
) -> tuple[bool, list[str]]:
    """Reject zero-emit or spammy candidates across cross-windows (no Brier ranking)."""
    surface = normalize_mutation_surface(cand.source_code)
    candidate_run = load_run_from_source(surface, cand.skill_id)
    parent_run = load_skill_run(cand.skill_id)

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
            return False, reasons

        window_reasons = _compare_emissions(
            parent_rows[0].forecasts_emitted,
            cand_rows[0].forecasts_emitted,
        )
        if window_reasons:
            reasons.extend(
                [f"window {ws.date()}–{we.date()}: {r}" for r in window_reasons]
            )
            return False, reasons
        total_emitted += cand_rows[0].forecasts_emitted

    if total_emitted < MIN_FORECASTS_EMITTED:
        reasons.append("candidate emitted 0 forecasts across all windows")
        return False, reasons

    return True, reasons


def select_candidates(
    db: Connection,
    *,
    dry_run: bool = False,
) -> SelectionResult:
    """Advance pending candidates that pass viability (and optional pathology filter)."""
    candidates = load_pending_candidates(db)
    result = SelectionResult()

    if not candidates:
        log.info("[selector] no candidates, exiting")
        return result

    by_skill: dict[str, list[CandidateRow]] = {}
    for c in candidates:
        by_skill.setdefault(c.skill_id, []).append(c)

    selected: list[str] = []

    for skill_id, skill_cands in by_skill.items():
        viability_window = build_viability_window(db, skill_id)
        if viability_window is None:
            for c in skill_cands:
                result.rejections[c.lineage_id] = ["invalid viability window span"]
            continue

        parent = load_parent_lineage(db, skill_id)
        parent_lineage_id = parent[0] if parent else None

        gt_total = _count_gt_post_epoch(db, skill_id)
        pathology_windows: list[tuple[datetime, datetime]] = []
        if gt_total >= MIN_GT_FOR_PATHOLOGY:
            pathology_windows = build_disjoint_windows(db, skill_id)
            if len(pathology_windows) >= MIN_WINDOWS and not result.windows:
                result.windows = pathology_windows
        else:
            log.info(
                "insufficient ground truth for cross-window pathology filter "
                f"(have {gt_total}, need {MIN_GT_FOR_PATHOLOGY}); "
                "viability gate only for %s",
                skill_id,
            )

        for cand in skill_cands:
            ok, reasons = _viability_gate(
                db, cand, viability_window, parent_lineage_id
            )
            if not ok:
                result.rejections[cand.lineage_id] = reasons
                log.info(
                    "rejected %s lineage=%s: %s",
                    skill_id,
                    cand.lineage_id[:8],
                    reasons,
                )
                continue

            if len(pathology_windows) >= MIN_WINDOWS:
                ok, reasons = _pathology_filter(
                    db, cand, pathology_windows, parent_lineage_id
                )
                if not ok:
                    result.rejections[cand.lineage_id] = reasons
                    log.info(
                        "rejected %s lineage=%s: %s",
                        skill_id,
                        cand.lineage_id[:8],
                        reasons,
                    )
                    continue

            selected.append(cand.lineage_id)
            log.info(
                "selected %s lineage=%s for shadow",
                skill_id,
                cand.lineage_id[:8],
            )

    result.selected_lineage_ids = selected

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

    p = argparse.ArgumentParser(description="Select candidates for shadow deploy")
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
