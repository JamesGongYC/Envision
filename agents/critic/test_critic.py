#!/usr/bin/env python3
"""T6 critic harness tests — mocked LLM/DB; never write prod."""
from __future__ import annotations

import ast
import sys
import unittest
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "agent" / "lib"))

from agents.critic.loop import run_critic_loop  # noqa: E402
from agents.critic.tools import (  # noqa: E402
    RAW_PRODUCER_FILTER,
    dispatch_tool,
    inspect_forecasts,
    tool_generate_skill,
)


@dataclass
class FakeBlock:
    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict | None = None


@dataclass
class FakeResponse:
    content: list[Any] = field(default_factory=list)


class FakeTelemetry:
    def __init__(self) -> None:
        self.run_id = uuid.uuid4()
        self.steps: list[dict] = []
        self.finished: dict | None = None

    def start_run(self, db, *, agent_type, trigger):
        self.agent_type = agent_type
        self.trigger = trigger
        return self.run_id

    def append_step(self, db, *, agent_run_id, seq, step_type, **kwargs):
        self.steps.append({"seq": seq, "step_type": step_type, **kwargs})
        return uuid.uuid4()

    def finish_run(self, db, *, agent_run_id, status, **kwargs):
        self.finished = {"status": status, **kwargs}


class ScriptedLLM:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, **kwargs):
        self.calls += 1
        if not self.responses:
            raise AssertionError("LLM called more times than scripted")
        return self.responses.pop(0), "fake-model"


def _tool_response(name: str, tool_input: dict, thought: str = "thinking") -> FakeResponse:
    return FakeResponse(
        content=[
            FakeBlock(type="text", text=thought),
            FakeBlock(
                type="tool_use",
                id=f"tu_{name}_{uuid.uuid4().hex[:6]}",
                name=name,
                input=tool_input,
            ),
        ]
    )


def _tool_only_response(name: str, tool_input: dict) -> FakeResponse:
    return FakeResponse(
        content=[
            FakeBlock(
                type="tool_use",
                id=f"tu_{name}_{uuid.uuid4().hex[:6]}",
                name=name,
                input=tool_input,
            ),
        ]
    )


def _text_only_response(text: str) -> FakeResponse:
    return FakeResponse(content=[FakeBlock(type="text", text=text)])


class InspectForecastsFilterTests(unittest.TestCase):
    def test_producer_filter_is_rule(self):
        self.assertEqual(RAW_PRODUCER_FILTER, "rule")

    def test_inspect_forecasts_queries_producer_rule(self):
        db = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = []
        db.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        db.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "agents.critic.tools.list_skills",
            return_value=[
                {
                    "skill_id": "wildfire_risk_elevated",
                    "mean_brier": 0.2,
                    "hit_rate": 0.5,
                    "n_evaluations": 10,
                    "override_frequency": 0.1,
                    "summary": "x",
                }
            ],
        ):
            out = inspect_forecasts(db, "wildfire_risk_elevated")

        sql = cur.execute.call_args.args[0]
        params = cur.execute.call_args.args[1]
        self.assertIn("f.producer = %s", sql)
        self.assertEqual(params[1], "rule")
        self.assertNotIn("agent", params)
        self.assertEqual(out["producer_filter"], "rule")


