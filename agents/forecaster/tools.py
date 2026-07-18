"""Forecaster agent tools — infrastructure only; not mutation surface."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Connection

try:
    from forecast_model import Forecast
    from forecast_writer import emit_forecasts
except ImportError:
    from agent.lib.forecast_model import Forecast  # type: ignore
    from agent.lib.forecast_writer import emit_forecasts  # type: ignore

from agent.evolution.skill_loader import MODAL_SKILLS, SKILL_FOLDERS, load_skill_run

from agents.common.aggregator_interface import emit_selected
from agents.forecaster.skill_layers import input_layers_for

BBox = list[float]  # [west, south, east, north] or GeoJSON Polygon dict handled separately


def _parse_geometry(geom: Any) -> dict | None:
    """Normalize forecast geometry to a GeoJSON dict (or None)."""
    if geom is None:
        return None
    if isinstance(geom, dict) and geom.get("type"):
        return geom
    if isinstance(geom, str):
        try:
            obj = json.loads(geom)
            if isinstance(obj, dict) and obj.get("type"):
                return obj
        except (TypeError, json.JSONDecodeError):
            return None
    return None


def enrich_run_skill_action_input(tool_input: dict) -> dict:
    """Attach skill_id + static input_layers for SSE / persistence."""
    skill_id = str(tool_input.get("skill_id") or "")
    out = dict(tool_input)
    out["skill_id"] = skill_id
    out["input_layers"] = input_layers_for(skill_id)
    return out


def candidate_popup_dict(f: Forecast) -> dict[str, Any]:
    """Per-candidate payload for emit terminal / T12 popups."""
    label = (f.reasoning or "").strip().split("\n")[0][:80] or f.skill_id
    return {
        "id": str(f.id),
        "location": _parse_geometry(f.geometry),
        "hazard": f.disaster_class,
        "probability": float(f.probability) if f.probability is not None else None,
        "skill": f.skill_id,
        "label": label,
    }


def _bbox_to_geojson(bbox: BBox | dict | None) -> str | None:
    if bbox is None:
        return None
    if isinstance(bbox, dict):
        return json.dumps(bbox)
    if len(bbox) != 4:
        raise ValueError("bbox must be [west, south, east, north]")
    w, s, e, n = bbox
    return json.dumps(
        {
            "type": "Polygon",
            "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
        }
    )


def _envelope_geojson(forecasts: list[Forecast]) -> str | None:
    if not forecasts:
        return None
    geoms = []
    for f in forecasts:
        g = f.geometry if isinstance(f.geometry, str) else json.dumps(f.geometry)
        geoms.append(g)
    # Compute envelope in Python via simple lon/lat bounds from GeoJSON coords.
    lons: list[float] = []
    lats: list[float] = []

    def walk(coords: Any) -> None:
        if isinstance(coords, (list, tuple)) and coords and isinstance(coords[0], (int, float)):
            lons.append(float(coords[0]))
            lats.append(float(coords[1]))
            return
        if isinstance(coords, (list, tuple)):
            for c in coords:
                walk(c)

    for g in geoms:
        try:
            obj = json.loads(g) if isinstance(g, str) else g
            walk(obj.get("coordinates"))
        except (TypeError, json.JSONDecodeError, AttributeError):
            continue
    if not lons or not lats:
        return None
    return _bbox_to_geojson([min(lons), min(lats), max(lons), max(lats)])


def _skill_md_summary(skill_id: str) -> str:
    folder = SKILL_FOLDERS.get(skill_id)
    if not folder:
        return ""
    path = MODAL_SKILLS / folder / "SKILL.md"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    # Prefer first non-empty prose paragraph after frontmatter.
    body = text
    if body.startswith("---"):
        parts = body.split("---", 2)
        body = parts[2] if len(parts) >= 3 else body
    for para in body.split("\n\n"):
        line = para.strip()
        if line and not line.startswith("#") and not line.startswith("```"):
            return line[:400]
        if line.startswith("## ") or line.startswith("# "):
            continue
    # Fallback: description from frontmatter
    for line in text.splitlines():
        if line.lower().startswith("description:"):
            return line.split(":", 1)[1].strip()[:400]
    return text[:200].strip()


def inspect_signals(
    db: Connection,
    bbox: BBox | dict | None = None,
) -> tuple[dict, str | None]:
    """Return signal_catalog + freshness; optional bbox scopes counts."""
    geo_focus = _bbox_to_geojson(bbox)
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT source, signal_type, row_count, first_seen, last_seen
            FROM signal_catalog
            ORDER BY source, signal_type
            """
        )
        catalog = [
            {
                "source": r[0],
                "signal_type": r[1],
                "row_count": int(r[2] or 0),
                "first_seen": r[3].isoformat() if r[3] else None,
                "last_seen": r[4].isoformat() if r[4] else None,
            }
            for r in cur.fetchall()
        ]
        cur.execute(
            """
            SELECT source, MAX(timestamp) AS max_ts
            FROM signals
            GROUP BY source
            ORDER BY source
            """
        )
        freshness = {
            r[0]: (r[1].isoformat() if r[1] else None) for r in cur.fetchall()
        }

        scoped = None
        if geo_focus is not None:
            cur.execute(
                """
                SELECT source, signal_type, COUNT(*)::int AS n
                FROM signals
                WHERE ST_Intersects(
                    geometry,
                    ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
                )
                GROUP BY source, signal_type
                ORDER BY source, signal_type
                """,
                (geo_focus,),
            )
            scoped = [
                {"source": r[0], "signal_type": r[1], "count": int(r[2])}
                for r in cur.fetchall()
            ]

    return (
        {
            "catalog": catalog,
            "freshness": freshness,
            "scoped_counts": scoped,
        },
        geo_focus,
    )


