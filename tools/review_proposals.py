#!/usr/bin/env python3
"""
review_proposals — Envision operator CLI (v3).

Human gate between shadow evaluation and production promotion.
Evolution components never deploy; this tool writes run.py and prints
the modal deploy command for the operator.

Usage:
  python review_proposals.py list [--status pending]
  python review_proposals.py show <proposal_id>
  python review_proposals.py promote <proposal_id> [--force --confirm PROMOTE ANYWAY]
  python review_proposals.py discard <proposal_id>
  python review_proposals.py approve <proposal_id>   # deprecated → promote
  python review_proposals.py reject <proposal_id>    # deprecated → discard
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from agent.evolution.proposal_review import (  # noqa: E402
    PROMOTE_CONFIRM,
    blocked_on,
    discard_proposal,
    fetch_proposal,
    list_proposals,
    promote_proposal,
    shadow_metrics,
    source_diff,
    backtest_summary,
    parent_live_brier_14d,
)
from agent.lib.repo_env import load_repo_env  # noqa: E402

load_repo_env()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("DATABASE_URL not set", file=sys.stderr)
    sys.exit(2)


def short_id(uid: str, n: int = 8) -> str:
    return str(uid)[:n]


def conn_cm():
    return psycopg.connect(DATABASE_URL, autocommit=False)


def cmd_list(args) -> int:
    with conn_cm() as db:
        rows = list_proposals(db, status=args.status)

    if not rows:
        print(f"No proposals with status='{args.status}'.")
        return 0

    print(
        f"{'ID':<10}  {'SKILL':<28}  {'LIN':<10}  {'BT':>6}  "
        f"{'SHADOW':>8}  {'N':>5}  BLOCKED_ON"
    )
    print("-" * 100)
    for r in rows:
        bt = r["backtest_mean_brier"]
        bt_s = f"{bt:.3f}" if bt is not None else "—"
        sh = r["shadow_brier"]
        sh_s = f"{sh:.3f}" if sh is not None else "—"
        block = "; ".join(r["blocked_on"]) if r["blocked_on"] else "—"
        print(
            f"{short_id(r['proposal_id']):<10}  {r['skill_id']:<28}  "
            f"{(r['lineage_status'] or '—'):<10}  {bt_s:>6}  {sh_s:>8}  "
            f"{r['shadow_n_evals']:>3}/20  {block[:40]}"
        )
    print(f"\n{len(rows)} proposal(s).")
    return 0


def cmd_show(args) -> int:
    with conn_cm() as db:
        prop = fetch_proposal(db, args.proposal_id)
        if not prop:
            print(f"No proposal found for prefix '{args.proposal_id}'.", file=sys.stderr)
            return 1

        shadow_brier, n_evals = shadow_metrics(db, prop.lineage_id)
        parent_brier = parent_live_brier_14d(db, prop.skill_id)
        bt = backtest_summary(db, prop.lineage_id)
        diff = source_diff(db, prop)
        blockers = blocked_on(db, prop)

    print("=" * 70)
    print(f"Proposal       : {prop.proposal_id}")
    print(f"Skill          : {prop.skill_id}")
    print(f"Version        : {prop.current_version} → {prop.current_version + 1} on promote")
    print(f"Status         : {prop.status} / lineage={prop.lineage_status}")
    print(f"Proposed at    : {prop.proposed_at.isoformat(timespec='seconds')}")
    print(f"Parent 14d Brier: {parent_brier:.4f}" if parent_brier else "Parent 14d Brier: —")
    print(f"Shadow Brier   : {shadow_brier:.4f} ({n_evals} evals)" if shadow_brier else f"Shadow evals : {n_evals}/20")
    print(f"Blocked on     : {'; '.join(blockers) if blockers else 'eligible for review'}")
    print("=" * 70)
    print("\n--- Rationale ---")
    print(prop.curator_reasoning or "(none)")
    if prop.curator_trace:
        print("\n--- Validation ---")
        stages = prop.curator_trace.get("validation_stages") or []
        for s in stages:
            mark = "ok" if s.get("passed") else "FAIL"
            print(f"  {s.get('stage')}: {mark}")
        attempts = prop.curator_trace.get("attempts") or []
        if attempts:
            print(f"  mutation attempts: {len(attempts)}")
    if bt:
        print("\n--- Backtest windows ---")
        for ws, we, brier, emitted in bt:
            print(f"  {ws.date()}–{we.date()}: brier={brier} emitted={emitted}")
    print("\n--- Source diff (parent vs candidate) ---")
    print(diff)
    print("=" * 70)
    return 0


def cmd_promote(args) -> int:
    with conn_cm() as db:
        ok, msg = promote_proposal(
            db,
            args.proposal_id,
            force=args.force,
            force_confirm=args.confirm,
            repo_root=REPO_ROOT,
        )
    if ok:
        print(msg)
        return 0
    print(msg, file=sys.stderr)
    return 1


def cmd_discard(args) -> int:
    with conn_cm() as db:
        ok, msg = discard_proposal(db, args.proposal_id)
    if ok:
        print(msg)
        return 0
    print(msg, file=sys.stderr)
    return 1


def cmd_approve(args) -> int:
    print("WARN: approve is deprecated; use promote", file=sys.stderr)
    return cmd_promote(args)


def cmd_reject(args) -> int:
    print("WARN: reject is deprecated; use discard", file=sys.stderr)
    return cmd_discard(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Review v3 skill evolution proposals.")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List proposals with shadow/backtest readouts.")
    p_list.add_argument(
        "--status", default="pending",
        choices=("pending", "approved", "rejected"),
    )
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show diff, rationale, metrics.")
    p_show.add_argument("proposal_id")
    p_show.set_defaults(func=cmd_show)

    p_prom = sub.add_parser("promote", help="Human gate: promote to production run.py.")
    p_prom.add_argument("proposal_id")
    p_prom.add_argument("--force", action="store_true")
    p_prom.add_argument("--confirm", default=None, help=f"Required with --force: {PROMOTE_CONFIRM}")
    p_prom.set_defaults(func=cmd_promote)

    p_disc = sub.add_parser("discard", help="Reject and archive candidate.")
    p_disc.add_argument("proposal_id")
    p_disc.set_defaults(func=cmd_discard)

    p_app = sub.add_parser("approve", help="Deprecated alias for promote.")
    p_app.add_argument("proposal_id")
    p_app.add_argument("--force", action="store_true")
    p_app.add_argument("--confirm", default=None)
    p_app.set_defaults(func=cmd_approve)

    p_rej = sub.add_parser("reject", help="Deprecated alias for discard.")
    p_rej.add_argument("proposal_id")
    p_rej.set_defaults(func=cmd_reject)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    try:
        args = build_parser().parse_args()
        sys.exit(args.func(args))
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
