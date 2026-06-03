"""Replay detection skills over historical windows; score via agent.lib.scoring."""
from __future__ import annotations

import os
import re
import sys
import uuid
from contextlib import contextmanager
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import psycopg
from psycopg import Connection

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_LIB = REPO_ROOT / "agent" / "lib"
for p in (str(REPO_ROOT), str(AGENT_LIB)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent.lib.forecast_model import BacktestRun, Forecast, GroundTruthRow  # noqa: E402
from agent.lib.scoring import (  # noqa: E402
    POST_BUFFER_HOURS,
    PRE_BUFFER_HOURS,
    brier_contribution,
    match_forecast_to_truth,
)
from agent.evolution.backtest_connection import (  # noqa: E402
    BacktestConnection,
    SKILL_LOOKBACK,
)
from agent.evolution.skill_loader import SKILL_FOLDERS, load_skill_run  # noqa: E402

SKILL_CADENCE: dict[str, timedelta] = {
    "wildfire_risk_elevated": timedelta(minutes=30),
    "wildfire_rapid_growth": timedelta(minutes=30),
    "typhoon_intensifying": timedelta(hours=3),
    "typhoon_landfall_imminent": timedelta(hours=3),
}

_BLOCKED_INSERT = re.compile(
    r"\bINSERT\s+INTO\s+(forecasts|signals|evaluations|ground_truth)\b",
    re.IGNORECASE,
)

_anthropic_call_count = 0
_BACKTEST_ENV = "ENVISION_BACKTEST"


@contextmanager
def _backtest_llm_guard():
    """Force template reasoning; fail if Anthropic client is still invoked."""
    global _anthropic_call_count
    _anthropic_call_count = 0
    prev = os.environ.get(_BACKTEST_ENV)
    os.environ[_BACKTEST_ENV] = "1"

    def _raise_anthropic(*_a, **_k):
        global _anthropic_call_count
        _anthropic_call_count += 1
        raise RuntimeError("LLM blocked in backtest")

    try:
        with patch("anthropic.Anthropic", side_effect=_raise_anthropic):
            yield
    finally:
        if prev is None:
            os.environ.pop(_BACKTEST_ENV, None)
        else:
            os.environ[_BACKTEST_ENV] = prev


def _blocked_execute(self, query, params=None, **kwargs):
    if isinstance(query, str) and _BLOCKED_INSERT.search(query):
        raise RuntimeError(
            f"backtest harness blocked live write: {query[:120]}..."
        )
    return _orig_execute(self, query, params, **kwargs)


_orig_execute = psycopg.Cursor.execute


def _audit_signal_leakage(
    db: Connection,
    forecasts: list[Forecast],
    t: datetime,
    skill_id: str,
) -> None:
    ids: list[str] = []
    for f in forecasts:
        ids.extend(f.contributing_signal_ids)
    if not ids:
        return
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT id, timestamp
            FROM signals
            WHERE id = ANY(%s::uuid[])
              AND timestamp > %s
            LIMIT 5
            """,
            (ids, t),
        )
        bad = cur.fetchall()
    if bad:
        raise RuntimeError(
            f"temporal leakage: skill={skill_id} t={t.isoformat()} "
            f"used future signals: {bad}"
        )


def _load_ground_truth(
    db: Connection,
    window_start: datetime,
    window_end: datetime,
) -> list[GroundTruthRow]:
    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, disaster_class, occurred_at,
                   ST_AsGeoJSON(geometry)::text AS geom_geojson
            FROM ground_truth
            WHERE occurred_at IS NOT NULL
              AND occurred_at >= %s - interval '{PRE_BUFFER_HOURS} hours'
              AND occurred_at <= %s + interval '{POST_BUFFER_HOURS} hours'
            """,
            (window_start, window_end),
        )
        rows = cur.fetchall()
    return [
        GroundTruthRow(
            id=r[0],
            disaster_class=r[1],
            occurred_at=r[2],
            geom_geojson=r[3],
        )
        for r in rows
    ]


