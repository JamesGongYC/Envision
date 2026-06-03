"""Dataclass mirrors of Envision SQL tables — canonical types in agent.lib.forecast_model."""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from agent.lib.forecast_model import (  # noqa: E402
    BacktestRun,
    Forecast,
    GroundTruthRow,
    ShadowEvaluation,
    ShadowForecast,
    SkillLineage,
)

__all__ = [
    "BacktestRun",
    "Forecast",
    "GroundTruthRow",
    "ShadowEvaluation",
    "ShadowForecast",
    "SkillLineage",
]
