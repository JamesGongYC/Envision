#!/usr/bin/env python3
"""Backfill skill_lineage rows for the four manual detection skills."""
from __future__ import annotations

import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.evolution.skill_loader import SKILL_FOLDERS  # noqa: E402
from agent.evolution.skill_surface import extract_mutation_surface  # noqa: E402
from agent.lib.repo_env import load_repo_env  # noqa: E402



def _read_version(run_py: Path) -> int:
    text = run_py.read_text(encoding="utf-8")
    m = re.search(r"^SKILL_VERSION\s*=\s*(\d+)", text, re.MULTILINE)
    return int(m.group(1)) if m else 1


def backfill(db) -> int:
    inserted = 0
    for skill_id, folder in SKILL_FOLDERS.items():
        skill_dir = REPO_ROOT / "agent" / "modal_skills" / folder
        run_py = skill_dir / "run.py"
        skill_md = skill_dir / "SKILL.md"
        version = _read_version(run_py)
        source = extract_mutation_surface(run_py.read_text(encoding="utf-8"))
        md = skill_md.read_text(encoding="utf-8") if skill_md.is_file() else ""

        with db.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM skill_lineage WHERE skill_id = %s AND version = %s",
                (skill_id, version),
            )
            if cur.fetchone():
                print(f"[lineage] skip {skill_id} v{version} (exists)")
                continue
            cur.execute(
                """
                INSERT INTO skill_lineage (
                  id, skill_id, parent_skill_id, version,
                  source_code, skill_md, generation_method, status
                ) VALUES (%s, %s, NULL, %s, %s, %s, 'manual', 'promoted')
                """,
                (str(uuid.uuid4()), skill_id, version, source, md),
            )
        inserted += 1
        print(f"[lineage] inserted {skill_id} v{version}")
    db.commit()
    return inserted


def main() -> int:
    load_repo_env()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print(
            "DATABASE_URL required — add it to envision/.env "
            "(see .env.example) or viewer/.env.local",
            file=sys.stderr,
        )
        return 2
    sys.path.insert(0, str(REPO_ROOT))
    with psycopg.connect(database_url, autocommit=False) as db:
        n = backfill(db)
    print(f"[lineage] done: {n} new row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
