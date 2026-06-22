"""Parse metadata constants from detection skill source."""
from __future__ import annotations

import ast
import re
from datetime import timedelta

from agent.evolution.backtest_harness import SKILL_CADENCE

SKILL_DISASTER_CLASS: dict[str, str] = {
    "wildfire_risk_elevated": "wildfire",
    "wildfire_rapid_growth": "wildfire",
    "typhoon_intensifying": "typhoon",
    "typhoon_landfall_imminent": "typhoon",
}


def _parse_constant(source: str, name: str) -> ast.Constant | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    if isinstance(node.value, ast.Constant):
                        return node.value
    return None


def parse_disaster_class(source: str, skill_id: str) -> str:
    val = _parse_constant(source, "DISASTER_CLASS")
    if val and isinstance(val.value, str):
        return val.value
    if skill_id in SKILL_DISASTER_CLASS:
        return SKILL_DISASTER_CLASS[skill_id]
    raise KeyError(f"no DISASTER_CLASS for {skill_id!r}")


def parse_cadence_minutes(source: str, skill_id: str) -> int:
    val = _parse_constant(source, "SKILL_CADENCE_MINUTES")
    if val and isinstance(val.value, int):
        return int(val.value)
    if skill_id in SKILL_CADENCE:
        return int(SKILL_CADENCE[skill_id].total_seconds() // 60)
    raise KeyError(f"no SKILL_CADENCE_MINUTES for {skill_id!r}")


def cadence_timedelta(source: str, skill_id: str) -> timedelta:
    return timedelta(minutes=parse_cadence_minutes(source, skill_id))


def skill_id_to_folder(skill_id: str) -> str:
    return skill_id.replace("_", "-")


def has_forbidden_bootstrap(source: str) -> bool:
    if re.search(r"Path\s*\(\s*__file__\s*\)", source):
        return True
    return bool(re.search(r"^\s*Path\s*\(\s*__file__\s*\)", source, re.MULTILINE))
