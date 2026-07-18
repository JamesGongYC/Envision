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

                    ids, candidates = real_emit(
                        kwargs["db"],
                        selected=tool_input.get("selected") or [],
                        agent_run_id=kwargs["agent_run_id"],
                        candidate_cache=cache,
                    )
                    # Assert model p ignored
                    written = mock_es.call_args.args[0]
                    self.assertEqual(written[0].probability, 0.5)
                return {
                    "emitted_ids": ids,
                    "candidates": candidates,
                    "count": len(ids),
                }, None, True
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
        # Intent prose (if present) precedes action
        thought_idx = types.index("thought")
        action_idx = types.index("action")
        self.assertLess(thought_idx, action_idx)

    def test_tool_only_response_still_dispatches(self):
        """T10: empty text + tool_use must still run (no intent gate)."""
        llm = ScriptedLLM(
            [
                _tool_only_response("list_skills", {}),
                _tool_only_response("emit", {"selected": []}),
            ]
        )

        def fake_dispatch(name, tool_input, **kwargs):
            if name == "list_skills":
                return [], None, False
            if name == "emit":
                return {"emitted_ids": [], "count": 0}, None, True
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
        types = [s["step_type"] for s in self.tel.steps]
        self.assertIn("action", types)
        self.assertIn("observation", types)
        self.assertIn("terminal", types)
        self.assertGreater(result.step_count, 0)
        self.assertEqual(types[0], "action")

    def test_no_tool_turn_reprompts_then_completes(self):
        """T10: thought-only turn re-prompts; does not complete with step_count=0."""
        llm = ScriptedLLM(
            [
                _text_only_response("Considering the signal catalog…"),
                _tool_response(
                    "emit",
                    {"selected": []},
                    thought="Nothing to emit.",
                ),
            ]
        )

        def fake_dispatch(name, tool_input, **kwargs):
            if name == "emit":
                return {"emitted_ids": [], "count": 0}, None, True
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
        self.assertGreaterEqual(llm.calls, 2)
        types = [s["step_type"] for s in self.tel.steps]
        self.assertEqual(types[0], "thought")
        self.assertIn("terminal", types)
        self.assertGreater(result.step_count, 0)

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


