#!/usr/bin/env python3
"""
curator — Envision Day 6 skill.

The self-evolving engine. Once per day:
  1. Pulls 14-day Brier stats per detection skill from `evaluations`.
  2. For each mutable skill with enough data and no already-pending
     proposal, reads its current script.
  3. Sends code + recent performance to Claude with strict scope rules
     (only numeric constants and templated reasoning strings can change).
  4. Receives a structured response via tool-use, validates the
     proposed code is valid Python, and is not a literal no-op.
  5. Writes the proposal to `skill_edit_proposals` with status='pending'.

The Curator never modifies live skill files. Promotion is manual via
`tools/review_proposals.py`.

Gated by `ENVISION_CURATOR_ENABLED`. Default-on; set to `false` to halt.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from anthropic import Anthropic
from psycopg import Connection

_LIB = Path(__file__).resolve().parents[2] / "lib"
if _LIB.is_dir() and str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))
from trace_builder import CuratorTraceBuilder  # noqa: E402

# --- config --------------------------------------------------------------
SKILL_ID = "curator"
CURATOR_ENABLED_VAR = "ENVISION_CURATOR_ENABLED"

# Min evaluations in last 14d before the Curator will propose anything
MIN_EVALUATIONS_TO_CONSIDER = 5

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8192

# Only these skills are eligible for mutation. Adding a new skill here
# does not enable mutation automatically — confirm the script's tunables
# are well-formed first.
MUTABLE_SKILLS: set[str] = {
    "wildfire_risk_elevated",
    "wildfire_rapid_growth",
    "typhoon_intensifying",
    "typhoon_landfall_imminent",
}

HERMES_SKILLS_DIR = os.path.expanduser("~/.hermes/skills")

DATABASE_URL = os.environ.get("DATABASE_URL")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not DATABASE_URL:
    print(f"[{SKILL_ID}] DATABASE_URL not set", file=sys.stderr)
    sys.exit(2)
if not ANTHROPIC_API_KEY:
    print(f"[{SKILL_ID}] ANTHROPIC_API_KEY not set", file=sys.stderr)
    sys.exit(2)


def parse_now(argv: list[str] | None = None) -> datetime:
    p = argparse.ArgumentParser(description="Run the Envision Curator")
    p.add_argument("--now", default=None, help="ISO8601 UTC run time (default: now)")
    args = p.parse_args(argv)
    if args.now is None:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --- kill switch ---------------------------------------------------------
def is_curator_enabled() -> bool:
    """Mirror tools/check_status.py. Default ON."""
    val = os.environ.get(CURATOR_ENABLED_VAR)
    if val is None or val == "":
        return True
    return val.strip().lower() in ("1", "true", "yes", "on", "y", "t")


# --- data access ---------------------------------------------------------
def load_per_skill_stats(conn: Connection, now: datetime) -> list[tuple]:
    """Return [(skill_id, version, n_evals, mean_brier, hits, fp), ...]
    for evaluations in the last 14 days."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              f.skill_id,
              MAX(f.skill_version)::int                 AS version,
              COUNT(*)::int                             AS n_evaluations,
              AVG(e.brier_contribution)::float          AS mean_brier,
              SUM(CASE WHEN e.outcome = 'hit' THEN 1 ELSE 0 END)::int
                AS hits,
              SUM(CASE WHEN e.outcome = 'false_positive' THEN 1 ELSE 0 END)::int
                AS false_positives
            FROM evaluations e
            JOIN forecasts f ON f.id = e.forecast_id
            WHERE e.evaluated_at > %s - interval '14 days'
            GROUP BY f.skill_id
            """,
            (now,),
        )
        return cur.fetchall()


def load_brier_stats_30d(conn: Connection, now: datetime) -> dict[str, dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              f.skill_id,
              COUNT(*)::int AS n_evaluations,
              AVG(e.brier_contribution)::float AS mean_brier
            FROM evaluations e
            JOIN forecasts f ON f.id = e.forecast_id
            WHERE e.evaluated_at > %s - interval '30 days'
            GROUP BY f.skill_id
            """,
            (now,),
        )
        return {
            row[0]: {"brier_30d": float(row[2]), "eval_count_30d": int(row[1])}
            for row in cur.fetchall()
        }


