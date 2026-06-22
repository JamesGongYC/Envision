"""Promotion: write candidate surface to production run.py (operator gate)."""
from __future__ import annotations

import re
from pathlib import Path

from agent.evolution.skill_loader import SKILL_FOLDERS
from agent.evolution.skill_metadata import skill_id_to_folder
from agent.evolution.skill_surface import normalize_mutation_surface

REPO_ROOT = Path(__file__).resolve().parents[2]
MIN_SHADOW_EVALS = 20
APP_PY_MARKER = "<!-- ENVISION_APP_PY"


def _folder_for_skill(skill_id: str) -> str:
    return SKILL_FOLDERS.get(skill_id) or skill_id_to_folder(skill_id)


def modal_deploy_command(skill_id: str) -> str:
    folder = _folder_for_skill(skill_id)
    rel = f"agent/modal_skills/{folder}/app.py"
    return f"python -m modal deploy {rel}"


def run_py_path(skill_id: str, repo_root: Path | None = None) -> Path:
    root = repo_root or REPO_ROOT
    folder = _folder_for_skill(skill_id)
    return root / "agent" / "modal_skills" / folder / "run.py"


def skill_md_path(skill_id: str, repo_root: Path | None = None) -> Path:
    root = repo_root or REPO_ROOT
    folder = _folder_for_skill(skill_id)
    return root / "agent" / "modal_skills" / folder / "SKILL.md"


def app_py_path(skill_id: str, repo_root: Path | None = None) -> Path:
    root = repo_root or REPO_ROOT
    folder = _folder_for_skill(skill_id)
    return root / "agent" / "modal_skills" / folder / "app.py"


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


def _split_skill_md(full_md: str) -> tuple[str, str | None]:
    if APP_PY_MARKER not in full_md:
        return full_md, None
    head, rest = full_md.split(APP_PY_MARKER, 1)
    rest = rest.lstrip("\n")
    if rest.endswith("-->"):
        rest = rest[:-3]
    if rest.startswith("\n"):
        rest = rest[1:]
    return head.rstrip() + "\n", rest.strip()


def write_promoted_skill_bundle(
    skill_id: str,
    surface: str,
    skill_md: str,
    new_version: int,
    *,
    repo_root: Path | None = None,
) -> tuple[Path, Path | None, Path | None]:
    """Write run.py and optional SKILL.md / app.py for generated skills."""
    run_path = write_promoted_run_py(skill_id, surface, new_version, repo_root=repo_root)
    md_body, app_py = _split_skill_md(skill_md)
    md_path: Path | None = None
    app_path: Path | None = None
    if md_body.strip():
        md_path = skill_md_path(skill_id, repo_root)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_body, encoding="utf-8")
    if app_py:
        app_path = app_py_path(skill_id, repo_root)
        app_path.parent.mkdir(parents=True, exist_ok=True)
        app_path.write_text(app_py + "\n", encoding="utf-8")
    return run_path, md_path, app_path
