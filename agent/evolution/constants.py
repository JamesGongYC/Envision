"""Evolution and backtest constants."""
from __future__ import annotations

from datetime import datetime, timezone

# First full day of clean post-seed, post-outage ingestion (UTC).
BACKTEST_EPOCH = datetime(2026, 6, 4, 0, 0, tzinfo=timezone.utc)

SEED_CUTOFF = datetime(2026, 5, 29, 0, 0, tzinfo=timezone.utc)

SEED_SKILL_IDS = (
    "wildfire_risk_elevated",
    "wildfire_rapid_growth",
)
