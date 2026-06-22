"""Unit tests for health_gate rolling window logic."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestHealthGate(unittest.TestCase):
    def test_single_529_does_not_trip_gate(self):
        from agent.lib.health_gate import should_abort_cycle

        db = MagicMock()
        cur = MagicMock()
        db.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        db.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cur.fetchone.return_value = (1, 1, 1.0)

        self.assertFalse(
            should_abort_cycle(db, min_samples=5, threshold=0.5)
        )

    def test_sustained_529_storm_trips_gate(self):
        from agent.lib.health_gate import should_abort_cycle

        db = MagicMock()
        cur = MagicMock()
        db.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        db.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cur.fetchone.return_value = (10, 8, 0.8)

        self.assertTrue(
            should_abort_cycle(db, min_samples=5, threshold=0.5)
        )

    def test_preflight_returns_false_on_529(self):
        from agent.lib import health_gate
        from anthropic import APIStatusError

        db = MagicMock()
        err = APIStatusError(
            message="overloaded",
            response=MagicMock(status_code=529, headers={}),
            body={"error": {"type": "overloaded_error"}},
        )
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}), patch.object(
            health_gate, "call_messages", side_effect=err
        ):
            self.assertFalse(health_gate.preflight_probe(db))


if __name__ == "__main__":
    unittest.main()
