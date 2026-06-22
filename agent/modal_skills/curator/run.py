#!/usr/bin/env python3
"""
curator — Envision v3 evolution orchestrator (daily).

Once per day:
  1. LLM health preflight probe (independent of kill switch).
  2. Optional operator-seeded generator (ENVISION_GENERATOR_*).
  3. When enabled: worst-K mutation pass.
  4. select_candidates() → shadow.
  5. Operator promotes via tools/review_proposals.py promote (human gate).

Does not write production skill files.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import Connection

_REPO = Path(__file__).resolve()
if "modal_skills" in _REPO.parts:
    _AGENT_ROOT = Path(*_REPO.parts[: _REPO.parts.index("modal_skills")])
else:
    _AGENT_ROOT = _REPO.parents[2]
_REPO_ROOT = _AGENT_ROOT.parent
for p in (str(_REPO_ROOT), str(_AGENT_ROOT / "lib")):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent.evolution.budget import BudgetTracker  # noqa: E402
from agent.evolution.generation_trigger import is_generator_seeded  # noqa: E402
from agent.evolution.orchestrator import run_evolution_pass  # noqa: E402
from agent.lib.health_gate import preflight_probe  # noqa: E402

SKILL_ID = "curator"
CURATOR_ENABLED_VAR = "ENVISION_CURATOR_ENABLED"

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print(f"[{SKILL_ID}] DATABASE_URL not set", file=sys.stderr)
    sys.exit(2)


def parse_now(argv: list[str] | None = None) -> datetime:
    p = argparse.ArgumentParser(description="Run the Envision Curator evolution pass")
    p.add_argument("--now", default=None, help="ISO8601 UTC run time (default: now)")
    args = p.parse_args(argv)
    if args.now is None:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_curator_enabled() -> bool:
    val = os.environ.get(CURATOR_ENABLED_VAR)
    if val is None or val == "":
        return True
    return val.strip().lower() in ("1", "true", "yes", "on", "y", "t")


def run(now: datetime, db: Connection) -> dict:
    if not preflight_probe(db):
        return {
            "health_gate": "preflight_failed",
            "enabled": is_curator_enabled(),
            "targeted": [],
            "mutated": 0,
            "accepted": 0,
        }

    curator_on = is_curator_enabled()
    generator_on = is_generator_seeded()

    if not curator_on and not generator_on:
        print(
            f"[{SKILL_ID}] disabled by kill switch "
            f"({CURATOR_ENABLED_VAR}={os.environ.get(CURATOR_ENABLED_VAR)}) "
            "and generator not seeded; exiting."
        )
        return {"enabled": False, "targeted": [], "mutated": 0, "accepted": 0}

    if (curator_on or generator_on) and not os.environ.get("ANTHROPIC_API_KEY"):
        print(f"[{SKILL_ID}] ANTHROPIC_API_KEY not set", file=sys.stderr)
        return {"error": "ANTHROPIC_API_KEY not set"}

    summary = run_evolution_pass(
        db,
        now,
        budget=BudgetTracker(),
        curator_enabled=curator_on,
    )
    out = summary.as_dict()
    out["enabled"] = curator_on
    out["generator_seeded"] = generator_on
    out["health_gate"] = "ok"
    return out


def main() -> int:
    now = parse_now()
    with psycopg.connect(DATABASE_URL, autocommit=False) as db:
        run(now, db)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"[{SKILL_ID}] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
