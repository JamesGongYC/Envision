#!/usr/bin/env python3
"""Tests for v3 Day 3 selector + shadow deployment."""
from __future__ import annotations

import importlib.util
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

from agent.evolution.selector import (  # noqa: E402
    CandidateRow,
    PARENT_SPAM_MULTIPLIER,
    select_candidates,
)
from agent.evolution.shadow_runner import (  # noqa: E402
    SHADOW_RATE_LIMIT,
    _apply_rate_limit,
)
from agent.lib.forecast_model import BacktestRun, Forecast  # noqa: E402
from agent.lib.forecast_writer import emit_forecasts  # noqa: E402
from agent.lib.repo_env import load_repo_env  # noqa: E402

load_repo_env()

DATABASE_URL = os.environ.get("DATABASE_URL")
HAS_DB = bool(DATABASE_URL)

W1 = (
    datetime(2026, 4, 1, tzinfo=timezone.utc),
    datetime(2026, 4, 3, tzinfo=timezone.utc),
)
W2 = (
    datetime(2026, 4, 4, tzinfo=timezone.utc),
    datetime(2026, 4, 6, tzinfo=timezone.utc),
)
W3 = (
    datetime(2026, 4, 7, tzinfo=timezone.utc),
    datetime(2026, 4, 9, tzinfo=timezone.utc),
)
WINDOWS = [W1, W2, W3]
VIABILITY = (
    datetime(2026, 6, 1, tzinfo=timezone.utc),
    datetime(2026, 6, 8, tzinfo=timezone.utc),
)


def _bt_run(
    ws: datetime,
    we: datetime,
    *,
    skill_id: str = "wildfire_risk_elevated",
    brier: float = 0.3,
    emitted: int = 5,
    lineage_id: str | None = None,
    version: int | None = None,
) -> BacktestRun:
    return BacktestRun(
        id=str(uuid.uuid4()),
        skill_id=skill_id,
        window_start=ws,
        window_end=we,
        brier_score=brier,
        forecasts_emitted=emitted,
        lineage_id=lineage_id,
        version=version,
    )


def _make_forecasts(n: int) -> list[Forecast]:
    now = datetime.now(timezone.utc)
    out = []
    for _ in range(n):
        out.append(
            Forecast(
                id=str(uuid.uuid4()),
                issued_at=now,
                valid_from=now,
                valid_until=now,
                disaster_class="wildfire",
                geometry='{"type":"Point","coordinates":[0,0]}',
                probability=0.5,
                skill_id="wildfire_risk_elevated",
                skill_version=1,
                contributing_signal_ids=[],
                reasoning="test",
                trace={},
            )
        )
    return out


class WriterTests(unittest.TestCase):
    def test_emit_shadow_requires_lineage_id(self):
        db = MagicMock()
        with self.assertRaises(ValueError) as ctx:
            emit_forecasts(_make_forecasts(1), db, table="forecasts_shadow")
        self.assertIn("lineage_id", str(ctx.exception))


class ShadowRunnerTests(unittest.TestCase):
    def test_shadow_runner_rate_limit(self):
        batch = _make_forecasts(200)
        capped, pathological = _apply_rate_limit(batch, "lineage-abc")
        self.assertTrue(pathological)
        self.assertEqual(len(capped), SHADOW_RATE_LIMIT)
        for f in capped:
            trace = f.trace if isinstance(f.trace, dict) else json.loads(f.trace)
            self.assertTrue(trace.get("pathological"))


