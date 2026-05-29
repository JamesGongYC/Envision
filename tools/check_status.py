#!/usr/bin/env python3
"""
check_status — Envision Day 4 utility.

Reports the state of the Curator kill switch (and any future per-skill
toggles). The Curator (Day 6) MUST consult `is_curator_enabled()` at the
start of every mutation cycle and abort if it returns False.

Convention (plan §8):
  ENVISION_CURATOR_ENABLED=false   →  Curator does not run mutations
  ENVISION_CURATOR_ENABLED=true    →  Curator runs normally
  (unset)                          →  treated as enabled (default-on)

This file is the single source of truth for that contract — import from
here in the Curator skill.
"""
from __future__ import annotations

import os
import sys


def _truthy(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on", "y", "t")


def is_curator_enabled() -> bool:
    """Default: enabled. Override with ENVISION_CURATOR_ENABLED=false."""
    return _truthy(os.environ.get("ENVISION_CURATOR_ENABLED"), default=True)


def main() -> int:
    print("Envision runtime status")
    print("-" * 40)
    curator = is_curator_enabled()
    print(f"  Curator mutation enabled : {curator}")
    print(f"    ENVISION_CURATOR_ENABLED = "
          f"{os.environ.get('ENVISION_CURATOR_ENABLED', '(unset → default true)')}")
    if not curator:
        print()
        print("  ⚠  Curator is HALTED. No mutation proposals will be generated.")
        print("     Existing pending proposals can still be reviewed/approved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
