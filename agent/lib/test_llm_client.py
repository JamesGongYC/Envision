"""Unit tests for llm_client — no production DB writes."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from anthropic import APIStatusError


class TestLlmClient(unittest.TestCase):
    def _make_client_mock(self, side_effects: list) -> MagicMock:
        client = MagicMock()
        client.messages.create.side_effect = side_effects
        return client

    def test_4xx_not_retried(self):
        from agent.lib import llm_client

        err = APIStatusError(
            message="bad request",
            response=MagicMock(status_code=400, headers={}),
            body={"error": {"type": "invalid_request_error"}},
        )
        mock_client = self._make_client_mock([err])

        with patch("anthropic.Anthropic", return_value=mock_client), patch.dict(
            "os.environ", {"ANTHROPIC_API_KEY": "test-key"}
        ):
            with self.assertRaises(APIStatusError):
                llm_client.call_messages(
                    call_site="narrator",
                    db=None,
                    messages=[{"role": "user", "content": "hi"}],
                    model="claude-test",
                    fallback_model=None,
                    max_tokens=10,
                )

        self.assertEqual(mock_client.messages.create.call_count, 1)

    def test_429_honors_retry_after(self):
        from agent.lib import llm_client

        ok_response = MagicMock()
        ok_response.content = [MagicMock(text="ok", type="text")]
        ok_response.usage = MagicMock(
            input_tokens=1, output_tokens=1, cache_read_input_tokens=0
        )
        ok_response._request_id = "req_test"

        err = APIStatusError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={"retry-after": "1"}),
            body={"error": {"type": "rate_limit_error"}},
        )
        mock_client = self._make_client_mock([err, ok_response])

        with patch("anthropic.Anthropic", return_value=mock_client), patch(
            "agent.lib.llm_client.time"
        ) as mock_time, patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            resp, model = llm_client.call_messages(
                call_site="probe",
                db=None,
                messages=[{"role": "user", "content": "ping"}],
                model="claude-test",
                fallback_model=None,
                max_tokens=5,
            )

        self.assertEqual(mock_client.messages.create.call_count, 2)
        mock_time.sleep.assert_called_once_with(1.0)
        self.assertEqual(model, "claude-test")
        self.assertIs(resp, ok_response)


if __name__ == "__main__":
    unittest.main()
