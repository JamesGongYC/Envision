#!/usr/bin/env python3
"""T2 forecaster harness tests — mocked LLM/DB; never write prod."""
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

from agent.lib.forecast_model import Forecast  # noqa: E402
from agents.common.aggregator_interface import emit_selected  # noqa: E402
from agents.forecaster.loop import run_forecaster_loop  # noqa: E402
from agents.forecaster.tools import emit as emit_tool  # noqa: E402


def _forecast(fid: str | None = None, p: float = 0.4) -> Forecast:
    return Forecast(
        id=fid or str(uuid.uuid4()),
        issued_at=datetime.now(timezone.utc),
        valid_from=datetime.now(timezone.utc),
        valid_until=datetime.now(timezone.utc),
        disaster_class="wildfire",
        geometry='{"type":"Point","coordinates":[-122.4,37.8]}',
        probability=p,
        skill_id="wildfire_risk_elevated",
        skill_version=1,
        contributing_signal_ids=[],
        reasoning="test",
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
    """In-memory stand-in for agent_run / agent_step persistence."""

    def __init__(self) -> None:
        self.run_id = uuid.uuid4()
        self.steps: list[dict] = []
        self.finished: dict | None = None

    def start_run(self, db, *, agent_type, trigger):
        return self.run_id

    def append_step(self, db, *, agent_run_id, seq, step_type, **kwargs):
        self.steps.append({"seq": seq, "step_type": step_type, **kwargs})
        return uuid.uuid4()

    def finish_run(self, db, *, agent_run_id, status, **kwargs):
        self.finished = {"status": status, **kwargs}


class ScriptedLLM:
    """Return a queue of FakeResponse objects."""

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


class EmitPStripTests(unittest.TestCase):
    def test_model_supplied_p_ignored(self):
        skill_p = 0.42
        fid = str(uuid.uuid4())
        cached = _forecast(fid, p=skill_p)
        cache = {fid: cached}
        db = MagicMock()
        with patch("agents.forecaster.tools.emit_selected") as mock_emit:
            mock_emit.return_value = [uuid.UUID(fid)]
            emit_tool(
                db,
                selected=[{"id": fid, "probability": 0.99}],
                agent_run_id=uuid.uuid4(),
                candidate_cache=cache,
            )
            mock_emit.assert_called_once()
            selected = mock_emit.call_args.args[0]
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0].probability, skill_p)

    def test_aggregator_prices_and_clamps_cap(self):
        f = _forecast(p=0.9)
        db = MagicMock()
        with patch(
            "agents.common.aggregator_interface.fetch_skill_hit_rates",
            return_value={f.skill_id: 0.5},
        ), patch(
            "agents.common.aggregator_interface.emit_forecasts"
        ) as mock_w:
            mock_w.return_value = 1
            ids = emit_selected([f], db=db, agent_run_id=uuid.uuid4())
            self.assertEqual(len(ids), 1)
            written = mock_w.call_args.args[0]
            self.assertEqual(written[0].probability, 0.85)
            self.assertEqual(mock_w.call_args.kwargs.get("producer"), "agent")


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.tel = FakeTelemetry()
        self.db = MagicMock()
        self.now = datetime.now(timezone.utc)
        self.patches = [
            patch("agents.forecaster.loop.start_run", self.tel.start_run),
            patch("agents.forecaster.loop.append_step", self.tel.append_step),
            patch("agents.forecaster.loop.finish_run", self.tel.finish_run),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_preflight_failure_gates_before_tools(self):
        llm = ScriptedLLM([])
        result = run_forecaster_loop(
            self.now,
            self.db,
            trigger="operator",
            call_llm=llm,
            preflight=lambda db: False,
            abort_check=lambda db: False,
        )
        self.assertEqual(result.status, "gated")
        self.assertEqual(llm.calls, 0)
        types = [s["step_type"] for s in self.tel.steps]
        self.assertEqual(types, ["gated"])
        self.assertEqual(self.tel.finished["status"], "gated")

    def test_rolling_529_gates_no_emit(self):
        llm = ScriptedLLM(
            [_tool_response("list_skills", {}, thought="checking skills")]
        )
        dispatched = []

        def fake_dispatch(name, tool_input, **kwargs):
            dispatched.append(name)
            return {"skills": []}, None, False

        with patch("agents.forecaster.loop.dispatch_tool", fake_dispatch):
            # Abort trips after the action is logged, before/during dispatch path:
            # first abort_check after LLM returns False so action proceeds,
            # then True on the check before dispatch — actually loop checks
            # abort after action append, before dispatch.
            checks = {"n": 0}

            def abort(db):
                checks["n"] += 1
                return True  # trip immediately after first action

            result = run_forecaster_loop(
                self.now,
                self.db,
                trigger="operator",
                call_llm=llm,
                preflight=lambda db: True,
                abort_check=abort,
            )
        self.assertEqual(result.status, "gated")
        self.assertEqual(result.emitted_ids, [])
        types = [s["step_type"] for s in self.tel.steps]
        self.assertIn("gated", types)
        self.assertNotIn("terminal", types)

    def test_full_cycle_ordered_steps(self):
        fid = str(uuid.uuid4())
        cand = _forecast(fid, p=0.5)
        llm = ScriptedLLM(
            [
                _tool_response("inspect_signals", {}),
                _tool_response("run_skill", {"skill_id": "wildfire_risk_elevated"}),
                _tool_response("emit", {"selected": [{"id": fid, "probability": 0.99}]}),
            ]
        )
        deposited: list = []

        def fake_dispatch(name, tool_input, **kwargs):
            cache = kwargs["candidate_cache"]
            if name == "inspect_signals":
                return {"catalog": []}, None, False
            if name == "run_skill":
                cache[fid] = cand
                deposited.append(cand)
                # Simulate D2 deposit side-effect marker
                return {
                    "candidates": [{"id": fid, "probability": 0.5}],
                    "count": 1,
                }, None, False
            if name == "emit":
                # emit tool path — call real emit with mocks
                with patch("agents.forecaster.tools.emit_selected") as mock_es:
                    mock_es.return_value = [uuid.UUID(fid)]
                    from agents.forecaster.tools import emit as real_emit

                    ids = real_emit(
                        kwargs["db"],
                        selected=tool_input.get("selected") or [],
                        agent_run_id=kwargs["agent_run_id"],
                        candidate_cache=cache,
                    )
                    # Assert model p ignored
                    written = mock_es.call_args.args[0]
                    self.assertEqual(written[0].probability, 0.5)
                return {"emitted_ids": ids, "count": len(ids)}, None, True
            raise AssertionError(name)

        with patch("agents.forecaster.loop.dispatch_tool", fake_dispatch):
            result = run_forecaster_loop(
                self.now,
                self.db,
                trigger="operator",
                call_llm=llm,
                preflight=lambda db: True,
                abort_check=lambda db: False,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.emitted_ids, [fid])
        self.assertEqual(len(deposited), 1)
        types = [s["step_type"] for s in self.tel.steps]
        # thought/action/observation repeated, then terminal
        self.assertIn("thought", types)
        self.assertIn("action", types)
        self.assertIn("observation", types)
        self.assertIn("terminal", types)
        self.assertEqual(types[-1], "terminal")

    def test_run_skill_deposits_even_when_not_selected(self):
        """D2: raw deposit happens inside run_skill regardless of later emit selection."""
        kept = _forecast(p=0.4)
        dropped = _forecast(p=0.3)
        db = MagicMock()
        cache: dict = {}

        with patch("agents.forecaster.tools.load_skill_run") as mock_load, patch(
            "agents.forecaster.tools.emit_forecasts"
        ) as mock_emit:
            mock_load.return_value = lambda now, db: [kept, dropped]
            mock_emit.return_value = 2
            from agents.forecaster.tools import run_skill

            serialized, _geo, cands = run_skill(
                db,
                skill_id="wildfire_risk_elevated",
                now=datetime.now(timezone.utc),
                agent_run_id=uuid.uuid4(),
                candidate_cache=cache,
            )
            self.assertEqual(len(cands), 2)
            mock_emit.assert_called_once()
            self.assertEqual(mock_emit.call_args.kwargs.get("producer"), "rule")
            self.assertIsNotNone(mock_emit.call_args.kwargs.get("agent_run_id"))

            # Agent selects only `kept`
            with patch("agents.forecaster.tools.emit_selected") as mock_sel:
                mock_sel.return_value = [uuid.UUID(str(kept.id))]
                emit_tool(
                    db,
                    selected=[{"id": str(kept.id)}],
                    agent_run_id=uuid.uuid4(),
                    candidate_cache=cache,
                )
                selected = mock_sel.call_args.args[0]
                self.assertEqual(len(selected), 1)
                self.assertEqual(str(selected[0].id), str(kept.id))
            # Raw deposit still included both
            raw_written = mock_emit.call_args.args[0]
            self.assertEqual(len(raw_written), 2)


class NoDirectSdkTests(unittest.TestCase):
    def test_no_anthropic_import_in_forecaster(self):
        root = REPO_ROOT / "agents" / "forecaster"
        offenders: list[str] = []
        for path in root.rglob("*.py"):
            if path.name.startswith("test_"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "anthropic" or alias.name.startswith(
                            "anthropic."
                        ):
                            offenders.append(str(path))
                elif isinstance(node, ast.ImportFrom):
                    if node.module and (
                        node.module == "anthropic"
                        or node.module.startswith("anthropic.")
                    ):
                        offenders.append(str(path))
        self.assertEqual(offenders, [], f"direct anthropic imports: {offenders}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