class SelectorUnitTests(unittest.TestCase):
    def _candidate(self, lineage_id: str) -> CandidateRow:
        return CandidateRow(
            proposal_id=str(uuid.uuid4()),
            lineage_id=lineage_id,
            skill_id="wildfire_risk_elevated",
            source_code="def run(now, db):\n    return []\n",
            current_version=1,
        )

    @patch("agent.evolution.selector._count_gt_post_epoch")
    @patch("agent.evolution.selector.build_viability_window")
    @patch("agent.evolution.selector.load_pending_candidates")
    @patch("agent.evolution.selector._viability_gate")
    @patch("agent.evolution.selector.load_parent_lineage")
    def test_selector_advances_on_thin_ground_truth(
        self, mock_parent, mock_viab, mock_load, mock_viab_window, mock_gt_count
    ):
        mock_load.return_value = [self._candidate("c1")]
        mock_viab_window.return_value = VIABILITY
        mock_gt_count.return_value = 7
        mock_parent.return_value = ("parent-lid", "parent code")
        mock_viab.return_value = (True, [])
        db = MagicMock()
        result = select_candidates(db, dry_run=True)
        self.assertEqual(result.selected_lineage_ids, ["c1"])
        self.assertNotIn("c1", result.rejections)

    @patch("agent.evolution.selector._count_gt_post_epoch")
    @patch("agent.evolution.selector.build_viability_window")
    @patch("agent.evolution.selector.load_pending_candidates")
    @patch("agent.evolution.selector._viability_gate")
    @patch("agent.evolution.selector.load_parent_lineage")
    def test_selector_rejects_zero_emit(
        self, mock_parent, mock_viab, mock_load, mock_viab_window, mock_gt_count
    ):
        mock_load.return_value = [self._candidate("c1")]
        mock_viab_window.return_value = VIABILITY
        mock_gt_count.return_value = 7
        mock_parent.return_value = ("parent-lid", "parent code")
        mock_viab.return_value = (False, ["candidate emitted 0 forecasts on window"])
        db = MagicMock()
        result = select_candidates(db, dry_run=True)
        self.assertEqual(result.selected_lineage_ids, [])
        self.assertIn("c1", result.rejections)

    @patch("agent.evolution.selector._count_gt_post_epoch")
    @patch("agent.evolution.selector.build_viability_window")
    @patch("agent.evolution.selector.load_pending_candidates")
    @patch("agent.evolution.selector._viability_gate")
    @patch("agent.evolution.selector.load_parent_lineage")
    def test_selector_rejects_spam_over_3x_parent(
        self, mock_parent, mock_viab, mock_load, mock_viab_window, mock_gt_count
    ):
        mock_load.return_value = [self._candidate("c1")]
        mock_viab_window.return_value = VIABILITY
        mock_gt_count.return_value = 7
        mock_parent.return_value = ("parent-lid", "parent code")
        mock_viab.return_value = (
            False,
            ["forecast spam: 16 > 15 (parent emitted 5)"],
        )
        db = MagicMock()
        result = select_candidates(db, dry_run=True)
        self.assertEqual(result.selected_lineage_ids, [])
        self.assertIn("c1", result.rejections)

    @patch("agent.evolution.selector._count_gt_post_epoch")
    @patch("agent.evolution.selector.build_viability_window")
    @patch("agent.evolution.selector.load_pending_candidates")
    @patch("agent.evolution.selector._viability_gate")
    @patch("agent.evolution.selector.load_parent_lineage")
    def test_selector_advances_all_qualifiers_no_topk_cap(
        self, mock_parent, mock_viab, mock_load, mock_viab_window, mock_gt_count
    ):
        cands = [self._candidate(f"c{i}") for i in range(5)]
        mock_load.return_value = cands
        mock_viab_window.return_value = VIABILITY
        mock_gt_count.return_value = 7
        mock_parent.return_value = ("parent-lid", "parent code")
        mock_viab.return_value = (True, [])
        db = MagicMock()
        result = select_candidates(db, dry_run=True)
        self.assertEqual(len(result.selected_lineage_ids), 5)
        for i in range(5):
            self.assertIn(f"c{i}", result.selected_lineage_ids)

    @patch("agent.evolution.selector.build_disjoint_windows")
    @patch("agent.evolution.selector._count_gt_post_epoch")
    @patch("agent.evolution.selector.build_viability_window")
    @patch("agent.evolution.selector.load_pending_candidates")
    @patch("agent.evolution.selector._viability_gate")
    @patch("agent.evolution.selector.backtest_skill")
    @patch("agent.evolution.selector.load_parent_lineage")
    def test_selector_pathology_rejects_zero_emit_despite_viability(
        self,
        mock_parent,
        mock_bt,
        mock_viab,
        mock_load,
        mock_viab_window,
        mock_gt_count,
        mock_windows,
    ):
        mock_load.return_value = [self._candidate("c1")]
        mock_viab_window.return_value = VIABILITY
        mock_gt_count.return_value = 30
        mock_windows.return_value = WINDOWS
        mock_parent.return_value = ("parent-lid", "parent code")
        mock_viab.return_value = (True, [])

        def side_effect(skill_id, windows, db, **kwargs):
            is_parent = kwargs.get("lineage_id") == "parent-lid"
            ws, we = windows[0]
            if (ws, we) == VIABILITY:
                emitted = 5
            elif is_parent:
                emitted = 5
            elif ws == W1[0]:
                emitted = 0
            else:
                emitted = 5
            return [
                _bt_run(
                    ws,
                    we,
                    emitted=emitted,
                    lineage_id=kwargs.get("lineage_id"),
                    version=kwargs.get("version"),
                )
            ]

        mock_bt.side_effect = side_effect
        db = MagicMock()
        result = select_candidates(db, dry_run=True)
        self.assertEqual(result.selected_lineage_ids, [])
        self.assertIn("c1", result.rejections)


