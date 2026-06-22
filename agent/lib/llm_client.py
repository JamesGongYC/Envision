"""Shared Anthropic client wrapper with retry, telemetry, and model-tier fallback."""
from __future__ import annotations

import os
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from psycopg import Connection

CallSite = Literal["mutator", "curator", "generator", "narrator", "probe"]

MAX_RETRIES_PER_MODEL = 3
BACKOFF_BASE_S = 1.0
BACKOFF_CAP_S = 30.0

DEFAULT_SONNET = os.environ.get("ENVISION_MUTATOR_MODEL", "claude-sonnet-4-6")
DEFAULT_HAIKU = os.environ.get(
    "ENVISION_MUTATOR_FALLBACK_MODEL", "claude-haiku-4-5"
)
DEFAULT_REASONING_MODEL = os.environ.get(
    "ENVISION_REASONING_MODEL", DEFAULT_SONNET
)
PROBE_MODEL = os.environ.get("ENVISION_PROBE_MODEL", DEFAULT_HAIKU)


@dataclass
class AttemptLog:
    attempt: int
    model: str
    status_code: int | None
    outcome: str
    error_type: str | None
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_input_tokens: int | None
    request_id: str | None


def _extract_request_id(response: Any) -> str | None:
    rid = getattr(response, "_request_id", None)
    if rid:
        return str(rid)
    headers = getattr(response, "headers", None)
    if headers is not None:
        if hasattr(headers, "get"):
            h = headers.get("request-id") or headers.get("Request-Id")
            if h:
                return str(h)
    return None


def _extract_error_type(exc: Any) -> str | None:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("type"):
            return str(err["type"])
    return getattr(exc, "type", None)


def _retry_after_seconds(exc: Any) -> float | None:
    headers = getattr(exc, "headers", None)
    if headers is None:
        response = getattr(exc, "response", None)
        if response is not None:
            headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw = None
    if hasattr(headers, "get"):
        raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def _usage_fields(response: Any) -> tuple[int | None, int | None, int | None]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None, None
    return (
        getattr(usage, "input_tokens", None),
        getattr(usage, "output_tokens", None),
        getattr(usage, "cache_read_input_tokens", None),
    )


def log_attempt(
    db: Connection | None,
    *,
    call_group_id: uuid.UUID,
    attempt: int,
    call_site: CallSite,
    model: str,
    status_code: int | None,
    outcome: str,
    error_type: str | None,
    latency_ms: int | None,
    input_tokens: int | None,
    output_tokens: int | None,
    cache_read_input_tokens: int | None,
    request_id: str | None,
) -> None:
    if db is None:
        return
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO llm_call_log (
              call_group_id, attempt, call_site, model,
              status_code, outcome, error_type, latency_ms,
              input_tokens, output_tokens, cache_read_input_tokens,
              request_id
            ) VALUES (
              %s, %s, %s, %s,
              %s, %s, %s, %s,
              %s, %s, %s,
              %s
            )
            """,
            (
                str(call_group_id),
                attempt,
                call_site,
                model,
                status_code,
                outcome,
                error_type,
                latency_ms,
                input_tokens,
                output_tokens,
                cache_read_input_tokens,
                request_id,
            ),
        )
    try:
        db.commit()
    except Exception:  # noqa: BLE001
        pass


def _is_retriable_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


def _sleep_backoff(attempt_idx: int, retry_after: float | None) -> None:
    if retry_after is not None:
        time.sleep(retry_after)
        return
    delay = min(BACKOFF_CAP_S, BACKOFF_BASE_S * (2 ** attempt_idx))
    jitter = random.uniform(0, delay * 0.25)
    time.sleep(delay + jitter)


def call_messages(
    *,
    call_site: CallSite,
    db: Connection | None,
    messages: list[dict[str, Any]],
    model: str,
    fallback_model: str | None = None,
    max_tokens: int,
    system: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | None = None,
    budget: Any | None = None,
    api_key: str | None = None,
) -> tuple[Any, str]:
    """Call Anthropic messages API with retries and telemetry.

    Returns (response, model_used).
    """
    from anthropic import Anthropic, APIStatusError

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    if budget is not None and hasattr(budget, "can_afford_next_call"):
        if not budget.can_afford_next_call():
            raise RuntimeError("evolution pass budget exhausted")

    client = Anthropic(api_key=key)
    call_group_id = uuid.uuid4()
    models = [model]
    if fallback_model and fallback_model != model:
        models.append(fallback_model)

    last_err: Exception | None = None
    global_attempt = 0

    for model_idx, current_model in enumerate(models):
        for retry_idx in range(MAX_RETRIES_PER_MODEL):
            global_attempt += 1
            kwargs: dict[str, Any] = {
                "model": current_model,
                "max_tokens": max_tokens,
                "messages": messages,
            }
            if system is not None:
                kwargs["system"] = system
            if tools is not None:
                kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice

            t0 = time.monotonic()
            status_code: int | None = None
            error_type: str | None = None
            outcome = "success"
            request_id: str | None = None
            in_tok: int | None = None
            out_tok: int | None = None
            cache_tok: int | None = None

            try:
                response = client.messages.create(**kwargs)
                latency_ms = int((time.monotonic() - t0) * 1000)
                status_code = 200
                request_id = _extract_request_id(response)
                in_tok, out_tok, cache_tok = _usage_fields(response)
                if budget is not None and hasattr(budget, "record_usage"):
                    budget.record_usage(current_model, in_tok, out_tok)
                log_attempt(
                    db,
                    call_group_id=call_group_id,
                    attempt=global_attempt,
                    call_site=call_site,
                    model=current_model,
                    status_code=status_code,
                    outcome=outcome,
                    error_type=None,
                    latency_ms=latency_ms,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cache_read_input_tokens=cache_tok,
                    request_id=request_id,
                )
                return response, current_model
            except APIStatusError as exc:
                latency_ms = int((time.monotonic() - t0) * 1000)
                status_code = exc.status_code
                error_type = _extract_error_type(exc)
                outcome = "error"
                log_attempt(
                    db,
                    call_group_id=call_group_id,
                    attempt=global_attempt,
                    call_site=call_site,
                    model=current_model,
                    status_code=status_code,
                    outcome=outcome,
                    error_type=error_type,
                    latency_ms=latency_ms,
                    input_tokens=None,
                    output_tokens=None,
                    cache_read_input_tokens=None,
                    request_id=_extract_request_id(exc),
                )
                last_err = exc
                if not _is_retriable_status(status_code):
                    raise
                if retry_idx < MAX_RETRIES_PER_MODEL - 1:
                    _sleep_backoff(retry_idx, _retry_after_seconds(exc))
                    continue
                break
            except Exception as exc:  # noqa: BLE001
                latency_ms = int((time.monotonic() - t0) * 1000)
                outcome = "network_error"
                log_attempt(
                    db,
                    call_group_id=call_group_id,
                    attempt=global_attempt,
                    call_site=call_site,
                    model=current_model,
                    status_code=None,
                    outcome=outcome,
                    error_type=type(exc).__name__,
                    latency_ms=latency_ms,
                    input_tokens=None,
                    output_tokens=None,
                    cache_read_input_tokens=None,
                    request_id=None,
                )
                last_err = exc
                if retry_idx < MAX_RETRIES_PER_MODEL - 1:
                    _sleep_backoff(retry_idx, None)
                    continue
                break

        if model_idx < len(models) - 1 and budget is not None:
            if hasattr(budget, "note_haiku_fallback"):
                budget.note_haiku_fallback()

    raise RuntimeError(f"LLM failed after retries: {last_err}") from last_err
