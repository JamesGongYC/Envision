#!/usr/bin/env python3
"""T4 agent API tests — mocked DB/loop; never write prod."""
from __future__ import annotations

import json
import os
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "agent" / "lib"))

os.environ["ENVISION_OPERATOR_TOKEN"] = "test-operator-token"
os.environ["DATABASE_URL"] = "postgresql://unused/unused"

from fastapi.testclient import TestClient  # noqa: E402

from agents.api.fastapi_app import create_app  # noqa: E402
from agents.api.sse import format_sse, gated_event  # noqa: E402
from agents.common.agent_telemetry import step_to_sse_payload  # noqa: E402
from agents.critic.loop import CriticResult  # noqa: E402
from agents.forecaster.loop import ForecasterResult  # noqa: E402


def _parse_sse(body: str) -> list[dict]:
    events: list[dict] = []
    for block in body.strip().split("\n\n"):
        if not block.strip():
            continue
        data_line = None
        for line in block.splitlines():
            if line.startswith("data: "):
                data_line = line[len("data: ") :]
        if data_line:
            events.append(json.loads(data_line))
    return events


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())

    def test_fire_missing_token_401(self):
        with patch("agents.forecaster.loop.run_forecaster_loop") as mock_loop:
            r = self.client.post("/agent/forecaster/fire")
            self.assertEqual(r.status_code, 401)
            mock_loop.assert_not_called()

    def test_fire_wrong_token_403(self):
        with patch("agents.forecaster.loop.run_forecaster_loop") as mock_loop:
            r = self.client.post(
                "/agent/forecaster/fire",
                headers={"Authorization": "Bearer wrong-token"},
            )
            self.assertEqual(r.status_code, 403)
            mock_loop.assert_not_called()


class FireStreamTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.headers = {"Authorization": "Bearer test-operator-token"}

    def _mock_db(self, *, in_flight: int = 0):
        """Patch psycopg.connect for capacity check + worker."""
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = (in_flight,)
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        return conn

    def test_valid_fire_streams_terminal(self):
        run_id = uuid.uuid4()
        steps = [
            step_to_sse_payload(
                run_id, seq=1, step_type="thought", tool_output={"text": "hi"}
            ),
            step_to_sse_payload(
                run_id,
                seq=2,
                step_type="action",
                tool="run_skill",
                tool_input={"skill_id": "wildfire_risk_elevated"},
            ),
            step_to_sse_payload(
                run_id,
                seq=3,
                step_type="observation",
                tool="run_skill",
                tool_output={"count": 1},
                geo_focus={
                    "type": "Polygon",
                    "coordinates": [
                        [[-122.5, 37.7], [-122.3, 37.7], [-122.3, 37.9], [-122.5, 37.9], [-122.5, 37.7]]
                    ],
                },
            ),
            step_to_sse_payload(
                run_id,
                seq=4,
                step_type="terminal",
                tool="emit",
                tool_output={"emitted_ids": [str(uuid.uuid4())]},
            ),
        ]

        def fake_loop(now, db, **kwargs):
            on_step = kwargs.get("on_step")
            for s in steps:
                if on_step:
                    on_step(s)
            return ForecasterResult(
                agent_run_id=run_id,
                status="completed",
                step_count=4,
                emitted_ids=steps[-1]["output"]["emitted_ids"],
            )

        with patch("agents.api.routes.psycopg.connect", return_value=self._mock_db()), patch(
            "agents.forecaster.loop.run_forecaster_loop", side_effect=fake_loop
        ):
            r = self.client.post("/agent/forecaster/fire", headers=self.headers)
            self.assertEqual(r.status_code, 200)
            self.assertIn("text/event-stream", r.headers["content-type"])
            events = _parse_sse(r.text)
            types = [e["step_type"] for e in events]
            self.assertEqual(types, ["thought", "action", "observation", "terminal"])
            self.assertIsNone(events[0]["geo_focus"])
            self.assertIsNotNone(events[2]["geo_focus"])
            self.assertEqual(events[2]["tool"], "run_skill")

    def test_preflight_gated(self):
        run_id = uuid.uuid4()

        def fake_loop(now, db, **kwargs):
            on_step = kwargs.get("on_step")
            payload = step_to_sse_payload(
                run_id,
                seq=1,
                step_type="gated",
                tool_output={"reason": "preflight_probe_failed"},
            )
            if on_step:
                on_step(payload)
            return ForecasterResult(
                agent_run_id=run_id,
                status="gated",
                step_count=1,
                error="preflight_probe_failed",
            )

        with patch("agents.api.routes.psycopg.connect", return_value=self._mock_db()), patch(
            "agents.forecaster.loop.run_forecaster_loop", side_effect=fake_loop
        ):
            r = self.client.post("/agent/forecaster/fire", headers=self.headers)
            events = _parse_sse(r.text)
            self.assertEqual(events[-1]["step_type"], "gated")
            self.assertEqual(events[-1]["output"]["reason"], "preflight_probe_failed")

    def test_max_in_flight_gated_no_loop(self):
        with patch(
            "agents.api.routes.psycopg.connect", return_value=self._mock_db(in_flight=2)
        ), patch("agents.forecaster.loop.run_forecaster_loop") as mock_loop, patch(
            "agents.api.routes.at_capacity", return_value=True
        ):
            r = self.client.post("/agent/forecaster/fire", headers=self.headers)
            self.assertEqual(r.status_code, 200)
            events = _parse_sse(r.text)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["step_type"], "gated")
            self.assertEqual(events[0]["output"]["reason"], "max_in_flight")
            self.assertIsNone(events[0]["run_id"])
            mock_loop.assert_not_called()


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.run_id = str(uuid.uuid4())

    def test_replay_read_only_sequence(self):
        rows = [
            {
                "seq": 1,
                "step_type": "thought",
                "tool": None,
                "tool_input": None,
                "tool_output": {"text": "t"},
                "geo_focus": None,
                "created_at": datetime.now(timezone.utc),
            },
            {
                "seq": 2,
                "step_type": "terminal",
                "tool": "emit",
                "tool_input": None,
                "tool_output": {"emitted_ids": []},
                "geo_focus": None,
                "created_at": datetime.now(timezone.utc),
            },
        ]
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)

        with patch("agents.api.routes.psycopg.connect", return_value=conn), patch(
            "agents.api.routes.get_run",
            return_value={"id": self.run_id, "status": "completed"},
        ), patch("agents.api.routes.iter_steps", return_value=rows) as mock_steps, patch(
            "agents.api.routes.call_messages", create=True
        ):
            # Ensure no LLM wrapper import path is exercised — patch llm if pulled
            with patch("agent.lib.llm_client.call_messages") as mock_llm:
                r = self.client.get(f"/agent/run/{self.run_id}/replay")
                self.assertEqual(r.status_code, 200)
                events = _parse_sse(r.text)
                self.assertEqual([e["step_type"] for e in events], ["thought", "terminal"])
                mock_steps.assert_called()
                mock_llm.assert_not_called()

    def test_replay_404(self):
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        with patch("agents.api.routes.psycopg.connect", return_value=conn), patch(
            "agents.api.routes.get_run", return_value=None
        ):
            r = self.client.get(f"/agent/run/{uuid.uuid4()}/replay")
            self.assertEqual(r.status_code, 404)


class CriticFireTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.headers = {"Authorization": "Bearer test-operator-token"}

    def _mock_db(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = (0,)
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        return conn

    def test_critic_fire_streams_terminal(self):
        run_id = uuid.uuid4()
        steps = [
            step_to_sse_payload(
                run_id, seq=1, step_type="thought", tool_output={"text": "inspect"}
            ),
            step_to_sse_payload(
                run_id,
                seq=2,
                step_type="action",
                tool="mutate_skill",
                tool_input={"skill_id": "wildfire_risk_elevated"},
            ),
            step_to_sse_payload(
                run_id,
                seq=3,
                step_type="terminal",
                tool="mutate_skill",
                tool_output={"proposal_ids": ["prop-1"]},
            ),
        ]

        def fake_loop(now, db, **kwargs):
            on_step = kwargs.get("on_step")
            for s in steps:
                if on_step:
                    on_step(s)
            return CriticResult(
                agent_run_id=run_id,
                status="completed",
                step_count=3,
                proposal_ids=["prop-1"],
            )

        with patch("agents.api.routes.psycopg.connect", return_value=self._mock_db()), patch(
            "agents.critic.loop.run_critic_loop", side_effect=fake_loop
        ):
            r = self.client.post("/agent/critic/fire", headers=self.headers)
            self.assertEqual(r.status_code, 200)
            events = _parse_sse(r.text)
            self.assertEqual(
                [e["step_type"] for e in events],
                ["thought", "action", "terminal"],
            )
            self.assertNotEqual(events[0].get("output", {}).get("reason"), "critic_not_shipped")
            self.assertEqual(events[-1]["output"]["proposal_ids"], ["prop-1"])


class PayloadHelperTests(unittest.TestCase):
    def test_format_sse_and_gated(self):
        ev = gated_event(reason="max_in_flight")
        text = format_sse("step", ev)
        self.assertIn("event: step", text)
        self.assertIn("max_in_flight", text)
        thought = step_to_sse_payload(
            uuid.uuid4(), seq=1, step_type="thought", tool_output={"text": "x"}
        )
        self.assertIsNone(thought["geo_focus"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