class EvaluatorTests(unittest.TestCase):
    def test_evaluator_live_unchanged(self):
        run_path = (
            REPO_ROOT / "agent" / "modal_skills" / "forecast-evaluator" / "run.py"
        )
        source = run_path.read_text(encoding="utf-8")
        self.assertIn("FROM forecasts f", source)
        self.assertIn("LEFT JOIN evaluations e ON e.forecast_id = f.id", source)
        self.assertIn("def evaluate_live_forecasts(", source)
        self.assertIn("def evaluate_shadow_forecasts(", source)
        self.assertIn("INSERT INTO evaluations", source)
        self.assertIn("INSERT INTO shadow_evaluations", source)

    def test_evaluator_live_path_isolated(self):
        spec = importlib.util.spec_from_file_location(
            "forecast_evaluator_run",
            REPO_ROOT / "agent" / "modal_skills" / "forecast-evaluator" / "run.py",
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)

        db = MagicMock()
        db.cursor.return_value.__enter__.return_value.fetchall.return_value = []

        with patch.object(mod, "insert_shadow_evaluation") as mock_shadow:
            n = mod.evaluate_live_forecasts(datetime.now(timezone.utc), db)
            mock_shadow.assert_not_called()
        self.assertEqual(n, 0)


class PublicRouteTests(unittest.TestCase):
    def test_public_routes_never_query_shadow(self):
        scan_paths = [
            REPO_ROOT / "viewer" / "lib" / "queries.ts",
            REPO_ROOT / "viewer" / "app" / "page.tsx",
            REPO_ROOT / "viewer" / "app" / "forecast" / "[id]" / "page.tsx",
        ]
        forbidden = ("forecasts_shadow", "shadow_evaluations")
        for path in scan_paths:
            self.assertTrue(path.is_file(), f"missing {path}")
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(
                    token,
                    text,
                    f"{path.name} must not reference {token}",
                )


@unittest.skipUnless(HAS_DB, "DATABASE_URL required")
class SelectorIntegrationTests(unittest.TestCase):
    def test_build_disjoint_windows_returns_disjoint_or_empty(self):
        import psycopg
        from agent.evolution.selector import build_disjoint_windows

        with psycopg.connect(DATABASE_URL) as db:
            windows = build_disjoint_windows(db, "wildfire_risk_elevated")
        for i in range(len(windows) - 1):
            self.assertLess(windows[i][1], windows[i + 1][0])


def main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (
        WriterTests,
        ShadowRunnerTests,
        SelectorUnitTests,
        EvaluatorTests,
        PublicRouteTests,
        SelectorIntegrationTests,
    ):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
