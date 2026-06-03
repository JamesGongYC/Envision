"""Run shadow lineage skills at live cadence into forecasts_shadow."""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg import Connection

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_LIB = REPO_ROOT / "agent" / "lib"
for p in (str(REPO_ROOT), str(AGENT_LIB)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent.evolution.backtest_harness import SKILL_CADENCE  # noqa: E402
from agent.evolution.skill_loader import load_run_from_source  # noqa: E402
from agent.lib.forecast_model import Forecast  # noqa: E402
from agent.lib.forecast_writer import emit_forecasts  # noqa: E402
from agent.lib.repo_env import load_repo_env  # noqa: E402

SHADOW_RATE_LIMIT = 50


def _load_shadow_lineages(db: Connection) -> list[tuple[str, str, str]]:
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT id, skill_id, source_code
            FROM skill_lineage
            WHERE status = 'shadow'
            ORDER BY skill_id, created_at
            """
        )
        return [(str(r[0]), r[1], r[2]) for r in cur.fetchall()]


def _apply_rate_limit(
    forecasts: list[Forecast],
    lineage_id: str,
) -> tuple[list[Forecast], bool]:
    if len(forecasts) <= SHADOW_RATE_LIMIT:
        return forecasts, False
    capped = forecasts[:SHADOW_RATE_LIMIT]
    for f in capped:
        trace = f.trace
        if isinstance(trace, str):
            try:
                trace = json.loads(trace)
            except json.JSONDecodeError:
                trace = {}
        if not isinstance(trace, dict):
            trace = {}
        trace = dict(trace)
        trace["pathological"] = True
        trace["pathological_reason"] = (
            f"emitted {len(forecasts)} forecasts; capped at {SHADOW_RATE_LIMIT}"
        )
        trace["lineage_id"] = lineage_id
        f.trace = trace
    return capped, True


def run_shadow_bucket(
    cadence: timedelta,
    now: datetime,
    db: Connection,
) -> int:
    """Run all shadow lineages matching this cadence bucket."""
    total = 0
    for lineage_id, skill_id, source_code in _load_shadow_lineages(db):
        if SKILL_CADENCE.get(skill_id) != cadence:
            continue
        run_fn = load_run_from_source(source_code, skill_id)
        batch = run_fn(now, db)
        if not isinstance(batch, list):
            print(
                f"[shadow_runner] {skill_id} lineage={lineage_id[:8]}: "
                f"run() returned {type(batch).__name__}, expected list",
                file=sys.stderr,
            )
            continue
        capped, pathological = _apply_rate_limit(batch, lineage_id)
        if pathological:
            print(
                f"[shadow_runner] WARN pathological: {skill_id} "
                f"lineage={lineage_id[:8]} capped {len(batch)} -> {len(capped)}",
                file=sys.stderr,
            )
        n = emit_forecasts(
            capped,
            db,
            table="forecasts_shadow",
            lineage_id=lineage_id,
        )
        total += n
        print(
            f"[shadow_runner] {skill_id} lineage={lineage_id[:8]}: "
            f"emitted {n} shadow forecast(s)"
        )
    return total


def run_shadow_tick(cadence_minutes: int, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    cadence = timedelta(minutes=cadence_minutes)
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    with psycopg.connect(url, autocommit=False) as db:
        n = run_shadow_bucket(cadence, now, db)
        db.commit()
    return n


def main() -> int:
    load_repo_env()
    p = argparse.ArgumentParser(description="Run shadow skills for one cadence bucket")
    p.add_argument(
        "--cadence-minutes",
        type=int,
        required=True,
        choices=[30, 180],
        help="30 for wildfire bucket, 180 for typhoon bucket",
    )
    p.add_argument("--now", default=None, help="ISO8601 UTC (default: now)")
    args = p.parse_args()

    now = datetime.now(timezone.utc)
    if args.now:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

    n = run_shadow_tick(args.cadence_minutes, now)
    print(f"[shadow_runner] total emitted: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