def _score_window(
    forecasts: list[Forecast],
    ground_truth: list[GroundTruthRow],
    *,
    grace_hours: int = 0,
) -> tuple[int, int, int, float | None]:
    hits = fp = misses = 0
    brier_sum = 0.0
    n_scored = 0
    for f in forecasts:
        matched = match_forecast_to_truth(f, ground_truth, grace_hours=grace_hours)
        outcome, b = brier_contribution(f, matched)
        if outcome == "hit":
            hits += 1
        elif outcome == "false_positive":
            fp += 1
        else:
            misses += 1
        brier_sum += b
        n_scored += 1
    mean_brier = (brier_sum / n_scored) if n_scored else None
    return hits, fp, misses, mean_brier


def _iter_ticks(start: datetime, end: datetime, step: timedelta):
    t = start
    while t <= end:
        yield t
        t += step


def backtest_skill(
    skill_id: str,
    windows: list[tuple[datetime, datetime]],
    db: Connection,
    *,
    version: int | None = None,
    run_fn: Callable[[datetime, Connection], list[Forecast]] | None = None,
    lineage_id: str | None = None,
) -> list[BacktestRun]:
    if skill_id not in SKILL_CADENCE:
        raise KeyError(f"no cadence for {skill_id}")

    run_fn = run_fn or load_skill_run(skill_id)
    step = SKILL_CADENCE[skill_id]
    results: list[BacktestRun] = []

    with _backtest_llm_guard(), patch.object(psycopg.Cursor, "execute", _blocked_execute):
        for window_start, window_end in windows:
            ws = window_start if window_start.tzinfo else window_start.replace(
                tzinfo=timezone.utc
            )
            we = window_end if window_end.tzinfo else window_end.replace(
                tzinfo=timezone.utc
            )
            ground_truth = _load_ground_truth(db, ws, we)
            collected: list[Forecast] = []

            for t in _iter_ticks(ws, we, step):
                if skill_id not in SKILL_LOOKBACK:
                    raise KeyError(f"no lookback for {skill_id}")
                db_tick = BacktestConnection(db, skill_id, t)
                batch = run_fn(t, db_tick)
                _audit_signal_leakage(db, batch, t, skill_id)
                collected.extend(batch)

            hits, fp, misses, mean_brier = _score_window(collected, ground_truth)

            row = BacktestRun(
                id=str(uuid.uuid4()),
                skill_id=skill_id,
                window_start=ws,
                window_end=we,
                version=version,
                lineage_id=lineage_id,
                brier_score=mean_brier,
                hits=hits,
                false_positives=fp,
                misses=misses,
                forecasts_emitted=len(collected),
                run_at=datetime.now(timezone.utc),
            )

            with db.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO backtest_run (
                      id, skill_id, version, lineage_id,
                      window_start, window_end,
                      brier_score, hits, false_positives, misses,
                      forecasts_emitted, run_at
                    ) VALUES (
                      %(id)s, %(skill_id)s, %(version)s, %(lineage_id)s,
                      %(window_start)s, %(window_end)s,
                      %(brier_score)s, %(hits)s, %(false_positives)s, %(misses)s,
                      %(forecasts_emitted)s, %(run_at)s
                    )
                    """,
                    {
                        "id": row.id,
                        "skill_id": row.skill_id,
                        "version": row.version,
                        "lineage_id": row.lineage_id,
                        "window_start": row.window_start,
                        "window_end": row.window_end,
                        "brier_score": row.brier_score,
                        "hits": row.hits,
                        "false_positives": row.false_positives,
                        "misses": row.misses,
                        "forecasts_emitted": row.forecasts_emitted,
                        "run_at": row.run_at,
                    },
                )
            db.commit()
            results.append(row)

    if _anthropic_call_count > 0:
        raise RuntimeError(
            f"expected zero Anthropic calls during backtest, got {_anthropic_call_count}"
        )

    return results


def main() -> int:
    import argparse
    import os

    from agent.lib.repo_env import load_repo_env

    load_repo_env()

    p = argparse.ArgumentParser(description="Run backtest for one skill")
    p.add_argument("--skill-id", default="wildfire_risk_elevated")
    p.add_argument("--days", type=int, default=7)
    args = p.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL required", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    window = (now - timedelta(days=args.days), now)
    with psycopg.connect(url, autocommit=False) as db:
        rows = backtest_skill(args.skill_id, [window], db)
    for r in rows:
        print(
            f"{r.skill_id}: emitted={r.forecasts_emitted} "
            f"brier={r.brier_score} hits={r.hits} fp={r.false_positives}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