class T11EventContractTests(unittest.TestCase):
    def test_input_layers_for_each_skill(self):
        from agents.forecaster.skill_layers import SKILL_INPUT_LAYERS, input_layers_for

        expected = {
            "wildfire_rapid_growth": [
                "firms_hotspots",
                "open_meteo_fire_weather",
                "nws_fire_alerts",
            ],
            "wildfire_risk_elevated": [
                "firms_hotspots",
                "nws_fire_alerts",
                "open_meteo_fire_weather",
            ],
            "typhoon_intensifying": [
                "jtwc_advisories",
                "aifs_cyclone_features",
            ],
            "typhoon_landfall_imminent": [
                "jtwc_advisories",
                "nhc_advisories",
                "aifs_cyclone_features",
            ],
        }
        self.assertEqual(SKILL_INPUT_LAYERS, expected)
        for skill_id, layers in expected.items():
            self.assertEqual(input_layers_for(skill_id), layers)
        self.assertEqual(input_layers_for("unknown_skill"), [])

    def test_run_skill_action_and_observation_carry_layers(self):
        from agents.forecaster.tools import (
            dispatch_tool,
            enrich_run_skill_action_input,
        )

        skill_id = "wildfire_rapid_growth"
        action = enrich_run_skill_action_input({"skill_id": skill_id})
        self.assertEqual(action["skill_id"], skill_id)
        self.assertEqual(
            action["input_layers"],
            ["firms_hotspots", "open_meteo_fire_weather", "nws_fire_alerts"],
        )

        fid = str(uuid.uuid4())
        cand = _forecast(fid, p=0.4)
        cand.skill_id = skill_id
        cache: dict = {}
        db = MagicMock()
        with patch("agents.forecaster.tools.load_skill_run") as mock_load, patch(
            "agents.forecaster.tools.emit_forecasts", return_value=1
        ):
            mock_load.return_value = lambda now, db: [cand]
            obs, geo, terminal = dispatch_tool(
                "run_skill",
                {"skill_id": skill_id},
                db=db,
                now=datetime.now(timezone.utc),
                agent_run_id=uuid.uuid4(),
                candidate_cache=cache,
            )
        self.assertFalse(terminal)
        self.assertEqual(obs["skill_id"], skill_id)
        self.assertEqual(obs["input_layers"], action["input_layers"])
        self.assertEqual(obs["count"], 1)
        self.assertIsInstance(obs["candidates"][0]["geometry"], dict)
        self.assertEqual(obs["candidates"][0]["geometry"]["type"], "Point")
        self.assertIsNotNone(geo)

    def test_emit_terminal_candidates_shape(self):
        fid = str(uuid.uuid4())
        cached = _forecast(fid, p=0.55)
        cached.reasoning = "Elevated fire weather near the Sierra foothills"
        cache = {fid: cached}
        db = MagicMock()
        with patch("agents.forecaster.tools.emit_selected") as mock_emit:
            mock_emit.return_value = [uuid.UUID(fid)]
            ids, candidates = emit_tool(
                db,
                selected=[{"id": fid, "probability": 0.99}],
                agent_run_id=uuid.uuid4(),
                candidate_cache=cache,
            )
        self.assertEqual(ids, [fid])
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c["id"], fid)
        self.assertEqual(c["location"]["type"], "Point")
        self.assertEqual(c["hazard"], "wildfire")
        self.assertEqual(c["probability"], 0.55)
        self.assertEqual(c["skill"], "wildfire_risk_elevated")
        self.assertIn("Sierra", c["label"])

    def test_scrub_coord_prose_strips_decimal_pair(self):
        from agents.common.prose_scrub import scrub_coord_prose

        raw = "Checking hotspots near 37.7, -122.4 for growth risk."
        scrubbed = scrub_coord_prose(raw)
        self.assertNotIn("37.7", scrubbed)
        self.assertNotIn("-122.4", scrubbed)
        self.assertIn("[coords omitted]", scrubbed)

    def test_thought_step_persists_scrubbed_text(self):
        tel = FakeTelemetry()
        patches = [
            patch("agents.forecaster.loop.start_run", tel.start_run),
            patch("agents.forecaster.loop.append_step", tel.append_step),
            patch("agents.forecaster.loop.finish_run", tel.finish_run),
        ]
        for p in patches:
            p.start()
        try:
            llm = ScriptedLLM(
                [
                    _tool_response(
                        "emit",
                        {"selected": []},
                        thought="Looking at 37.7, -122.4 then emitting nothing.",
                    ),
                ]
            )

            def fake_dispatch(name, tool_input, **kwargs):
                if name == "emit":
                    return {
                        "emitted_ids": [],
                        "candidates": [],
                        "count": 0,
                    }, None, True
                raise AssertionError(name)

            with patch("agents.forecaster.loop.dispatch_tool", fake_dispatch):
                result = run_forecaster_loop(
                    datetime.now(timezone.utc),
                    MagicMock(),
                    trigger="operator",
                    call_llm=llm,
                    preflight=lambda db: True,
                    abort_check=lambda db: False,
                )
            self.assertEqual(result.status, "completed")
            thought_steps = [s for s in tel.steps if s["step_type"] == "thought"]
            self.assertEqual(len(thought_steps), 1)
            text = thought_steps[0]["tool_output"]["text"]
            self.assertNotIn("37.7", text)
            self.assertNotIn("-122.4", text)
        finally:
            for p in patches:
                p.stop()

    def test_sse_promotes_layers_and_candidates(self):
        from agents.common.agent_telemetry import (
            step_row_to_sse_payload,
            step_to_sse_payload,
        )

        run_id = uuid.uuid4()
        layers = ["firms_hotspots", "nws_fire_alerts"]
        live = step_to_sse_payload(
            run_id,
            seq=2,
            step_type="action",
            tool="run_skill",
            tool_input={"skill_id": "wildfire_risk_elevated", "input_layers": layers},
        )
        self.assertEqual(live["skill_id"], "wildfire_risk_elevated")
        self.assertEqual(live["input_layers"], layers)

        candidates = [
            {
                "id": str(uuid.uuid4()),
                "location": {"type": "Point", "coordinates": [-122.4, 37.8]},
                "hazard": "wildfire",
                "probability": 0.5,
                "skill": "wildfire_risk_elevated",
                "label": "test",
            }
        ]
        terminal = step_to_sse_payload(
            run_id,
            seq=5,
            step_type="terminal",
            tool="emit",
            tool_output={
                "emitted_ids": [candidates[0]["id"]],
                "candidates": candidates,
                "count": 1,
            },
        )
        self.assertEqual(terminal["candidates"], candidates)

        replay = step_row_to_sse_payload(
            run_id,
            {
                "seq": 5,
                "step_type": "terminal",
                "tool": "emit",
                "tool_input": None,
                "tool_output": {
                    "emitted_ids": [candidates[0]["id"]],
                    "candidates": candidates,
                    "count": 1,
                },
                "geo_focus": None,
                "created_at": datetime.now(timezone.utc),
            },
        )
        self.assertEqual(replay["candidates"], candidates)
        self.assertEqual(replay["output"]["candidates"], candidates)


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

    def test_no_react_prose_import(self):
        root = REPO_ROOT / "agents" / "forecaster"
        for path in root.rglob("*.py"):
            if path.name.startswith("test_"):
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(
                "react_prose",
                text,
                msg=f"{path} must not import react_prose",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
