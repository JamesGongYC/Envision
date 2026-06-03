"""Load repo-root .env into os.environ (stdlib only; no python-dotenv)."""
from __future__ import annotations

import os
from pathlib import Path

# agent/lib/repo_env.py -> repo root is parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOADED = False


def repo_root() -> Path:
    """Envision repository root."""
    return _REPO_ROOT


def _parse_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            # .env is the local source of truth for dev scripts
            os.environ[key] = value


def load_repo_env() -> Path:
    """
    Load envision/.env, then viewer/.env.local for any keys still missing.
    Returns repo root path.
    """
    global _LOADED
    if _LOADED:
        return _REPO_ROOT
    _LOADED = True

    _parse_env_file(_REPO_ROOT / ".env")
    # Next.js local env (often has DATABASE_URL only)
    local = _REPO_ROOT / "viewer" / ".env.local"
    for raw in local.read_text(encoding="utf-8").splitlines() if local.is_file() else []:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and not os.environ.get(key):
            os.environ[key] = value

    return _REPO_ROOT
