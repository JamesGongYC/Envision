"""Runtime forecast and evolution dataclasses (Modal + harness)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass
class Forecast:
    id: UUID | str
    issued_at: datetime
    valid_from: datetime
    valid_until: datetime
    disaster_class: str
    geometry: str
    probability: float
    skill_id: str
    skill_version: int
    contributing_signal_ids: list[str]
    reasoning: str
    is_baseline: bool = False
    trace: dict[str, Any] | str = field(default_factory=dict)

    def trace_json(self) -> str:
        if isinstance(self.trace, str):
            return self.trace
        return json.dumps(self.trace)


@dataclass
class SkillLineage:
    id: UUID | str | None
    skill_id: str
    version: int | None
    source_code: str
    parent_skill_id: str | None = None
    skill_md: str = ""
    generation_method: str = "manual"
    status: str = "candidate"
    proposal_id: UUID | str | None = None
    created_at: datetime | None = None


@dataclass
class BacktestRun:
    id: UUID | str | None
    skill_id: str
    window_start: datetime
    window_end: datetime
    version: int | None = None
    lineage_id: UUID | str | None = None
    brier_score: float | None = None
    hits: int = 0
    false_positives: int = 0
    misses: int = 0
    forecasts_emitted: int = 0
    run_at: datetime | None = None


@dataclass
class ShadowForecast(Forecast):
    shadow_promotion_status: str = "evaluating"
    lineage_id: UUID | str | None = None


@dataclass
class ShadowEvaluation:
    id: UUID | str | None
    shadow_forecast_id: UUID | str
    outcome: str
    brier_contribution: float
    matched_ground_truth_id: UUID | str | None = None
    evaluated_at: datetime | None = None


@dataclass
class GroundTruthRow:
    id: UUID | str
    disaster_class: str
    occurred_at: datetime
    geom_geojson: str
