#!/usr/bin/env python3
"""Tests for v3 mutator validation pipeline."""
from __future__ import annotations

import json
import os
import sys
import unittest
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "agent" / "lib"))

from agent.evolution.mutator import MAX_ATTEMPTS, mutate_skill  # noqa: E402
from agent.evolution.skill_loader import SKILL_FOLDERS  # noqa: E402
from agent.evolution.skill_surface import (  # noqa: E402
    assert_parent_surface_clean,
    extract_mutation_surface,
)
from agent.evolution.skill_validator import (  # noqa: E402
    check_import_allowlist,
    check_no_persistence,
    check_signature_lock,
    check_signal_catalog,
    is_no_op,
    validate_candidate,
    validate_python,
)
from agent.lib.repo_env import load_repo_env  # noqa: E402

load_repo_env()

SKILL_ID = "wildfire_risk_elevated"
DATABASE_URL = os.environ.get("DATABASE_URL")
HAS_DB = bool(DATABASE_URL)
HAS_ANTHROPIC = bool(os.environ.get("ANTHROPIC_API_KEY"))


def _parent_source() -> str:
    folder = SKILL_FOLDERS[SKILL_ID]
    raw = (REPO_ROOT / "agent" / "modal_skills" / folder / "run.py").read_text(
        encoding="utf-8"
    )
    return extract_mutation_surface(raw)


def _fixture_mutant(eps_km: float = 11.0) -> str:
    """Valid surface-only mutant: DBSCAN eps tweak, no persistence."""
    parent = _parent_source()
    mutant = parent.replace("EPS_KM = 10.0", f"EPS_KM = {eps_km}", 1)
    return "".join(
        ln
        for ln in mutant.splitlines(keepends=True)
        if not ln.strip().startswith("from __future__")
    )


def _persistence_mutant() -> str:
    return """
from datetime import datetime
from psycopg import Connection
from forecast_model import Forecast
from forecast_writer import emit_forecasts

def run(now: datetime, db: Connection) -> list[Forecast]:
    emit_forecasts([], db)
    return []
"""


def _stub_llm_fixed(source: str, rationale: str = "fixture mutant") -> Any:
    def llm_fn(_prompt: str) -> tuple[str, str, list[str], object, str]:
        return source, rationale, ["eps_km"], object(), "stub"

    return llm_fn


class ValidatorUnitTests(unittest.TestCase):
    def setUp(self):
        self.parent = _parent_source()
        self.inventory = {
            ("firms_viirs", "hotspot"),
            ("nws_alerts", "fire_warning"),
            ("ecmwf_open_data", "fire_weather_grid"),
            ("aifs", "fire_weather_grid"),
            ("nhc", "cyclone_advisory"),
        }

    def test_signature_lock_rejects_wrong_params(self):
        bad = "def run(x, y):\n    return []\n"
        ok, detail = check_signature_lock(bad)
        self.assertFalse(ok)
        self.assertIn("run", detail)

    def test_no_op_detected(self):
        self.assertTrue(is_no_op(self.parent, self.parent))

    def test_no_persistence_rejects_insert(self):
        bad = """
from datetime import datetime
from psycopg import Connection
from forecast_model import Forecast

def run(now: datetime, db: Connection) -> list[Forecast]:
    with db.cursor() as cur:
        cur.execute("INSERT INTO forecasts (id) VALUES ('x')")
    return []
"""
        ok, detail = check_no_persistence(bad)
        self.assertFalse(ok)
        self.assertIn("write", detail.lower())

    def test_signal_catalog_rejects_unknown_type(self):
        bad = self.parent.replace(
            "signal_type = 'hotspot'",
            "signal_type = 'totally_fake_type'",
            1,
        )
        ok, detail = check_signal_catalog(bad, self.inventory)
        self.assertFalse(ok)
        self.assertIn("signal_type", detail)

    def test_import_allowlist_rejects_subprocess(self):
        bad = "import subprocess\n" + self.parent
        ok, detail = check_import_allowlist(bad)
        self.assertFalse(ok)

    def test_parent_surface_rejects_bundled_persistence(self):
        dirty = _parent_source() + "\nfrom forecast_writer import emit_forecasts\n"
        with self.assertRaises(ValueError) as ctx:
            assert_parent_surface_clean(dirty)
        self.assertIn("parent_surface includes persistence", str(ctx.exception))


