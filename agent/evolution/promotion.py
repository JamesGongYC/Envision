"""Promotion: write candidate surface to production run.py (operator gate)."""
from __future__ import annotations

import re
from pathlib import Path

from agent.evolution.skill_loader import SKILL_FOLDERS
from agent.evolution.skill_surface import normalize_mutation_surface

REPO_ROOT = Path(__file__).resolve().parents[2]
MIN_SHADOW_EVALS = 20


def modal_deploy_command(skill_id: str) -> str:
    folder = SKILL_FOLDERS.get(skill_id)
    if not folder:
        raise KeyError(f"unknown skill_id {skill_id!r}")
    rel = f"agent/modal_skills/{folder}/app.py"
    return f"python -m modal deploy {rel}"


def run_py_path(skill_id: str, repo_root: Path | None = None) -> Path:
    root = repo_root or REPO_ROOT
    folder = SKILL_FOLDERS[skill_id]
    return root / "agent" / "modal_skills" / folder / "run.py"


def bump_skill_version(source: str, new_version: int) -> str:
    if re.search(r"^SKILL_VERSION\s*=", source, re.MULTILINE):
        return re.sub(
            r"^SKILL_VERSION\s*=\s*\d+",
            f"SKILL_VERSION = {new_version}",
            source,
            count=1,
            flags=re.MULTILINE,
        )
    return f"SKILL_VERSION = {new_version}\n" + source


def write_promoted_run_py(
    skill_id: str,
    surface: str,
    new_version: int,
    *,
    repo_root: Path | None = None,
) -> Path:
    """Write normalized mutation surface to modal_skills/<folder>/run.py."""
    path = run_py_path(skill_id, repo_root)
    normalized = normalize_mutation_surface(surface)
    content = bump_skill_version(normalized, new_version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
