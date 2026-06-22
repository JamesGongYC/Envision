"""LLM-generated forecast reasoning with templated fallback.

Callers build prompts from trace dicts via reasoning_prompts.py (inputs/intermediate
after TraceBuilder) — do not recompute detection math for the LLM.
"""
from __future__ import annotations

import os
import sys

from psycopg import Connection

try:
    from llm_client import (
        DEFAULT_REASONING_MODEL,
        call_messages,
    )
except ImportError:
    from agent.lib.llm_client import (  # type: ignore[no-redef]
        DEFAULT_REASONING_MODEL,
        call_messages,
    )

MAX_TOKENS = 200

_BACKTEST_ENV = "ENVISION_BACKTEST"


def _in_backtest() -> bool:
    return os.environ.get(_BACKTEST_ENV, "").lower() in ("1", "true", "yes")


def generate_reasoning(
    prompt: str,
    fallback: str,
    *,
    db: Connection | None = None,
) -> str:
    """Call Sonnet for operator-facing reasoning; never raise."""
    if _in_backtest():
        return fallback

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[reasoning_llm] ANTHROPIC_API_KEY not set; using fallback.", file=sys.stderr)
        return fallback

    try:
        response, _model = call_messages(
            call_site="narrator",
            db=db,
            messages=[{"role": "user", "content": prompt}],
            model=DEFAULT_REASONING_MODEL,
            fallback_model=None,
            max_tokens=MAX_TOKENS,
        )
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text
        text = text.strip()
        if not text:
            print("[reasoning_llm] empty LLM response; using fallback.", file=sys.stderr)
            return fallback
        if len(text) > 400:
            text = text[:397] + "..."
        return text
    except Exception as e:  # noqa: BLE001
        if "LLM blocked in backtest" not in str(e):
            print(f"[reasoning_llm] API error: {e}; using fallback.", file=sys.stderr)
        return fallback
