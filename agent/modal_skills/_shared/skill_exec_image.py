"""Shared Modal image for detection skill execution (curator sandbox, shadow, cron)."""
from __future__ import annotations

from pathlib import Path

import modal

SKILL_EXEC_PIP_PACKAGES = (
    "psycopg[binary]",
    "shapely",
    "scikit-learn",
    "numpy",
    "httpx",
    "anthropic",
)


def build_skill_exec_image(
    *,
    agent_dir: Path | str | None = None,
    agent_lib: Path | str | None = None,
    skill_dir: Path | str | None = None,
    agent_remote_path: str = "/root/agent",
    agent_lib_remote_path: str = "/root/agent_lib",
    skill_remote_path: str = "/root/skill",
) -> modal.Image:
    """Base image for any context that exec's detection skill run(now, db)."""
    image = modal.Image.debian_slim(python_version="3.11").pip_install(
        *SKILL_EXEC_PIP_PACKAGES
    )
    if agent_dir:
        image = image.add_local_dir(str(agent_dir), remote_path=agent_remote_path)
    if agent_lib:
        image = image.add_local_dir(str(agent_lib), remote_path=agent_lib_remote_path)
    if skill_dir:
        image = image.add_local_dir(str(skill_dir), remote_path=skill_remote_path)
    # Must be last: ships this module into the container so app.py can import it.
    return image.add_local_python_source("skill_exec_image")
