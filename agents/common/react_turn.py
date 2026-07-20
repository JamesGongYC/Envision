"""Shared ReAct turn helpers — text-retry nudge (T13). No LLM calls here."""
from __future__ import annotations

from typing import Any, Sequence

TEXT_RETRY_MAX = 1

MISSING_TEXT_NUDGE = (
    "Include 1–2 first-person sentences in a text block beside the tool_use "
    "(intent or sense-making). Do not omit the tool call. Name places in words; "
    "never write raw lat/lng or coordinate pairs."
)


def missing_text_nudge() -> str:
    """User message when the model returned tool_use without a text block."""
    return MISSING_TEXT_NUDGE


def should_retry_for_text(
    thought: str,
    tool_uses: Sequence[Any],
    *,
    text_retries: int,
    text_retry_max: int = TEXT_RETRY_MAX,
) -> bool:
    """True when tools arrived without prose and we still have a retry left."""
    return bool(tool_uses) and not bool(thought) and text_retries < text_retry_max
