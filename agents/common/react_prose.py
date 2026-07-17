"""Shared ReAct prose helpers for forecaster/critic loops (T8)."""
from __future__ import annotations

import json
from typing import Any


INTENT_NUDGE = (
    "Write 1–2 first-person intent sentences (why this tool, what you expect, "
    "how you will use the result), then call exactly one tool. Do not call a "
    "tool without that prose. Never echo JSON."
)

NARRATION_SYSTEM_SUFFIX = (
    "\n\nWhen narrating a tool result: reply with 1–2 first-person sentences only. "
    "Say what the result means and what it changes. Name skills/signals. "
    "Never echo JSON. Do not call tools."
)


def narration_user_prompt(tool_name: str, observation: Any) -> str:
    payload = json.dumps(observation, default=str)
    if len(payload) > 4000:
        payload = payload[:4000] + "…"
    return (
        f"You called `{tool_name}`. Here is the raw result (do not echo it):\n"
        f"{payload}\n\n"
        "In 1–2 first-person sentences, what does this mean and what does it "
        "change for your next move? Name skills or signals; never paste JSON."
    )
