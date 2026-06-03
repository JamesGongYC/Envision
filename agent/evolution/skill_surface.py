"""Mutation surface: pure run.py body without CLI / persistence scaffolding."""
from __future__ import annotations

import re
from pathlib import Path

from agent.evolution.skill_loader import SKILL_FOLDERS
from agent.evolution.skill_validator import check_no_persistence

REPO_ROOT = Path(__file__).resolve().parents[2]

_PERSISTENCE_MSG = (
    "parent_surface includes persistence — fix input assembly (§2), not the prompt"
)


def extract_mutation_surface(source: str) -> str:
    """Return run.py content up to (excluding) ``def main`` / ``if __name__``."""
    lines = source.splitlines(keepends=True)
    cut = len(lines)
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("def main(") or stripped.startswith("def main ("):
            cut = i
            break
    surface = "".join(lines[:cut]).rstrip()
    if surface:
        surface += "\n"
    return normalize_mutation_surface(surface)


def normalize_mutation_surface(source: str) -> str:
    """Drop boilerplate the validator rejects but that is not skill logic."""
    kept = [
        ln
        for ln in source.splitlines(keepends=True)
        if not ln.strip().startswith("from __future__")
    ]
    out = "".join(kept).rstrip()
    return f"{out}\n" if out else ""


def assert_parent_surface_clean(parent_surface: str) -> None:
    """Pre-send guard: surface must not contain persistence (validator check #4)."""
    ok, detail = check_no_persistence(parent_surface)
    if not ok:
        raise ValueError(f"{_PERSISTENCE_MSG}: {detail}")
    if "forecast_writer" in parent_surface and re.search(
        r"\bemit_forecasts\s*\(", parent_surface
    ):
        raise ValueError(_PERSISTENCE_MSG)


def load_parent_surface_from_disk(skill_id: str) -> tuple[str, int]:
    folder = SKILL_FOLDERS[skill_id]
    run_py = REPO_ROOT / "agent" / "modal_skills" / folder / "run.py"
    raw = run_py.read_text(encoding="utf-8")
    m = re.search(r"^SKILL_VERSION\s*=\s*(\d+)", raw, re.MULTILINE)
    version = int(m.group(1)) if m else 1
    surface = extract_mutation_surface(raw)
    assert_parent_surface_clean(surface)
    return surface, version
