"""FastAPI routes: forecaster/critic fire + public replay."""
from __future__ import annotations

import os
import queue
import threading
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from agents.api.auth import require_operator
from agents.api.concurrency import at_capacity
from agents.api.sse import format_sse, gated_event
from agents.common.agent_telemetry import (
    get_run,
    iter_steps,
    step_row_to_sse_payload,
)

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
        # Capacity check on a short-lived connection (no run started yet).
        with psycopg.connect(_db_url(), autocommit=True) as db:
            if at_capacity(db):
                yield format_sse("step", gated_event(reason="max_in_flight"))
                return

        from agents.forecaster.loop import run_forecaster_loop

        q: queue.Queue[dict[str, Any] | None] = queue.Queue()

        def worker() -> None:
            try:
                with psycopg.connect(_db_url(), autocommit=False) as db:
                    run_forecaster_loop(
                        datetime.now(timezone.utc),
                        db,
                        trigger="button",
                        on_step=lambda payload: q.put(payload),
                        commit_each_step=True,
                    )
            except Exception as exc:  # noqa: BLE001
                q.put(gated_event(reason=f"failed:{exc}"))
            finally:
                q.put(None)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        while True:
            item = q.get()
            if item is None:
                break
            yield format_sse("step", item)
        t.join(timeout=5)

    return _sse_response(gen())


@router.post("/agent/critic/fire")
def fire_critic(_: None = Depends(require_operator)) -> StreamingResponse:
    """Operator-gated live critic run; streams ReAct steps as SSE."""

    def gen() -> Iterator[str]:
        with psycopg.connect(_db_url(), autocommit=True) as db:
            if at_capacity(db):
                yield format_sse("step", gated_event(reason="max_in_flight"))
                return

        from agents.critic.loop import run_critic_loop

        q: queue.Queue[dict[str, Any] | None] = queue.Queue()

        def worker() -> None:
            try:
                with psycopg.connect(_db_url(), autocommit=False) as db:
                    run_critic_loop(
                        datetime.now(timezone.utc),
                        db,
                        trigger="button",
                        on_step=lambda payload: q.put(payload),
                        commit_each_step=True,
                    )
            except Exception as exc:  # noqa: BLE001
                q.put(gated_event(reason=f"failed:{exc}"))
            finally:
                q.put(None)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        while True:
            item = q.get()
            if item is None:
                break
            yield format_sse("step", item)
        t.join(timeout=5)

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
