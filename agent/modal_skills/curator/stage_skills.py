"""Stage detection skills into ~/.hermes/skills for curator reads."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

REPO_DETECT = Path("/root/repo_detect")
HERMES_SKILLS = Path(os.path.expanduser("~/.hermes/skills"))


def stage_detection_skills() -> None:
    if not REPO_DETECT.is_dir():
        raise RuntimeError(f"detect skills not found at {REPO_DETECT}")
    HERMES_SKILLS.mkdir(parents=True, exist_ok=True)
    for skill_dir in sorted(REPO_DETECT.iterdir()):
        if not skill_dir.is_dir():
            continue
        scripts = skill_dir / "scripts"
        if not scripts.is_dir():
            continue
        target = HERMES_SKILLS / skill_dir.name / "scripts"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(scripts, target)
    print(f"[curator] staged detection skills under {HERMES_SKILLS}")
