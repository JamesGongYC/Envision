#!/usr/bin/env python3
"""Unit tests for trace_builder."""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Allow `from trace_builder import ...` when run as script or module.
_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from trace_builder import (  # noqa: E402
    SOFT_CAP_BYTES,
    CuratorTraceBuilder,
    TraceBuilder,
    _serialized_size,
)


class TraceBuilderTests(unittest.TestCase):
    def test_required_keys(self) -> None:
        now = datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)
        tb = TraceBuilder(now, "wildfire_rapid_growth")
        tb.set_inputs(hotspot_count_last_24h=10, hotspot_count_prior_24h=5)
        tb.set_intermediate(growing_cells=[], threshold_met_count=0)
        tb.add_geometry_step("cell_boundaries_emitted", bboxes=[])
        tb.set_probability_components(base=0.45, growth_factor=0.1, persistence_factor=0.05)
        trace = tb.build()
        for key in ("now", "inputs", "intermediate", "geometry_steps", "probability_components"):
            self.assertIn(key, trace)
        self.assertEqual(trace["now"], "2026-05-30T12:00:00+00:00")

    def test_json_safe_numpy_like(self) -> None:
        class FakeNumpy:
            def item(self):
                return 3.14

        now = datetime(2026, 5, 30, tzinfo=timezone.utc)
        tb = TraceBuilder(now, "test")
        tb.set_inputs(x=FakeNumpy())
        tb.set_intermediate(growing_cells=[], threshold_met_count=0)
        tb.add_geometry_step("s", bboxes=[])
        tb.set_probability_components(base=0.4, growth_factor=0.0, persistence_factor=0.0)
        trace = tb.build()
        self.assertEqual(trace["inputs"]["x"], 3.14)

    def test_truncation_marker(self) -> None:
        now = datetime(2026, 5, 30, tzinfo=timezone.utc)
        tb = TraceBuilder(now, "wildfire_rapid_growth")
        tb.set_inputs(hotspot_count_last_24h=1, hotspot_count_prior_24h=1)
        big = [{"cell_id": str(i), "growth_ratio": 1.5, "days_consecutive": 2} for i in range(2000)]
        tb.set_intermediate(growing_cells=big, threshold_met_count=2000)
        tb.add_geometry_step("cell_boundaries_emitted", bboxes=[[0, 0, 1, 1]] * 500)
        tb.set_probability_components(base=0.45, growth_factor=0.1, persistence_factor=0.05)
        trace = tb.build()
        self.assertTrue(trace.get("_truncated"))
        self.assertLessEqual(_serialized_size(trace), SOFT_CAP_BYTES + 512)

    def test_fork_resets_probability(self) -> None:
        now = datetime(2026, 5, 30, tzinfo=timezone.utc)
        base = TraceBuilder(now, "wildfire_rapid_growth")
        base.set_inputs(a=1)
        base.set_intermediate(growing_cells=[], threshold_met_count=0)
        base.add_geometry_step("cell_boundaries_emitted", bboxes=[])
        base.set_probability_components(base=0.5, growth_factor=0.1, persistence_factor=0.0)
        child = base.fork()
        child.set_probability_components(base=0.6, growth_factor=0.2, persistence_factor=0.1)
        t1 = base.build()
        t2 = child.build()
        self.assertEqual(t1["probability_components"]["base"], 0.5)
        self.assertEqual(t2["probability_components"]["base"], 0.6)


class CuratorTraceBuilderTests(unittest.TestCase):
    def test_required_keys(self) -> None:
        ctb = CuratorTraceBuilder()
        ctb.set_brier_stats({"wildfire_rapid_growth": {"brier_14d": 0.2, "eval_count": 10}})
        ctb.set_ast_validation(passed=True)
        trace = ctb.build()
        self.assertIn("brier_stats_observed", trace)
        self.assertIn("ast_validation", trace)
        self.assertTrue(trace["ast_validation"]["passed"])

    def test_llm_truncation_first(self) -> None:
        ctb = CuratorTraceBuilder()
        ctb.set_brier_stats({"s": {"brier_14d": 0.1, "eval_count": 5}})
        ctb.set_ast_validation(passed=True)
        ctb.set_llm_response("x" * 50_000)
        trace = ctb.build()
        self.assertTrue(trace.get("_truncated"))
        self.assertLess(len(trace["llm_response_full"]), 50_000)


if __name__ == "__main__":
    unittest.main()
