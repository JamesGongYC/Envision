"""Resolve skill/shared directories for local dev and Modal (/root/app.py)."""
from __future__ import annotations

import os


def skill_and_shared_dirs() -> tuple[str, str]:
    root = os.path.dirname(os.path.abspath(__file__))
    shared = os.path.join(root, "shared")
    if not os.path.isfile(os.path.join(shared, "image.py")):
        shared = os.path.join(os.path.dirname(root), "_shared")
    skill = root
    if os.path.isfile(os.path.join(root, "skill", "run.py")):
        skill = os.path.join(root, "skill")
    return skill, shared
