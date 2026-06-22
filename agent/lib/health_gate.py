"""LLM API health gate: pre-flight probe + rolling 529 window."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from psycopg import Connection

try:
    from llm_client import DEFAULT_SONNET, PROBE_MODEL, call_messages
except ImportError:
    from agent.lib.llm_client import DEFAULT_SONNET, PROBE_MODEL, call_messages  # type: ignore

DEFAULT_WINDOW_MINUTES = int(os.environ.get("ENVISION_LLM_GATE_WINDOW_MINUTES", "10"))
DEFAULT_MIN_SAMPLES = int(os.environ.get("ENVISION_LLM_GATE_MIN_SAMPLES", "5"))
DEFAULT_529_THRESHOLD = float(os.environ.get("ENVISION_LLM_GATE_529_THRESHOLD", "0.5"))


@dataclass
class GateStats:
    attempts: int
    overloaded: int
    overloaded_rate: float


def rolling_gate_stats(
    db: Connection,
    *,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
) -> GateStats:
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT
                count(*)::int AS attempts,
                count(*) FILTER (WHERE status_code = 529)::int AS overloaded,
                count(*) FILTER (WHERE status_code = 529)::float
                    / NULLIF(count(*), 0) AS overloaded_rate
            FROM llm_call_log
            WHERE created_at >= now() - (%s * interval '1 minute')
            """,
            (window_minutes,),
        )
        row = cur.fetchone()
    attempts = int(row[0] or 0)
    overloaded = int(row[1] or 0)
    rate = float(row[2] or 0.0)
    return GateStats(attempts=attempts, overloaded=overloaded, overloaded_rate=rate)


def should_abort_cycle(
    db: Connection,
    *,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    threshold: float = DEFAULT_529_THRESHOLD,
) -> bool:
    stats = rolling_gate_stats(db, window_minutes=window_minutes)
    if stats.attempts < min_samples:
        return False
    return stats.overloaded_rate >= threshold


def preflight_probe(db: Connection) -> bool:
    """Cheap probe call. Returns False on capacity/overload errors."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[health_gate] ANTHROPIC_API_KEY not set; probe skipped.", file=sys.stderr)
        return False
    try:
        call_messages(
            call_site="probe",
            db=db,
            messages=[{"role": "user", "content": "Reply with exactly: ok"}],
            model=PROBE_MODEL,
            fallback_model=DEFAULT_SONNET if PROBE_MODEL != DEFAULT_SONNET else None,
            max_tokens=8,
        )
        db.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        from anthropic import APIStatusError

        if isinstance(exc, APIStatusError) and exc.status_code in (529, 503):
            print(f"[health_gate] preflight probe failed: {exc}", file=sys.stderr)
            return False
        print(f"[health_gate] preflight probe error: {exc}", file=sys.stderr)
        return False
