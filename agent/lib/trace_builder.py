"""Shared trace JSONB builders for detection skills and the Curator."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

SOFT_CAP_BYTES = 12_288
HARD_CAP_BYTES = 16_384

DETECTION_REQUIRED = (
    "now",
    "inputs",
    "intermediate",
    "geometry_steps",
    "probability_components",
)

CURATOR_REQUIRED = ("brier_stats_observed", "ast_validation")

# Deterministic truncation order for detection traces (field paths).
DETECTION_TRUNCATION_PATHS = [
    ("intermediate", "growing_cells"),
    ("intermediate", "selected_clusters"),
    ("intermediate", "populated_places_in_cone"),
    ("intermediate", "pressure_history"),
    ("geometry_steps", None),
    ("inputs", "active_storms"),
]


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalar
        return value.item()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


def _serialized_size(obj: dict) -> int:
    return len(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _get_nested(obj: dict, path: tuple[str, str | None]) -> Any:
    if path[1] is None:
        return obj.get(path[0])
    container = obj.get(path[0])
    if isinstance(container, dict):
        return container.get(path[1])
    return None


def _set_nested(obj: dict, path: tuple[str, str | None], value: Any) -> None:
    if path[1] is None:
        obj[path[0]] = value
        return
    if path[0] not in obj or not isinstance(obj[path[0]], dict):
        obj[path[0]] = {}
    obj[path[0]][path[1]] = value


def _truncate_detection_field(obj: dict, path: tuple[str, str | None]) -> bool:
    """Truncate one field; return True if something was changed."""
    if path[1] is None:
        steps = obj.get("geometry_steps")
        if not isinstance(steps, list) or not steps:
            return False
        if len(steps) > 1:
            obj["geometry_steps"] = steps[:1]
            return True
        step = steps[0]
        if isinstance(step, dict):
            for key in list(step.keys()):
                if key != "name" and isinstance(step[key], list) and len(step[key]) > 1:
                    step[key] = step[key][:1]
                    return True
        return False

    container = obj.get(path[0])
    if not isinstance(container, dict):
        return False
    val = container.get(path[1])
    if not isinstance(val, list):
        return False
    if len(val) > 0:
        container[path[1]] = val[: max(0, len(val) // 2)]
        return True
    return False


def _truncate_curator(obj: dict) -> bool:
    resp = obj.get("llm_response_full")
    if isinstance(resp, str) and len(resp) > 0:
        new_len = max(0, len(resp) // 2)
        obj["llm_response_full"] = resp[:new_len]
        return True
    return False


def _apply_soft_cap(obj: dict, *, curator: bool = False) -> dict:
    if _serialized_size(obj) <= SOFT_CAP_BYTES:
        return obj
    obj["_truncated"] = True
    while _serialized_size(obj) > SOFT_CAP_BYTES:
        changed = False
        if curator:
            changed = _truncate_curator(obj)
        else:
            for path in DETECTION_TRUNCATION_PATHS:
                if _truncate_detection_field(obj, path):
                    changed = True
                    break
        if not changed:
            break
    if _serialized_size(obj) > HARD_CAP_BYTES:
        obj = {"now": obj.get("now"), "_truncated": True, "error": "trace_hard_cap_exceeded"}
    return obj


class TraceBuilder:
    """Build forecasts.trace JSONB for detection skills."""

    def __init__(self, now: datetime, skill_id: str) -> None:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        self._now_iso = now.isoformat()
        self._skill_id = skill_id
        self._inputs: dict[str, Any] = {}
        self._intermediate: dict[str, Any] = {}
        self._geometry_steps: list[dict[str, Any]] = []
        self._probability_components: dict[str, Any] = {}

    def set_inputs(self, **kwargs: Any) -> None:
        self._inputs.update(kwargs)

    def set_intermediate(self, **kwargs: Any) -> None:
        self._intermediate.update(kwargs)

    def add_geometry_step(self, name: str, **kwargs: Any) -> None:
        step = {"name": name, **_json_safe(kwargs)}
        self._geometry_steps.append(step)

    def set_probability_components(self, **kwargs: Any) -> None:
        self._probability_components.update(kwargs)

    def fork(self) -> TraceBuilder:
        """Copy run-level state for a single forecast emission."""
        child = TraceBuilder.__new__(TraceBuilder)
        child._now_iso = self._now_iso
        child._skill_id = self._skill_id
        child._inputs = _json_safe(dict(self._inputs))
        child._intermediate = _json_safe(dict(self._intermediate))
        child._geometry_steps = _json_safe(list(self._geometry_steps))
        child._probability_components = {}
        return child

    def build(self) -> dict:
        trace = {
            "now": self._now_iso,
            "inputs": _json_safe(self._inputs),
            "intermediate": _json_safe(self._intermediate),
            "geometry_steps": _json_safe(self._geometry_steps),
            "probability_components": _json_safe(self._probability_components),
        }
        missing = [k for k in DETECTION_REQUIRED if k not in trace or trace[k] in (None,)]
        if missing:
            raise ValueError(f"TraceBuilder missing required keys: {missing}")
        return _apply_soft_cap(trace, curator=False)


class CuratorTraceBuilder:
    """Build skill_edit_proposals.curator_trace JSONB."""

    def __init__(self) -> None:
        self._brier_stats: dict[str, Any] = {}
        self._ast_validation: dict[str, Any] = {
            "passed": False,
            "warnings": [],
            "errors": [],
        }
        self._llm_hash: str | None = None
        self._llm_response: str | None = None
        self._rejection_reasons: list[str] = []
        self._rationale: str | None = None
        self._validation_stages: list[dict[str, Any]] = []
        self._mutation_targets: list[str] = []
        self._llm_model: str | None = None
        self._mutation_attempts: list[dict[str, Any]] = []

    def set_brier_stats(self, stats: dict[str, Any]) -> None:
        self._brier_stats = stats

    def set_ast_validation(
        self,
        *,
        passed: bool,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
    ) -> None:
        self._ast_validation = {
            "passed": passed,
            "warnings": list(warnings or []),
            "errors": list(errors or []),
        }

    def set_llm_hash(self, prompt_hash: str) -> None:
        self._llm_hash = prompt_hash

    def set_llm_response(self, text: str) -> None:
        self._llm_response = text

    def add_rejection_reason(self, reason: str) -> None:
        self._rejection_reasons.append(reason)

    def set_rationale(self, rationale: str) -> None:
        self._rationale = rationale

    def set_mutation_targets(self, targets: list[str]) -> None:
        self._mutation_targets = list(targets)

    def set_llm_model(self, model: str) -> None:
        self._llm_model = model

    def set_validation_stages(self, stages: list[dict[str, Any]]) -> None:
        self._validation_stages = list(stages)

    def set_mutation_attempts(self, attempts: list[dict[str, Any]]) -> None:
        self._mutation_attempts = list(attempts)

    def add_validation_stage(
        self, stage: str, *, passed: bool, detail: str = ""
    ) -> None:
        self._validation_stages.append({
            "stage": stage,
            "passed": passed,
            "detail": detail,
        })

    def build(self) -> dict:
        trace: dict[str, Any] = {
            "brier_stats_observed": _json_safe(self._brier_stats),
            "ast_validation": _json_safe(self._ast_validation),
            "rejection_reasons": _json_safe(self._rejection_reasons),
        }
        if self._rationale is not None:
            trace["rationale"] = self._rationale
        if self._validation_stages:
            trace["validation_stages"] = _json_safe(self._validation_stages)
        if self._mutation_attempts:
            trace["attempts"] = _json_safe(self._mutation_attempts)
        if self._mutation_targets:
            trace["mutation_targets"] = _json_safe(self._mutation_targets)
        if self._llm_model is not None:
            trace["llm_model"] = self._llm_model
        if self._llm_hash is not None:
            trace["llm_input_prompt_hash"] = self._llm_hash
        if self._llm_response is not None:
            trace["llm_response_full"] = self._llm_response
        missing = [k for k in CURATOR_REQUIRED if k not in trace]
        if missing:
            raise ValueError(f"CuratorTraceBuilder missing required keys: {missing}")
        return _apply_soft_cap(trace, curator=True)