def build_brier_stats_observed(
    rows_14d: list[tuple],
    stats_30d: dict[str, dict],
) -> dict[str, dict]:
    observed: dict[str, dict] = {}
    for skill_id, _version, n_evals, mean_brier, hits, fp in rows_14d:
        entry = {
            "brier_14d": round(float(mean_brier), 4),
            "eval_count": int(n_evals),
            "hits": int(hits),
            "false_positives": int(fp),
        }
        if skill_id in stats_30d:
            entry.update(stats_30d[skill_id])
        observed[skill_id] = entry
    return observed


def has_pending_proposal(conn, skill_id: str, version: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM skill_edit_proposals
            WHERE skill_id = %s
              AND current_version = %s
              AND status = 'pending'
            LIMIT 1
            """,
            (skill_id, version),
        )
        return cur.fetchone() is not None


def insert_proposal(
    conn: Connection,
    skill_id: str,
    current_version: int,
    proposed_code: str,
    reasoning: str,
    now: datetime,
    curator_trace: dict,
) -> None:
    with conn.cursor() as cur:
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
                str(uuid.uuid4()),
                now,
                skill_id,
                current_version,
                proposed_code,
                reasoning,
                json.dumps(curator_trace),
            ),
        )


# --- filesystem ---------------------------------------------------------
def find_skill_script(skill_id: str) -> str | None:
    """Locate the main detect_*.py file for a skill. Tries hyphenated
    and underscored directory variants because skill_id in the DB is
    canonical (with underscores) while disk uses hyphens."""
    candidates = (skill_id, skill_id.replace("_", "-"))
    for c in candidates:
        scripts_dir = os.path.join(HERMES_SKILLS_DIR, c, "scripts")
        if not os.path.isdir(scripts_dir):
            continue
        for fn in sorted(os.listdir(scripts_dir)):
            if fn.startswith("detect_") and fn.endswith(".py"):
                return os.path.join(scripts_dir, fn)
    return None


# --- LLM call ------------------------------------------------------------
SYSTEM_PROMPT = """You are the Curator for Envision, an experimental
wildfire and tropical-cyclone monitoring agent. Your single responsibility
is to propose small, safe parameter adjustments to detection skills based
on their recent calibration performance.

You operate under strict scope rules:
- You MAY change numeric constants at the top of the file (thresholds,
  probabilities, time windows, buffer sizes).
- You MAY change templated string content used to build the `reasoning`
  field of forecasts.
- You MAY NOT change function signatures, control flow, imports, SQL,
  table or column names, or any cryptography/networking code.
- If the data is too sparse to draw a conclusion, propose the file
  unchanged and explain in your reasoning that you are deferring.

Lower Brier scores are better. A score consistently above ~0.3 with mostly
false positives means the skill is over-confident or its threshold is too
permissive; consider tightening thresholds or lowering base probability.
"""


def build_user_prompt(
    skill_id: str,
    code: str,
    n_evals: int,
    mean_brier: float,
    hits: int,
    false_positives: int,
) -> str:
    fp_rate = false_positives / max(1, n_evals)
    return f"""Skill under review: `{skill_id}`

Last 14 days of evaluations:
- Total: {n_evals}
- Hits: {hits}
- False positives: {false_positives} ({fp_rate:.0%} of evaluations)
- Mean Brier contribution: {mean_brier:.4f}

Current script:

```python
{code}
```

Propose either a small adjustment or a no-op. Use the
`propose_skill_edit` tool to submit your response.
"""


PROPOSE_TOOL = {
    "name": "propose_skill_edit",
    "description": (
        "Submit a proposed edit to the skill, or submit it unchanged "
        "with a no-op explanation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reasoning": {
                "type": "string",
                "description": (
                    "1-3 sentence explanation of the change and its "
                    "expected effect. If proposing a no-op, say why."
                ),
            },
            "proposed_code": {
                "type": "string",
                "description": (
                    "The complete new file content. Must be valid "
                    "Python 3. Pass the file unchanged for a no-op."
                ),
            },
        },
        "required": ["reasoning", "proposed_code"],
    },
}


def serialize_llm_response(response) -> str:
    parts: list[str] = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
        elif getattr(block, "type", None) == "tool_use":
            parts.append(json.dumps(block.input, ensure_ascii=False))
    return "\n".join(parts) or str(response)


def call_curator_llm(
    client: Anthropic,
    skill_id: str,
    code: str,
    n_evals: int,
    mean_brier: float,
    hits: int,
    fp: int,
) -> tuple[str, str, object, str]:
    """Returns (reasoning, proposed_code, response, user_prompt)."""
    user_prompt = build_user_prompt(
        skill_id, code, n_evals, mean_brier, hits, fp
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[PROPOSE_TOOL],
        tool_choice={"type": "tool", "name": "propose_skill_edit"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    tool_block = next(
        (b for b in response.content if b.type == "tool_use"), None
    )
    if tool_block is None:
        raise RuntimeError("LLM did not return a tool_use block")

    inp = tool_block.input
    return inp["reasoning"], inp["proposed_code"], response, user_prompt


# --- validation ----------------------------------------------------------
def validate_python(source: str) -> tuple[bool, list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    try:
        ast.parse(source)
    except SyntaxError as e:
        errors.append(str(e))
        return False, warnings, errors
    return True, warnings, errors


def is_valid_python(source: str) -> bool:
    passed, _, _ = validate_python(source)
    return passed


def is_no_op(current: str, proposed: str) -> bool:
    return current.strip() == proposed.strip()


# --- run -----------------------------------------------------------------
def run(now: datetime, db: Connection) -> dict:
    if not is_curator_enabled():
        print(
            f"[{SKILL_ID}] disabled by kill switch "
            f"(ENVISION_CURATOR_ENABLED={os.environ.get(CURATOR_ENABLED_VAR)}); "
            f"exiting."
        )
        return {"considered": 0, "proposed": 0, "skipped": 0}

    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    considered = 0
    proposed = 0
    skipped = 0

    rows = load_per_skill_stats(db, now)
    stats_30d = load_brier_stats_30d(db, now)
    brier_observed = build_brier_stats_observed(rows, stats_30d)
    if not rows:
        print(
            f"[{SKILL_ID}] no evaluations in last 14 days; "
            f"nothing to consider."
        )
        return {"considered": 0, "proposed": 0, "skipped": 0}

    for skill_id, version, n_evals, mean_brier, hits, fp in rows:
        if skill_id not in MUTABLE_SKILLS:
            continue

        if n_evals < MIN_EVALUATIONS_TO_CONSIDER:
            print(
                f"[{SKILL_ID}] {skill_id} v{version}: "
                f"only {n_evals} evaluations; skipping."
            )
            skipped += 1
            continue

        if has_pending_proposal(db, skill_id, version):
            print(
                f"[{SKILL_ID}] {skill_id} v{version}: "
                f"already has a pending proposal; skipping."
            )
            skipped += 1
            continue

        script_path = find_skill_script(skill_id)
        if not script_path:
            print(
                f"[{SKILL_ID}] {skill_id}: cannot locate script "
                f"on disk; skipping."
            )
            skipped += 1
            continue

        with open(script_path, encoding="utf-8") as f:
            current_code = f.read()

        considered += 1
        print(
            f"[{SKILL_ID}] {skill_id} v{version}: calling LLM "
            f"(n={n_evals}, brier={mean_brier:.3f}, "
            f"hits={hits}, fp={fp})..."
        )

        try:
            reasoning, proposed_code, response, user_prompt = call_curator_llm(
                client, skill_id, current_code,
                n_evals, mean_brier, hits, fp,
            )
        except Exception as e:  # noqa: BLE001
            print(
                f"[{SKILL_ID}] {skill_id}: LLM call failed: {e}"
            )
            continue

        passed, warnings, errors = validate_python(proposed_code)
        if is_no_op(current_code, proposed_code):
            warnings.append("proposed_code_identical_to_current")
            print(
                f"[{SKILL_ID}] {skill_id}: LLM proposed no-op. "
                f"Reasoning: {reasoning[:120]}"
            )
            continue

        if not passed:
            print(
                f"[{SKILL_ID}] {skill_id}: proposed code is not "
                f"valid Python; rejecting."
            )
            continue

        ctb = CuratorTraceBuilder()
        ctb.set_brier_stats(brier_observed)
        ctb.set_ast_validation(passed=True, warnings=warnings, errors=errors)
        ctb.set_llm_hash(
            hashlib.sha256(user_prompt.encode("utf-8")).hexdigest()[:16]
        )
        ctb.set_llm_response(serialize_llm_response(response))

        insert_proposal(
            db,
            skill_id,
            version,
            proposed_code,
            reasoning,
            now,
            ctb.build(),
        )
        proposed += 1
        print(
            f"[{SKILL_ID}] {skill_id}: proposal recorded. "
            f"Reasoning: {reasoning[:120]}"
        )

    db.commit()

    print(
        f"[{SKILL_ID}] done. considered={considered} proposed={proposed} "
        f"skipped={skipped}."
    )
    return {"considered": considered, "proposed": proposed, "skipped": skipped}


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