def list_skills(db: Connection) -> list[dict]:
    """Detection skills with SKILL.md summary + recent Brier/hit_rate/override_frequency."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT
              f.skill_id,
              COUNT(*)::int AS n_evaluations,
              AVG(e.brier_contribution)::float AS mean_brier,
              SUM(CASE WHEN e.outcome = 'hit' THEN 1 ELSE 0 END)::int AS hits,
              SUM(CASE WHEN e.outcome IN ('hit', 'false_positive', 'miss') THEN 1 ELSE 0 END)::int AS n_scored
            FROM evaluations e
            JOIN forecasts f ON f.id = e.forecast_id
            WHERE e.evaluated_at > now() - interval '14 days'
            GROUP BY f.skill_id
            """
        )
        eval_by_skill = {
            r[0]: {
                "n_evaluations": int(r[1]),
                "mean_brier": float(r[2]) if r[2] is not None else None,
                "hits": int(r[3]),
                "hit_rate": (float(r[3]) / float(r[4])) if r[4] else None,
            }
            for r in cur.fetchall()
        }

        # override_frequency: among agent runs, fraction of skill's raw deposits
        # not mirrored by a producer='agent' row for the same run.
        cur.execute(
            """
            WITH raw AS (
              SELECT agent_run_id, skill_id, id
              FROM forecasts
              WHERE producer = 'rule'
                AND agent_run_id IS NOT NULL
            ),
            agent_emit AS (
              SELECT agent_run_id, skill_id, COUNT(*)::int AS n
              FROM forecasts
              WHERE producer = 'agent'
                AND agent_run_id IS NOT NULL
              GROUP BY agent_run_id, skill_id
            ),
            per_run AS (
              SELECT
                r.skill_id,
                r.agent_run_id,
                COUNT(*)::int AS n_raw,
                COALESCE(a.n, 0)::int AS n_agent
              FROM raw r
              LEFT JOIN agent_emit a
                ON a.agent_run_id = r.agent_run_id AND a.skill_id = r.skill_id
              GROUP BY r.skill_id, r.agent_run_id, a.n
            )
            SELECT
              skill_id,
              CASE WHEN SUM(n_raw) = 0 THEN 0.0
                   ELSE SUM(GREATEST(n_raw - n_agent, 0))::float / SUM(n_raw)::float
              END AS override_frequency
            FROM per_run
            GROUP BY skill_id
            """
        )
        override_by_skill = {r[0]: float(r[1] or 0.0) for r in cur.fetchall()}

    out: list[dict] = []
    for skill_id in sorted(SKILL_FOLDERS):
        stats = eval_by_skill.get(skill_id, {})
        out.append(
            {
                "skill_id": skill_id,
                "summary": _skill_md_summary(skill_id),
                "mean_brier": stats.get("mean_brier"),
                "hit_rate": stats.get("hit_rate"),
                "n_evaluations": stats.get("n_evaluations", 0),
                "override_frequency": override_by_skill.get(skill_id, 0.0),
            }
        )
    return out


def run_skill(
    db: Connection,
    *,
    skill_id: str,
    now: datetime,
    agent_run_id: UUID | str,
    candidate_cache: dict[str, Forecast],
) -> tuple[list[dict], str | None, list[Forecast]]:
    """Execute promoted skill; deposit raw candidates to scoring stream (D2)."""
    run_fn = load_skill_run(skill_id)
    candidates: list[Forecast] = list(run_fn(now, db) or [])
    # Always deposit raw output for fitness — selection-independent.
    if candidates:
        emit_forecasts(
            candidates,
            db,
            producer="rule",
            agent_run_id=str(agent_run_id),
        )
        for f in candidates:
            candidate_cache[str(f.id)] = f
    geo = _envelope_geojson(candidates)
    serialized = [_forecast_public_dict(f) for f in candidates]
    return serialized, geo, candidates