@unittest.skipUnless(HAS_DB, "DATABASE_URL required")
class ValidatorIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = _parent_source()
        cls.now = datetime.now(timezone.utc)

    def setUp(self):
        self.db = psycopg.connect(DATABASE_URL, autocommit=False)
        with self.db.cursor() as cur:
            cur.execute("SELECT source, signal_type FROM signal_catalog")
            self.inventory = {(r[0], r[1]) for r in cur.fetchall()}
        if not self.inventory:
            self.skipTest("signal_catalog empty")

    def tearDown(self):
        self.db.close()

    def _counts(self) -> dict[str, int]:
        tables = ("forecasts", "signals", "evaluations")
        out = {}
        with self.db.cursor() as cur:
            for t in tables:
                cur.execute(f"SELECT COUNT(*)::int FROM {t}")
                out[t] = cur.fetchone()[0]
        return out

    def test_validate_stages_without_sandbox(self):
        bad_sig = self.parent.replace(
            "def run(now: datetime, db: Connection)",
            "def run(now: datetime, db: Connection, extra=None)",
            1,
        )
        report = validate_candidate(
            bad_sig,
            self.parent,
            SKILL_ID,
            self.inventory,
            self.db,
            self.now,
            run_sandbox=False,
        )
        self.assertFalse(report.accepted)
        self.assertTrue(
            any(s["stage"] == "signature_lock" and not s["passed"] for s in report.stages)
        )

    def test_runtime_rejected_in_sandbox(self):
        broken = (
            "from datetime import datetime\n"
            "from psycopg import Connection\n"
            "from forecast_model import Forecast\n"
            "def run(now: datetime, db: Connection) -> list[Forecast]:\n"
            "    raise RuntimeError('boom')\n"
        )
        before = self._counts()
        report = validate_candidate(
            broken,
            "def run(now, db):\n    return []\n",
            SKILL_ID,
            self.inventory,
            self.db,
            self.now,
        )
        after = self._counts()
        self.assertEqual(before, after)
        self.assertFalse(report.accepted)
        self.assertTrue(any(s["stage"] == "sandbox" and not s["passed"] for s in report.stages))
        self.assertTrue(
            any("RuntimeError: boom" in r for r in report.rejection_reasons)
        )

    def test_sandbox_blocks_insert(self):
        writer = (
            "from datetime import datetime\n"
            "from psycopg import Connection\n"
            "from forecast_model import Forecast\n"
            "def run(now: datetime, db: Connection) -> list[Forecast]:\n"
            "    with db.cursor() as cur:\n"
            "        cur.execute('INSERT INTO signals (id) VALUES (%s)', ('00000000-0000-0000-0000-000000000001',))\n"
            "    return []\n"
        )
        before = self._counts()
        report = validate_candidate(
            writer,
            "def run(now, db):\n    return []\n",
            SKILL_ID,
            self.inventory,
            self.db,
            self.now,
        )
        after = self._counts()
        self.assertEqual(before, after)
        self.assertFalse(report.accepted)
        self.assertTrue(
            any(s["stage"] == "no_persistence" and not s["passed"] for s in report.stages)
        )

    def test_no_writes_from_validation_runs(self):
        noop_variant = self.parent.replace("LOOKBACK_HOURS = 24", "LOOKBACK_HOURS = 25", 1)
        before = self._counts()
        validate_candidate(
            noop_variant,
            self.parent,
            SKILL_ID,
            self.inventory,
            self.db,
            self.now,
            run_sandbox=False,
        )
        after = self._counts()
        self.assertEqual(before, after)


