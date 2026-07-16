#!/usr/bin/env python3
"""Tests for v3 Day 4 orchestration + operator review."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "agent" / "lib"))

from agent.evolution.budget import PASS_BUDGET_USD, BudgetTracker  # noqa: E402
from agent.evolution.promotion import (  # noqa: E402
    bump_skill_version,
    modal_deploy_command,
    write_promoted_run_py,
)
from agent.evolution.proposal_review import (  # noqa: E402
    ProposalRow,
    blocked_on,
    PROMOTE_CONFIRM,
)
from agent.lib.repo_env import load_repo_env  # noqa: E402

load_repo_env()


class BudgetTests(unittest.TestCase):
    def test_budget_cap_stops_afford(self):
        t = BudgetTracker(cap_usd=1.0)
        t.record_usage("claude-sonnet-4-6", 500_000, 100_000)
        self.assertFalse(t.can_afford_next_call())

    def test_haiku_switch_fraction(self):
        t = BudgetTracker(cap_usd=10.0)
        t.spend_usd = 7.5
        self.assertTrue(t.should_use_haiku())


class PromotionTests(unittest.TestCase):
    def test_bump_skill_version(self):
        src = "SKILL_VERSION = 1\n\ndef run():\n    pass\n"
        out = bump_skill_version(src, 2)
        self.assertIn("SKILL_VERSION = 2", out)

    def test_modal_deploy_command(self):
        cmd = modal_deploy_command("wildfire_risk_elevated")
        self.assertIn("wildfire-risk-elevated", cmd)
        self.assertIn("modal deploy", cmd)

    def test_write_promoted_run_py(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "agent" / "modal_skills" / "wildfire-risk-elevated").mkdir(
                parents=True
            )
            path = write_promoted_run_py(
                "wildfire_risk_elevated",
                "SKILL_VERSION = 1\n\ndef run(now, db):\n    return []\n",
                2,
                repo_root=root,
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("SKILL_VERSION = 2", text)
            self.assertIn("def run", text)


class BlockedOnTests(unittest.TestCase):
    def test_cold_start_evals(self):
        db = MagicMock()
        prop = ProposalRow(
            proposal_id="p1",
            skill_id="wildfire_risk_elevated",
            current_version=1,
            status="pending",
            proposed_at=datetime.now(timezone.utc),
            lineage_id="l1",
            lineage_status="shadow",
            source_code="def run(n,d):\n return []",
            curator_reasoning="",
            curator_trace=None,
        )
        with patch(
            "agent.evolution.proposal_review.shadow_metrics",
            return_value=(0.2, 4),
        ), patch(
            "agent.evolution.proposal_review.parent_live_brier_14d",
            return_value=0.35,
        ), patch(
            "agent.evolution.proposal_review.backtest_summary",
            return_value=[(1, 2, 0.3, 5)],
        ):
            reasons = blocked_on(db, prop)
        self.assertTrue(any("evals 4/20" in r for r in reasons))

    def test_candidate_not_shadow(self):
        db = MagicMock()
        prop = ProposalRow(
            proposal_id="p1",
            skill_id="wildfire_risk_elevated",
            current_version=1,
            status="pending",
            proposed_at=datetime.now(timezone.utc),
            lineage_id="l1",
            lineage_status="candidate",
            source_code="",
            curator_reasoning="",
            curator_trace=None,
        )
        with patch(
            "agent.evolution.proposal_review.backtest_summary",
            return_value=[],
        ), patch(
            "agent.evolution.proposal_review.shadow_metrics",
            return_value=(None, 0),
        ):
            reasons = blocked_on(db, prop)
        self.assertTrue(any("not in shadow" in r for r in reasons))


class CuratorSubsumesV2Tests(unittest.TestCase):
    def test_archived_v2_exists(self):
        p = REPO_ROOT / "agent" / "modal_skills" / "curator" / "_archived_v2_param_tweak.py"
        self.assertTrue(p.is_file())
        text = p.read_text(encoding="utf-8")
        self.assertIn("propose_skill_edit", text)

    def test_new_run_uses_orchestrator(self):
        run_py = REPO_ROOT / "agent" / "modal_skills" / "curator" / "run.py"
        text = run_py.read_text(encoding="utf-8")
        self.assertIn("run_evolution_pass", text)
        self.assertNotIn("propose_skill_edit", text)


class OrchestrationTests(unittest.TestCase):
    @patch("agent.evolution.orchestrator.select_candidates")
    @patch("agent.evolution.orchestrator.run_critic_loop")
    def test_orchestration_order(self, mock_critic, mock_select):
        from agents.critic.loop import CriticResult
        from agent.evolution.selector import SelectionResult
        from agent.evolution.orchestrator import run_evolution_pass

        mock_critic.return_value = CriticResult(
            agent_run_id=__import__("uuid").uuid4(),
            status="completed",
            step_count=3,
            proposal_ids=["p"],
        )
        mock_select.return_value = SelectionResult(selected_lineage_ids=["l"])

        db = MagicMock()
        summary = run_evolution_pass(db, datetime.now(timezone.utc), budget=BudgetTracker())
        mock_critic.assert_called_once()
        self.assertEqual(mock_critic.call_args.kwargs.get("trigger"), "scheduled")
        mock_select.assert_called_once()
        self.assertEqual(summary.accepted, 1)
        self.assertEqual(summary.selected_to_shadow, ["l"])


class PromoteRefuseTests(unittest.TestCase):
    @patch("agent.evolution.proposal_review.write_promoted_run_py")
    def test_promote_refuses_low_evals(self, mock_write):
        from agent.evolution.proposal_review import promote_proposal

        db = MagicMock()
        prop = ProposalRow(
            proposal_id="p1",
            skill_id="wildfire_risk_elevated",
            current_version=1,
            status="pending",
            proposed_at=datetime.now(timezone.utc),
            lineage_id="l1",
            lineage_status="shadow",
            source_code="def run(n,d):\n return []",
            curator_reasoning="",
            curator_trace=None,
        )
        with patch(
            "agent.evolution.proposal_review.fetch_proposal",
            return_value=prop,
        ), patch(
            "agent.evolution.proposal_review.blocked_on",
            return_value=["evals 5/20"],
        ):
            ok, msg = promote_proposal(db, "p1")
        self.assertFalse(ok)
        mock_write.assert_not_called()


def main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (
        BudgetTests,
        PromotionTests,
        BlockedOnTests,
        CuratorSubsumesV2Tests,
        OrchestrationTests,
        PromoteRefuseTests,
    ):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
