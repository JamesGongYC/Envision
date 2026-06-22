"""Operator-seeded, condition-gated generator trigger (A2)."""
from __future__ import annotations

import os
import re

from psycopg import Connection

GENERATOR_ENABLED_VAR = "ENVISION_GENERATOR_ENABLED"
DISASTER_CLASS_VAR = "ENVISION_GENERATOR_DISASTER_CLASS"
PROMPT_VAR = "ENVISION_GENERATOR_PROMPT"

DISASTER_SIGNAL_TYPES: dict[str, frozenset[str]] = {
    "wildfire": frozenset({
        "hotspot",
        "fire_warning",
        "fire_weather",
        "fire_weather_grid",
        "heat_dome",
        "high_wind_corridor",
        "heavy_precipitation_band",
    }),
    "typhoon": frozenset({
        "cyclone_advisory",
        "cyclone_feature",
    }),
}


def is_generator_seeded() -> bool:
    val = os.environ.get(GENERATOR_ENABLED_VAR)
    if val is None or val == "":
        return False
    return val.strip().lower() in ("1", "true", "yes", "on", "y", "t")


def seeded_disaster_class() -> str | None:
    raw = os.environ.get(DISASTER_CLASS_VAR, "").strip().lower()
    if raw in ("wildfire", "typhoon"):
        return raw
    return None


def seed_prompt() -> str:
    return os.environ.get(PROMPT_VAR, "").strip()


def _referenced_signal_types(source: str) -> set[str]:
    return set(re.findall(r"signal_type\s*=\s*['\"]([^'\"]+)['\"]", source))


def _promoted_skill_sources(db: Connection) -> list[str]:
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT source_code FROM skill_lineage
            WHERE status = 'promoted' AND source_code IS NOT NULL
            """
        )
        return [row[0] for row in cur.fetchall() if row[0]]


def find_uncovered_signals(
    db: Connection, disaster_class: str
) -> list[tuple[str, str]]:
    allowed = DISASTER_SIGNAL_TYPES.get(disaster_class, frozenset())
    if not allowed:
        return []

    with db.cursor() as cur:
        cur.execute(
            "SELECT source, signal_type FROM signal_catalog ORDER BY 1, 2"
        )
        catalog = [(r[0], r[1]) for r in cur.fetchall() if r[1] in allowed]

    referenced: set[str] = set()
    for source in _promoted_skill_sources(db):
        referenced.update(_referenced_signal_types(source))

    return [(s, t) for s, t in catalog if t not in referenced]


def has_pending_generated(db: Connection, disaster_class: str) -> bool:
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM skill_lineage l
            JOIN skill_edit_proposals p ON p.lineage_id = l.id
            WHERE l.generation_method = 'generated'
              AND l.status IN ('candidate', 'shadow')
              AND p.status = 'pending'
              AND l.source_code LIKE %s
            LIMIT 1
            """,
            (f"%DISASTER_CLASS = \"{disaster_class}\"%",),
        )
        if cur.fetchone():
            return True
        cur.execute(
            """
            SELECT 1
            FROM skill_lineage l
            JOIN skill_edit_proposals p ON p.lineage_id = l.id
            WHERE l.generation_method = 'generated'
              AND l.status IN ('candidate', 'shadow')
              AND p.status = 'pending'
              AND l.source_code LIKE %s
            LIMIT 1
            """,
            (f"%DISASTER_CLASS = '{disaster_class}'%",),
        )
        return cur.fetchone() is not None


def should_run_generator(db: Connection) -> tuple[bool, str | None, list[tuple[str, str]]]:
    if not is_generator_seeded():
        return False, None, []
    dclass = seeded_disaster_class()
    if not dclass:
        return False, None, []
    if has_pending_generated(db, dclass):
        return False, None, []
    uncovered = find_uncovered_signals(db, dclass)
    if not uncovered:
        return False, None, []
    return True, dclass, uncovered