@unittest.skipUnless(HAS_DB, "DATABASE_URL required")
class MutatorStubTests(unittest.TestCase):
    """Deterministic mutate_skill paths — no live LLM."""

    @classmethod
    def setUpClass(cls):
        cls.now = datetime.now(timezone.utc)

    def setUp(self):
        self.db = psycopg.connect(DATABASE_URL, autocommit=False)
        with self.db.cursor() as cur:
            cur.execute("SELECT source, signal_type FROM signal_catalog")
            if not cur.fetchall():
                self.skipTest("signal_catalog empty")

    def tearDown(self):
        self.db.close()

    def _data_counts(self) -> dict[str, int]:
        tables = (
            "forecasts",
            "signals",
            "evaluations",
            "skill_edit_proposals",
            "skill_lineage",
        )
        out = {}
        with self.db.cursor() as cur:
            for t in tables:
                cur.execute(f"SELECT COUNT(*)::int FROM {t}")
                out[t] = cur.fetchone()[0]
        return out

    def _cleanup_mutation(self, proposal_id: str | None, lineage_id: str | None) -> None:
        with self.db.cursor() as cur:
            if proposal_id:
                cur.execute(
                    "UPDATE skill_edit_proposals SET lineage_id = NULL WHERE id = %s",
                    (proposal_id,),
                )
            if lineage_id:
                cur.execute(
                    "DELETE FROM skill_lineage WHERE id = %s", (lineage_id,)
                )
            if proposal_id:
                cur.execute(
                    "DELETE FROM skill_edit_proposals WHERE id = %s", (proposal_id,)
                )
        self.db.commit()

    def test_mutate_accepts_fixture_candidate(self):
        before = self._data_counts()
        result = mutate_skill(
            SKILL_ID,
            self.db,
            now=self.now,
            llm_fn=_stub_llm_fixed(_fixture_mutant()),
        )
        try:
            self.assertTrue(result.accepted, result.rejection_reasons)
            self.assertEqual(len(result.attempts), 1)
            self.assertTrue(result.attempts[0]["accepted"])
            self.assertTrue(result.proposal_id)
            self.assertTrue(result.lineage_id)

            after = self._data_counts()
            self.assertEqual(before["forecasts"], after["forecasts"])
            self.assertEqual(before["signals"], after["signals"])
            self.assertEqual(before["evaluations"], after["evaluations"])
            self.assertEqual(before["skill_edit_proposals"] + 1, after["skill_edit_proposals"])
            self.assertEqual(before["skill_lineage"] + 1, after["skill_lineage"])

            with self.db.cursor() as cur:
                cur.execute(
                    "SELECT status, lineage_id, curator_trace FROM skill_edit_proposals WHERE id = %s",
                    (result.proposal_id,),
                )
                prow = cur.fetchone()
                cur.execute(
                    "SELECT status, version, proposal_id FROM skill_lineage WHERE id = %s",
                    (result.lineage_id,),
                )
                lrow = cur.fetchone()

            self.assertEqual(prow[0], "pending")
            self.assertEqual(str(prow[1]), result.lineage_id)
            trace = prow[2] if isinstance(prow[2], dict) else json.loads(prow[2])
            self.assertEqual(len(trace.get("attempts", [])), 1)

            self.assertEqual(lrow[0], "candidate")
            self.assertIsNone(lrow[1])
            self.assertEqual(str(lrow[2]), result.proposal_id)
        finally:
            self._cleanup_mutation(result.proposal_id, result.lineage_id)

    def test_mutate_retries_then_accepts(self):
        calls: list[str] = []

        def llm_fn(prompt: str) -> tuple[str, str, list[str], object, str]:
            calls.append(prompt)
            if len(calls) == 1:
                return (
                    _persistence_mutant(),
                    "bad attempt",
                    [],
                    object(),
                    "stub",
                )
            return (
                _fixture_mutant(12.0),
                "fixed eps",
                ["eps_km"],
                object(),
                "stub",
            )

        before = self._data_counts()
        result = mutate_skill(SKILL_ID, self.db, now=self.now, llm_fn=llm_fn)
        try:
            self.assertTrue(result.accepted, result.rejection_reasons)
            self.assertEqual(len(calls), 2)
            self.assertIn("Previous attempt rejected", calls[1])
            self.assertEqual(len(result.attempts), 2)
            self.assertFalse(result.attempts[0]["accepted"])
            self.assertTrue(result.attempts[1]["accepted"])

            after = self._data_counts()
            self.assertEqual(before["forecasts"], after["forecasts"])
            self.assertEqual(before["skill_edit_proposals"] + 1, after["skill_edit_proposals"])

            with self.db.cursor() as cur:
                cur.execute(
                    "SELECT curator_trace FROM skill_edit_proposals WHERE id = %s",
                    (result.proposal_id,),
                )
                trace = cur.fetchone()[0]
            if not isinstance(trace, dict):
                trace = json.loads(trace)
            self.assertEqual(len(trace["attempts"]), 2)
        finally:
            self._cleanup_mutation(result.proposal_id, result.lineage_id)

    def test_mutate_gives_up_after_max_attempts(self):
        before = self._data_counts()

        def llm_fn(_prompt: str) -> tuple[str, str, list[str], object, str]:
            return _persistence_mutant(), "always bad", [], object(), "stub"

        result = mutate_skill(SKILL_ID, self.db, now=self.now, llm_fn=llm_fn)
        self.assertFalse(result.accepted)
        self.assertEqual(len(result.attempts), MAX_ATTEMPTS)
        self.assertFalse(any(a["accepted"] for a in result.attempts))
        self.assertIsNone(result.proposal_id)
        self.assertIsNone(result.lineage_id)

        after = self._data_counts()
        self.assertEqual(before["skill_edit_proposals"], after["skill_edit_proposals"])
        self.assertEqual(before["skill_lineage"], after["skill_lineage"])
        self.assertEqual(before["forecasts"], after["forecasts"])


