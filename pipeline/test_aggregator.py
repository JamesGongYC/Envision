#!/usr/bin/env python3
"""T3 aggregator unit tests — pure; no DB writes."""
from __future__ import annotations

import ast
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "agent" / "lib"))

from agent.lib.forecast_model import Forecast  # noqa: E402
from agent.evolution.skill_validator import (  # noqa: E402
    _ALLOWED_IMPORT_ROOTS,
    _BANNED_IMPORT_ROOTS,
    check_import_allowlist,
    check_no_persistence,
)
from pipeline.aggregator import AggregatorConfig, aggregate  # noqa: E402


def _f(
    *,
    skill_id: str,
    p: float,
    disaster_class: str = "wildfire",
    lon: float = -122.4,
    lat: float = 37.8,
    fid: str | None = None,
) -> Forecast:
    return Forecast(
        id=fid or str(uuid.uuid4()),
        issued_at=datetime.now(timezone.utc),
        valid_from=datetime.now(timezone.utc),
        valid_until=datetime.now(timezone.utc),
        disaster_class=disaster_class,
        geometry=f'{{"type":"Point","coordinates":[{lon},{lat}]}}',
        probability=p,
        skill_id=skill_id,
        skill_version=1,
        contributing_signal_ids=[],
        reasoning="test",
    )


CFG = AggregatorConfig(corroboration_radius_km=50.0, p_cap=0.85)


class AggregateRuleTests(unittest.TestCase):
    def test_corroboration_noisy_or(self):
        a = _f(skill_id="skill_a", p=0.4, fid="a")
        b = _f(skill_id="skill_b", p=0.5, fid="b")
        out = aggregate([a, b], {"skill_a": 0.5, "skill_b": 0.5}, CFG)
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0].probability, 0.7, places=9)

    def test_corroboration_clamped_to_cap(self):
        members = [
            _f(skill_id="s1", p=0.7, fid="1"),
            _f(skill_id="s2", p=0.7, fid="2"),
            _f(skill_id="s3", p=0.7, fid="3"),
        ]
        rates = {"s1": 0.5, "s2": 0.5, "s3": 0.5}
        out = aggregate(members, rates, CFG)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].probability, 0.85)

    def test_conflict_hit_rate_wins(self):
        hi = _f(
            skill_id="hi_skill",
            p=0.55,
            disaster_class="wildfire",
            fid="hi",
        )
        lo = _f(
            skill_id="lo_skill",
            p=0.6,
            disaster_class="typhoon",
            fid="lo",
        )
        out = aggregate(
            [hi, lo],
            {"hi_skill": 0.7, "lo_skill": 0.4},
            CFG,
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].skill_id, "hi_skill")
        self.assertEqual(out[0].probability, 0.55)

    def test_single_detection_unchanged(self):
        one = _f(skill_id="solo", p=0.6, fid="solo")
        out = aggregate([one], {"solo": 0.9}, CFG)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].probability, 0.6)
        self.assertEqual(str(out[0].id), "solo")

    def test_underconfident_never_lowered(self):
        # Skill p below its hit-rate; single path must keep skill p (not hit-rate).
        one = _f(skill_id="under", p=0.3, fid="u")
        out = aggregate([one], {"under": 0.8}, CFG)
        self.assertEqual(out[0].probability, 0.3)

        # Corroboration must not go below max individual p.
        a = _f(skill_id="a", p=0.4, fid="a")
        b = _f(skill_id="b", p=0.5, fid="b")
        out2 = aggregate([a, b], {"a": 0.9, "b": 0.9}, CFG)
        self.assertGreaterEqual(out2[0].probability, 0.5)

    def test_shared_code_rule_and_agent_same_p(self):
        one = _f(skill_id="shared", p=0.61, fid="shared")
        rates = {"shared": 0.4}
        rule_out = aggregate([one], rates, CFG)
        agent_out = aggregate([one], rates, CFG)
        self.assertEqual(rule_out[0].probability, agent_out[0].probability)
        self.assertEqual(rule_out[0].probability, 0.61)

    def test_determinism(self):
        a = _f(skill_id="skill_a", p=0.4, fid="a")
        b = _f(skill_id="skill_b", p=0.5, fid="b")
        rates = {"skill_a": 0.5, "skill_b": 0.6}
        out1 = aggregate([a, b], rates, CFG)
        out2 = aggregate([a, b], rates, CFG)
        self.assertEqual(len(out1), len(out2))
        self.assertEqual(out1[0].probability, out2[0].probability)
        self.assertEqual(str(out1[0].id), str(out2[0].id))
        self.assertEqual(out1[0].skill_id, out2[0].skill_id)

    def test_same_skill_no_self_corroboration(self):
        a = _f(skill_id="same", p=0.4, fid="a", lon=-122.4)
        b = _f(skill_id="same", p=0.5, fid="b", lon=-122.41)
        out = aggregate([a, b], {"same": 0.5}, CFG)
        self.assertEqual(len(out), 2)
        probs = sorted(x.probability for x in out)
        self.assertEqual(probs, [0.4, 0.5])


class ImportBoundaryTests(unittest.TestCase):
    def test_pipeline_banned_from_allowlist(self):
        self.assertIn("pipeline", _BANNED_IMPORT_ROOTS)
        self.assertNotIn("pipeline", _ALLOWED_IMPORT_ROOTS)
        ok, detail = check_import_allowlist(
            "from pipeline.aggregator import aggregate\n"
        )
        self.assertFalse(ok)
        self.assertIn("pipeline", detail)

    def test_emit_priced_blocked_in_persistence_check(self):
        src = "def run(now, db):\n    emit_priced([], db)\n    return []\n"
        ok, detail = check_no_persistence(src)
        self.assertFalse(ok)

    def test_mutator_generator_have_no_pipeline_import(self):
        roots = [
            REPO_ROOT / "agent" / "evolution" / "mutator.py",
            REPO_ROOT / "agent" / "evolution" / "generator.py",
        ]
        offenders: list[str] = []
        for path in roots:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] == "pipeline":
                            offenders.append(str(path))
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.split(".")[0] == "pipeline":
                        offenders.append(str(path))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
