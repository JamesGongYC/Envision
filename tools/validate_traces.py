#!/usr/bin/env python3
"""Read-only validation for forecasts.trace and curator_trace (v2 Day 6)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field

import psycopg

DATABASE_URL = os.environ.get("DATABASE_URL")

DETECTION_SKILLS = (
    "wildfire_rapid_growth",
    "typhoon_intensifying",
    "typhoon_landfall_imminent",
    "wildfire_risk_elevated",
)

DETECTION_REQUIRED = (
    "now",
    "inputs",
    "intermediate",
    "geometry_steps",
    "probability_components",
)

CURATOR_REQUIRED = ("brier_stats_observed", "ast_validation")

HARD_CAP = 16_384
TRUNCATION_WARN_RATE = 0.05


@dataclass
class ComponentResult:
    component: str
    sampled: int = 0
    missing_keys: int = 0
    oversize: int = 0
    truncated: int = 0
    empty_trace: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def truncated_rate(self) -> float:
        if self.sampled == 0:
            return 0.0
        return self.truncated / self.sampled

    @property
    def hard_fail(self) -> bool:
        return self.missing_keys > 0 or self.oversize > 0

    @property
    def status(self) -> str:
        if self.sampled == 0:
            return "WARN"
        if self.hard_fail:
            return "FAIL"
        if self.truncated_rate > TRUNCATION_WARN_RATE:
            return "WARN"
        if self.empty_trace > 0:
            return "WARN"
        return "PASS"


def check_detection_trace(trace_obj: dict) -> list[str]:
    missing = [k for k in DETECTION_REQUIRED if k not in trace_obj]
    return missing


def check_curator_trace(trace_obj: dict) -> list[str]:
    missing = [k for k in CURATOR_REQUIRED if k not in trace_obj]
    return missing


def validate_forecasts(cur, skill_id: str, hours: int) -> ComponentResult:
    res = ComponentResult(component=skill_id)
    cur.execute(
        """
        SELECT trace::text, trace
        FROM forecasts
        WHERE skill_id = %s
          AND issued_at > now() - make_interval(hours => %s)
        ORDER BY issued_at DESC
        LIMIT 5
        """,
        (skill_id, hours),
    )
    rows = cur.fetchall()
    res.sampled = len(rows)
    if not rows:
        res.notes.append("no forecasts in window")
        return res

    for trace_text, trace_obj in rows:
        if not trace_obj or trace_obj == {}:
            res.empty_trace += 1
            continue
        if isinstance(trace_text, str):
            size = len(trace_text.encode("utf-8"))
        else:
            size = len(json.dumps(trace_obj).encode("utf-8"))
        if size > HARD_CAP:
            res.oversize += 1
        if trace_obj.get("_truncated"):
            res.truncated += 1
        missing = check_detection_trace(trace_obj)
        if missing:
            res.missing_keys += 1
            res.notes.append(f"missing {missing}")

    return res


def validate_curator(cur, hours: int) -> ComponentResult:
    res = ComponentResult(component="curator")
    cur.execute(
        """
        SELECT curator_trace::text, curator_trace
        FROM skill_edit_proposals
        WHERE proposed_at > now() - make_interval(hours => %s)
        ORDER BY proposed_at DESC
        LIMIT 5
        """,
        (hours,),
    )
    rows = cur.fetchall()
    res.sampled = len(rows)
    if not rows:
        res.notes.append("no proposals in window")
        return res

    for trace_text, trace_obj in rows:
        if not trace_obj or trace_obj == {}:
            res.empty_trace += 1
            continue
        if isinstance(trace_text, str):
            size = len(trace_text.encode("utf-8"))
        else:
            size = len(json.dumps(trace_obj).encode("utf-8"))
        if size > HARD_CAP:
            res.oversize += 1
        if trace_obj.get("_truncated"):
            res.truncated += 1
        missing = check_curator_trace(trace_obj)
        if missing:
            res.missing_keys += 1
            res.notes.append(f"missing {missing}")

    return res


def print_table(results: list[ComponentResult]) -> None:
    print()
    print(
        "| component | sampled | missing_keys | oversize | truncated_rate | status |"
    )
    print("|---|---:|---:|---:|---:|---|")
    for r in results:
        rate = f"{r.truncated_rate:.0%}" if r.sampled else "n/a"
        print(
            f"| {r.component} | {r.sampled} | {r.missing_keys} | {r.oversize} | "
            f"{rate} | {r.status} |"
        )
    print()
    for r in results:
        if r.notes:
            print(f"**{r.component}**: {'; '.join(r.notes)}")
    print()


def main() -> int:
    p = argparse.ArgumentParser(description="Validate trace JSONB columns")
    p.add_argument("--hours", type=int, default=24, help="Lookback window (default: 24)")
    args = p.parse_args()

    if not DATABASE_URL:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    results: list[ComponentResult] = []
    with psycopg.connect(DATABASE_URL) as db:
        with db.cursor() as cur:
            for skill_id in DETECTION_SKILLS:
                results.append(validate_forecasts(cur, skill_id, args.hours))
            results.append(validate_curator(cur, args.hours))

    print_table(results)

    hard = [r for r in results if r.hard_fail]
    warns = [r for r in results if r.status == "WARN"]
    if hard:
        print(
            f"Validation FAILED for: {', '.join(r.component for r in hard)}",
            file=sys.stderr,
        )
        return 1
    if warns:
        print(
            f"Validation warnings: {', '.join(r.component for r in warns)}",
            file=sys.stderr,
        )
    print("Validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
