#!/usr/bin/env python3
"""
review_proposals — Envision Day 4 CLI.

The gate between the Curator's autopilot and the live skill library.
Curator proposals land in `skill_edit_proposals` with status='pending';
this tool lets a human review and approve or reject them.

Approval marks the row approved and PRINTS the path where the new code
should be deployed. Actual file replacement is intentionally manual in
v1 — we don't want a CLI command to silently overwrite skill files.

Usage:
  python review_proposals.py list
  python review_proposals.py list --status approved
  python review_proposals.py show <proposal_id>
  python review_proposals.py approve <proposal_id>
  python review_proposals.py reject  <proposal_id> [--reason "..."]
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

import psycopg

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("DATABASE_URL not set", file=sys.stderr)
    sys.exit(2)

HERMES_SKILLS_DIR = os.path.expanduser("~/.hermes/skills")


# --- helpers -------------------------------------------------------------
def short_id(uid: str, n: int = 8) -> str:
    return str(uid)[:n]


def conn_cm():
    return psycopg.connect(DATABASE_URL, autocommit=False)


def guess_skill_file(skill_id: str) -> str:
    """Convention: ~/.hermes/skills/<skill-id>/scripts/<something>.py.
    Curator's proposed_code replaces the main detect_*.py. We don't enforce
    the filename — just point the operator at the skill directory."""
    # Hermes uses hyphens in directory names; skill_id in DB may use underscores
    candidates = [
        skill_id,
        skill_id.replace("_", "-"),
        skill_id.replace("-", "_"),
    ]
    for c in candidates:
        path = os.path.join(HERMES_SKILLS_DIR, c)
        if os.path.isdir(path):
            return path
    return os.path.join(HERMES_SKILLS_DIR, skill_id) + "  (not found on disk)"


# --- subcommands ---------------------------------------------------------
def cmd_list(args) -> int:
    with conn_cm() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, skill_id, current_version, proposed_at, status
            FROM skill_edit_proposals
            WHERE status = %s
            ORDER BY proposed_at DESC
            LIMIT 50
            """,
            (args.status,),
        )
        rows = cur.fetchall()

    if not rows:
        print(f"No proposals with status='{args.status}'.")
        return 0

    print(f"{'ID':<10}  {'STATUS':<10}  {'SKILL':<30}  {'V':>3}  PROPOSED_AT")
    print("-" * 80)
    for pid, skill_id, ver, proposed_at, status in rows:
        print(f"{short_id(pid):<10}  {status:<10}  {skill_id:<30}  "
              f"{ver:>3}  {proposed_at.isoformat(timespec='seconds')}")
    print(f"\n{len(rows)} proposal(s) with status='{args.status}'.")
    return 0


def cmd_show(args) -> int:
    with conn_cm() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, skill_id, current_version, proposed_code,
                   curator_reasoning, proposed_at, status, reviewed_at
            FROM skill_edit_proposals
            WHERE id::text LIKE %s
            """,
            (args.proposal_id + "%",),
        )
        rows = cur.fetchall()

    if not rows:
        print(f"No proposal found with id prefix '{args.proposal_id}'.",
              file=sys.stderr)
        return 1
    if len(rows) > 1:
        print(f"Ambiguous id prefix '{args.proposal_id}' matches "
              f"{len(rows)} proposals — give more characters.",
              file=sys.stderr)
        return 1

    (pid, skill_id, ver, proposed_code, reasoning,
     proposed_at, status, reviewed_at) = rows[0]

    print("=" * 70)
    print(f"Proposal       : {pid}")
    print(f"Skill          : {skill_id}")
    print(f"Current version: {ver}  →  proposing version {ver + 1}")
    print(f"Status         : {status}")
    print(f"Proposed at    : {proposed_at.isoformat(timespec='seconds')}")
    if reviewed_at:
        print(f"Reviewed at    : {reviewed_at.isoformat(timespec='seconds')}")
    print(f"Skill dir      : {guess_skill_file(skill_id)}")
    print("=" * 70)
    print("\n--- Curator reasoning ---")
    print(reasoning or "(none)")
    print("\n--- Proposed code ---")
    print(proposed_code)
    print("=" * 70)
    return 0


def cmd_set_status(args, new_status: str) -> int:
    with conn_cm() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE skill_edit_proposals
                SET status = %s, reviewed_at = %s
                WHERE id::text LIKE %s AND status = 'pending'
                RETURNING id, skill_id, current_version
                """,
                (new_status, datetime.now(timezone.utc),
                 args.proposal_id + "%"),
            )
            rows = cur.fetchall()
        if not rows:
            conn.rollback()
            print(f"No PENDING proposal matched id prefix "
                  f"'{args.proposal_id}'. (Already reviewed? "
                  f"Use `show` to inspect.)", file=sys.stderr)
            return 1
        if len(rows) > 1:
            conn.rollback()
            print(f"Id prefix '{args.proposal_id}' matched "
                  f"{len(rows)} proposals — give more characters.",
                  file=sys.stderr)
            return 1
        conn.commit()

    pid, skill_id, ver = rows[0]
    print(f"Proposal {short_id(pid)} → {new_status}.")
    if new_status == "approved":
        print()
        print("Next steps (MANUAL — this tool does not overwrite files):")
        print(f"  1. cd {guess_skill_file(skill_id)}")
        print(f"  2. Back up the current script:")
        print(f"     cp scripts/detect_*.py scripts/_baseline_v{ver}.py")
        print(f"  3. Paste the new code from `show {short_id(pid)}` "
              f"into the appropriate scripts/*.py file.")
        print(f"  4. Skill is now at version {ver + 1}; future forecasts "
              f"from this skill will record skill_version = {ver + 1}.")
    return 0


def cmd_approve(args) -> int:
    return cmd_set_status(args, "approved")


def cmd_reject(args) -> int:
    return cmd_set_status(args, "rejected")


# --- entry --------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Review Curator-proposed skill edits."
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List proposals.")
    p_list.add_argument(
        "--status", default="pending",
        choices=("pending", "approved", "rejected"),
        help="Filter by status (default: pending).",
    )
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show full proposal.")
    p_show.add_argument("proposal_id", help="Full or prefix of proposal UUID.")
    p_show.set_defaults(func=cmd_show)

    p_app = sub.add_parser("approve", help="Mark a pending proposal approved.")
    p_app.add_argument("proposal_id", help="Full or prefix of proposal UUID.")
    p_app.set_defaults(func=cmd_approve)

    p_rej = sub.add_parser("reject", help="Mark a pending proposal rejected.")
    p_rej.add_argument("proposal_id", help="Full or prefix of proposal UUID.")
    p_rej.set_defaults(func=cmd_reject)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