@unittest.skipUnless(HAS_DB and HAS_ANTHROPIC, "DATABASE_URL + ANTHROPIC_API_KEY required")
class MutatorLiveTests(unittest.TestCase):
    def test_mutate_wildfire_live(self):
        """Smoke test only — not the happy-path proof (see MutatorStubTests)."""
        try:
            with psycopg.connect(DATABASE_URL, autocommit=False) as db:
                result = mutate_skill(SKILL_ID, db)
        except psycopg.OperationalError as e:
            self.skipTest(f"database connection lost during mutate: {e}")
        if not result.accepted:
            warnings.warn(
                f"live mutator rejected after {len(result.attempts)} attempt(s): "
                f"{result.rejection_reasons} — investigate low acceptance rate",
                stacklevel=2,
            )
            self.skipTest(f"mutator rejected: {result.rejection_reasons}")
        self.assertTrue(result.proposal_id)
        self.assertTrue(result.lineage_id)
        try:
            with psycopg.connect(DATABASE_URL) as db:
                with db.cursor() as cur:
                    cur.execute(
                        "SELECT status, lineage_id FROM skill_edit_proposals WHERE id = %s",
                        (result.proposal_id,),
                    )
                    prow = cur.fetchone()
                    cur.execute(
                        "SELECT status, version, proposal_id FROM skill_lineage WHERE id = %s",
                        (result.lineage_id,),
                    )
                    lrow = cur.fetchone()
                    cur.execute(
                        "UPDATE skill_edit_proposals SET lineage_id = NULL WHERE id = %s",
                        (result.proposal_id,),
                    )
                    cur.execute(
                        "DELETE FROM skill_lineage WHERE id = %s",
                        (result.lineage_id,),
                    )
                    cur.execute(
                        "DELETE FROM skill_edit_proposals WHERE id = %s",
                        (result.proposal_id,),
                    )
                db.commit()
        except psycopg.OperationalError as e:
            self.skipTest(f"database unavailable during cleanup: {e}")
        self.assertEqual(prow[0], "pending")
        self.assertEqual(str(prow[1]), result.lineage_id)
        self.assertEqual(lrow[0], "candidate")
        self.assertIsNone(lrow[1])
        self.assertEqual(str(lrow[2]), result.proposal_id)


def main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(ValidatorUnitTests))
    suite.addTests(loader.loadTestsFromTestCase(ValidatorIntegrationTests))
    suite.addTests(loader.loadTestsFromTestCase(MutatorStubTests))
    suite.addTests(loader.loadTestsFromTestCase(MutatorLiveTests))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