class GenerateRefuseTests(unittest.TestCase):
    def test_generate_refused_when_not_seeded(self):
        db = MagicMock()
        now = datetime.now(timezone.utc)
        with patch(
            "agents.critic.tools.is_generator_seeded", return_value=False
        ), patch(
            "agents.critic.tools.evolution_generate_skill"
        ) as mock_gen:
            out = tool_generate_skill(
                db, now=now, disaster_class="wildfire", seed="x"
            )
            mock_gen.assert_not_called()
            self.assertTrue(out["refused"])
            self.assertFalse(out["terminal"])

            obs, is_terminal = dispatch_tool(
                "generate_skill",
                {"disaster_class": "wildfire"},
                db=db,
                now=now,
            )
            self.assertTrue(obs["refused"])
            self.assertFalse(is_terminal)
            mock_gen.assert_not_called()


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.tel = FakeTelemetry()
        self.db = MagicMock()
        self.now = datetime.now(timezone.utc)
        self.patches = [
            patch("agents.critic.loop.start_run", self.tel.start_run),
            patch("agents.critic.loop.append_step", self.tel.append_step),
            patch("agents.critic.loop.finish_run", self.tel.finish_run),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_preflight_failure_gates_mutator_not_called(self):
        llm = ScriptedLLM([])
        with patch("agents.critic.tools.evolution_mutate_skill") as mock_mut:
            result = run_critic_loop(
                self.now,
                self.db,
                trigger="operator",
                call_llm=llm,
                preflight=lambda db: False,
                abort_check=lambda db: False,
            )
            mock_mut.assert_not_called()
        self.assertEqual(result.status, "gated")
        self.assertEqual(llm.calls, 0)
        self.assertEqual(self.tel.agent_type, "critic")

    def test_mutate_path_calls_mutator_and_records_proposal(self):
        llm = ScriptedLLM(
            [
                _tool_response(
                    "mutate_skill",
                    {"skill_id": "wildfire_risk_elevated"},
                    thought="underperformer",
                )
            ]
        )
        mut = MagicMock()
        mut.accepted = True
        mut.proposal_id = "prop-abc"
        mut.lineage_id = "lin-1"
        mut.rejection_reasons = []
        mut.rationale = "fix threshold"

        with patch(
            "agents.critic.tools.evolution_mutate_skill", return_value=mut
        ) as mock_mut:
            result = run_critic_loop(
                self.now,
                self.db,
                trigger="button",
                call_llm=llm,
                preflight=lambda db: True,
                abort_check=lambda db: False,
            )
            mock_mut.assert_called_once()
            self.assertEqual(
                mock_mut.call_args.args[0], "wildfire_risk_elevated"
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.proposal_ids, ["prop-abc"])
        self.assertEqual(self.tel.finished["status"], "completed")
        self.assertEqual(
            self.tel.finished["outcome"]["proposal_ids"], ["prop-abc"]
        )
        types = [s["step_type"] for s in self.tel.steps]
        self.assertIn("terminal", types)
        self.assertEqual(self.tel.trigger, "button")
        self.assertEqual(types[0], "thought")
        self.assertEqual(types[1], "action")

    def test_tool_only_response_still_dispatches(self):
        llm = ScriptedLLM(
            [
                _tool_only_response(
                    "mutate_skill", {"skill_id": "wildfire_risk_elevated"}
                )
            ]
        )
        mut = MagicMock()
        mut.accepted = True
        mut.proposal_id = "prop-x"
        mut.lineage_id = "lin"
        mut.rejection_reasons = []
        mut.rationale = "ok"

        with patch(
            "agents.critic.tools.evolution_mutate_skill", return_value=mut
        ):
            result = run_critic_loop(
                self.now,
                self.db,
                trigger="button",
                call_llm=llm,
                preflight=lambda db: True,
                abort_check=lambda db: False,
            )

        self.assertEqual(result.status, "completed")
        types = [s["step_type"] for s in self.tel.steps]
        self.assertEqual(types[0], "action")
        self.assertIn("terminal", types)
        self.assertGreater(result.step_count, 0)

    def test_no_tool_turn_reprompts_then_completes(self):
        llm = ScriptedLLM(
            [
                _text_only_response("Looking at Brier ranks…"),
                _tool_response(
                    "mutate_skill",
                    {"skill_id": "wildfire_risk_elevated"},
                    thought="Mutating the weak skill.",
                ),
            ]
        )
        mut = MagicMock()
        mut.accepted = True
        mut.proposal_id = "prop-y"
        mut.lineage_id = "lin"
        mut.rejection_reasons = []
        mut.rationale = "ok"

        with patch(
            "agents.critic.tools.evolution_mutate_skill", return_value=mut
        ):
            result = run_critic_loop(
                self.now,
                self.db,
                trigger="button",
                call_llm=llm,
                preflight=lambda db: True,
                abort_check=lambda db: False,
            )

        self.assertEqual(result.status, "completed")
        self.assertGreaterEqual(llm.calls, 2)
        types = [s["step_type"] for s in self.tel.steps]
        self.assertEqual(types[0], "thought")
        self.assertIn("terminal", types)
        self.assertGreater(result.step_count, 0)


class NoAnthropicImportTests(unittest.TestCase):
    def test_no_anthropic_under_critic(self):
        critic_dir = REPO_ROOT / "agents" / "critic"
        for path in critic_dir.rglob("*.py"):
            if path.name.startswith("test_"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotEqual(
                            alias.name.split(".")[0],
                            "anthropic",
                            msg=f"{path} imports anthropic",
                        )
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotEqual(
                        node.module.split(".")[0],
                        "anthropic",
                        msg=f"{path} imports from anthropic",
                    )
                    self.assertNotIn(
                        "react_prose",
                        node.module,
                        msg=f"{path} imports react_prose",
                    )


class OrchestratorCriticWireTests(unittest.TestCase):
    @patch("agent.evolution.orchestrator.select_candidates")
    @patch("agent.evolution.orchestrator.run_critic_loop")
    @patch("agent.evolution.orchestrator.should_abort_cycle", return_value=False)
    @patch(
        "agent.evolution.orchestrator.should_run_generator",
        return_value=(False, None, []),
    )
    def test_curator_enabled_uses_critic_not_worst_k(
        self, _gen, _abort, mock_critic, mock_select
    ):
        from agent.evolution.budget import BudgetTracker
        from agent.evolution.orchestrator import pick_worst_k_skills, run_evolution_pass
        from agent.evolution.selector import SelectionResult
        from agents.critic.loop import CriticResult

        mock_critic.return_value = CriticResult(
            agent_run_id=uuid.uuid4(),
            status="completed",
            step_count=2,
            proposal_ids=["p1"],
        )
        mock_select.return_value = SelectionResult(selected_lineage_ids=[])

        with patch(
            "agent.evolution.orchestrator.pick_worst_k_skills"
        ) as mock_pick:
            summary = run_evolution_pass(
                MagicMock(),
                datetime.now(timezone.utc),
                budget=BudgetTracker(),
                curator_enabled=True,
            )
            mock_pick.assert_not_called()

        mock_critic.assert_called_once()
        self.assertEqual(mock_critic.call_args.kwargs.get("trigger"), "scheduled")
        self.assertEqual(summary.accepted, 1)
        # Function still exists but is unused on live path
        self.assertTrue(callable(pick_worst_k_skills))


if __name__ == "__main__":
    unittest.main(verbosity=2)
