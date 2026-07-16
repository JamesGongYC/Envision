"""SSE framing helpers for agent trace streams."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from agents.common.agent_telemetry import step_to_sse_payload


def format_sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, default=str, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


def gated_event(
    *,
    reason: str,
    run_id: str | None = None,
    seq: int = 0,
) -> dict[str, Any]:
    return step_to_sse_payload(
        run_id,
        seq=seq,
        step_type="gated",
        tool=None,
        tool_input=None,
        tool_output={"reason": reason},
        geo_focus=None,
        ts=datetime.now(timezone.utc),
    )
