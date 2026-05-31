"""LLM-generated forecast reasoning with templated fallback.

Callers build prompts from trace dicts via reasoning_prompts.py (inputs/intermediate
after TraceBuilder) — do not recompute detection math for the LLM.
"""
from __future__ import annotations

import os
import sys

DEFAULT_MODEL = os.environ.get("ENVISION_REASONING_MODEL", "claude-sonnet-4-20250514")
MAX_TOKENS = 200


def generate_reasoning(prompt: str, fallback: str) -> str:
    """Call Sonnet for operator-facing reasoning; never raise."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[reasoning_llm] ANTHROPIC_API_KEY not set; using fallback.", file=sys.stderr)
        return fallback

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        text = ""
        for block in msg.content:
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
        print(f"[reasoning_llm] API error: {e}; using fallback.", file=sys.stderr)
        return fallback
