#!/usr/bin/env python3
"""Run only the live Sonnet mutator smoke test (MutatorLiveTests)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "agent" / "lib"))

from agent.evolution.test_mutator import MutatorLiveTests  # noqa: E402
from agent.lib.repo_env import load_repo_env  # noqa: E402


def main() -> int:
    load_repo_env()
    suite = unittest.TestSuite()
    suite.addTest(MutatorLiveTests("test_mutate_wildfire_live"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
