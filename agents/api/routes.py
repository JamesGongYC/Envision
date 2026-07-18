"""FastAPI routes: forecaster/critic fire + public replay."""
from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from agents.api.auth import require_operator
from agents.api.stream_fire import stream_agent_fire
from agents.common.agent_telemetry import (
    get_run,
    iter_steps,
    step_row_to_sse_payload,
)
from agents.api.sse import format_sse

router = APIRouter()


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(status_code=500, detail="DATABASE_URL not set")
    return url


def _sse_response(gen: Iterator[str]) -> StreamingResponse:
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/agent/forecaster/fire")
def fire_forecaster(_: None = Depends(require_operator)) -> StreamingResponse:
    """Operator-gated live forecaster run; streams ReAct steps as SSE."""

    def gen() -> Iterator[str]:
        from agents.forecaster.loop import run_forecaster_loop

        yield from stream_agent_fire(
            db_url=_db_url(),
            run_loop=run_forecaster_loop,
        )

    return _sse_response(gen())


@router.post("/agent/critic/fire")
def fire_critic(_: None = Depends(require_operator)) -> StreamingResponse:
    """Operator-gated live critic run; streams ReAct steps as SSE."""

    def gen() -> Iterator[str]:
        from agents.critic.loop import run_critic_loop

        yield from stream_agent_fire(
            db_url=_db_url(),
            run_loop=run_critic_loop,
        )

    return _sse_response(gen())


@router.get("/agent/run/{run_id}/replay")
def replay_run(run_id: str) -> StreamingResponse:
    """Public read-only re-stream of persisted agent_step rows."""
    try:
        UUID(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="agent_run not found") from exc

    with psycopg.connect(_db_url(), autocommit=True) as db:
        if get_run(db, run_id) is None:
            raise HTTPException(status_code=404, detail="agent_run not found")

    def gen() -> Iterator[str]:
        with psycopg.connect(_db_url(), autocommit=True) as db:
            for row in iter_steps(db, run_id):
                yield format_sse("step", step_row_to_sse_payload(run_id, row))

    return _sse_response(gen())
