"""Load detection skill run() without importing Modal app.py."""
from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_LIB = REPO_ROOT / "agent" / "lib"
MODAL_SKILLS = REPO_ROOT / "agent" / "modal_skills"

# DB skill_id (underscores) -> modal_skills folder (hyphens)
SKILL_FOLDERS: dict[str, str] = {
    "wildfire_risk_elevated": "wildfire-risk-elevated",
    "wildfire_rapid_growth": "wildfire-rapid-growth",
    "typhoon_intensifying": "typhoon-intensifying",
    "typhoon_landfall_imminent": "typhoon-landfall-imminent",
}


def _ensure_paths() -> None:
    for p in (str(REPO_ROOT), str(AGENT_LIB)):
        if p not in sys.path:
            sys.path.insert(0, p)


def load_skill_run(skill_id: str) -> Callable[[datetime, object], list]:
    """Return the skill's run(now, db) function."""
    folder = SKILL_FOLDERS.get(skill_id)
    if not folder:
        raise KeyError(f"unknown skill_id {skill_id!r}; known: {list(SKILL_FOLDERS)}")

    run_path = MODAL_SKILLS / folder / "run.py"
    if not run_path.is_file():
        raise FileNotFoundError(run_path)

    _ensure_paths()
    spec = importlib.util.spec_from_file_location(f"envision_skill_{folder}", run_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {run_path}")

    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    run_fn = getattr(mod, "run", None)
    if run_fn is None:
        raise AttributeError(f"{run_path} has no run()")
    return run_fn


def load_run_from_source(source: str, skill_id: str) -> Callable[[datetime, object], list]:
    """Load run(now, db) from in-memory Python source (sandbox / mutator)."""
    import uuid as _uuid

    _ensure_paths()
    mod_name = f"envision_mutant_{_uuid.uuid4().hex[:12]}"
    mod = importlib.util.module_from_spec(
        importlib.util.spec_from_loader(mod_name, loader=None)
    )
    mod.__file__ = f"<mutant:{skill_id}>"
    sys.modules[mod_name] = mod
    compiled = compile(source, mod.__file__, "exec")
    exec(compiled, mod.__dict__)  # noqa: S102
    run_fn = getattr(mod, "run", None)
    if run_fn is None:
        raise AttributeError(f"mutant for {skill_id!r} has no run()")
    return run_fn
