"""SSE fire streaming with finalize-on-exit (no in-flight capacity gate)."""
from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import psycopg

from agents.api.sse import format_sse, gated_event
from agents.common.agent_telemetry import finish_run, get_run

# Ending step types: after these, the run should not stay `running`.
_END_STEP_TYPES = frozenset({"terminal", "gated", "failed"})


def _ensure_finished(
    db_url: str,
    run_id: UUID | str | None,
    *,
    error: str,
) -> None:
    """If the run is still `running`, mark it failed. Best-effort; never raises."""
    if not run_id:
        return
    try:
        with psycopg.connect(db_url, autocommit=False) as db:
            row = get_run(db, run_id)
            if row is None:
                return
            if row.get("status") != "running":
                return
            finish_run(
                db,
                agent_run_id=run_id,
                status="failed",
                error=error[:2000],
            )
            db.commit()
    except Exception:  # noqa: BLE001
        return


def _cancel_connection(conn: Any) -> None:
    if conn is None:
        return
    try:
        cancel = getattr(conn, "cancel", None)
        if callable(cancel):
            cancel()
    except Exception:  # noqa: BLE001
        pass
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


def stream_agent_fire(
    *,
    db_url: str,
    run_loop: Callable[..., Any],
) -> Iterator[str]:
    """
    Run an agent loop on a worker thread and yield SSE step events.

    - Finalizes any still-`running` agent_run in worker finally / on disconnect.
    - Exits the generator promptly after terminal/gated/failed + queue drain.
    - On client disconnect (GeneratorExit), cancels the worker DB connection.
    """
    q: queue.Queue[dict[str, Any] | None] = queue.Queue()
    run_id_box: list[UUID | str | None] = [None]
    conn_box: list[Any] = [None]
    stop = threading.Event()

    def on_step(payload: dict[str, Any]) -> None:
        rid = payload.get("run_id")
        if rid and run_id_box[0] is None:
            run_id_box[0] = rid
        q.put(payload)

    def worker() -> None:
        try:
            with psycopg.connect(db_url, autocommit=False) as db:
                conn_box[0] = db
                if stop.is_set():
                    return
                run_loop(
                    datetime.now(timezone.utc),
                    db,
                    trigger="button",
                    on_step=on_step,
                    commit_each_step=True,
                )
        except Exception as exc:  # noqa: BLE001
            if not stop.is_set():
                q.put(gated_event(reason=f"failed:{exc}"))
        finally:
            _ensure_finished(
                db_url,
                run_id_box[0],
                error="worker_exit_while_running",
            )
            q.put(None)
            conn_box[0] = None

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    try:
        while True:
            item = q.get()
            if item is None:
                break
            rid = item.get("run_id")
            if rid and run_id_box[0] is None:
                run_id_box[0] = rid
            yield format_sse("step", item)
            if item.get("step_type") in _END_STEP_TYPES:
                # Drain until sentinel so the worker can exit cleanly.
                while True:
                    try:
                        nxt = q.get(timeout=2.0)
                    except queue.Empty:
                        break
                    if nxt is None:
                        break
                    if nxt.get("step_type") in _END_STEP_TYPES:
                        yield format_sse("step", nxt)
                break
    except GeneratorExit:
        stop.set()
        _cancel_connection(conn_box[0])
        _ensure_finished(
            db_url,
            run_id_box[0],
            error="client_disconnect",
        )
        raise
    finally:
        if stop.is_set():
            _cancel_connection(conn_box[0])
        t.join(timeout=5)
        _ensure_finished(
            db_url,
            run_id_box[0],
            error="stream_cleanup_while_running",
        )