def emit(
    db: Connection,
    *,
    selected: list[dict] | list[Forecast],
    agent_run_id: UUID | str,
    candidate_cache: dict[str, Forecast],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Terminal: restore skill p from cache, hand set to aggregator stub.

    Returns (emitted_ids, candidates_for_popup).
    """
    restored: list[Forecast] = []
    for item in selected:
        if isinstance(item, Forecast):
            fid = str(item.id)
            cached = candidate_cache.get(fid)
            if cached is not None:
                restored.append(deepcopy(cached))
            else:
                # No cache hit — keep skill object but do not trust elevated p from model path
                restored.append(item)
            continue
        if not isinstance(item, dict):
            continue
        fid = str(item.get("id") or "")
        cached = candidate_cache.get(fid)
        if cached is not None:
            restored.append(deepcopy(cached))
            continue
        # Unknown id with model-supplied fields: refuse invented p by requiring cache.
        # Skip orphans rather than invent scores.
        continue

    ids = emit_selected(restored, db=db, agent_run_id=agent_run_id)
    by_id = {str(f.id): f for f in restored}
    candidates = [
        candidate_popup_dict(by_id[str(i)])
        for i in ids
        if str(i) in by_id
    ]
    return [str(i) for i in ids], candidates


def _forecast_public_dict(f: Forecast) -> dict:
    """Serialize a forecast for agent context — includes skill p as observation only."""
    return {
        "id": str(f.id),
        "skill_id": f.skill_id,
        "skill_version": f.skill_version,
        "disaster_class": f.disaster_class,
        "probability": f.probability,  # skill-authored; emit ignores model overrides
        "valid_from": f.valid_from.isoformat() if f.valid_from else None,
        "valid_until": f.valid_until.isoformat() if f.valid_until else None,
        "geometry": _parse_geometry(f.geometry),
        "reasoning": (f.reasoning or "")[:500],
    }


# Anthropic tool schemas for the ReAct loop
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "inspect_signals",
        "description": (
            "Inspect signal_catalog and per-source freshness. "
            "Optional bbox [west,south,east,north] scopes counts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bbox": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 4,
                    "maxItems": 4,
                    "description": "Optional [west, south, east, north]",
                }
            },
        },
    },
    {
        "name": "list_skills",
        "description": "List detection skills with summaries, Brier, hit_rate, override_frequency.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_skill",
        "description": (
            "Run a promoted detection skill by skill_id. Returns candidate forecasts. "
            "Raw output is always deposited to the scoring stream."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string"},
            },
            "required": ["skill_id"],
        },
    },
    {
        "name": "emit",
        "description": (
            "TERMINAL. Emit the selected candidate set (by forecast id). "
            "Do not author probabilities — supply ids (and optional copies) only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "selected": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "probability": {"type": "number"},
                        },
                        "required": ["id"],
                    },
                }
            },
            "required": ["selected"],
        },
    },
]


def dispatch_tool(
    name: str,
    tool_input: dict,
    *,
    db: Connection,
    now: datetime,
    agent_run_id: UUID | str,
    candidate_cache: dict[str, Forecast],
) -> tuple[Any, str | None, bool]:
    """
    Dispatch a tool by name.
    Returns (observation, geo_focus_geojson|None, is_terminal).
    """
    if name == "inspect_signals":
        result, geo = inspect_signals(db, tool_input.get("bbox"))
        return result, geo, False
    if name == "list_skills":
        return list_skills(db), None, False
    if name == "run_skill":
        skill_id = str(tool_input.get("skill_id") or "")
        serialized, geo, _ = run_skill(
            db,
            skill_id=skill_id,
            now=now,
            agent_run_id=agent_run_id,
            candidate_cache=candidate_cache,
        )
        layers = input_layers_for(skill_id)
        return (
            {
                "skill_id": skill_id,
                "input_layers": layers,
                "candidates": serialized,
                "count": len(serialized),
            },
            geo,
            False,
        )
    if name == "emit":
        selected = tool_input.get("selected") or []
        ids, candidates = emit(
            db,
            selected=selected,
            agent_run_id=agent_run_id,
            candidate_cache=candidate_cache,
        )
        return (
            {
                "emitted_ids": ids,
                "candidates": candidates,
                "count": len(ids),
            },
            None,
            True,
        )
    raise ValueError(f"unknown tool {name!r}")
