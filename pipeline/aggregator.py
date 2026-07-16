"""Deterministic forecast probability aggregator (outside mutation surface).

Pure function: no DB, clock, or RNG. Prices candidate sets for both the
routine rule path and the agent path so the 0.85 cap and p=hit-rate guard
live in exactly one place.
"""
from __future__ import annotations

import json
import math
import os
import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

try:
    from forecast_model import Forecast
except ImportError:
    from agent.lib.forecast_model import Forecast  # type: ignore

# EmittedForecast is a priced Forecast copy.
EmittedForecast = Forecast

_EARTH_RADIUS_KM = 6371.0


@dataclass(frozen=True)
class AggregatorConfig:
    corroboration_radius_km: float
    p_cap: float


def default_config() -> AggregatorConfig:
    return AggregatorConfig(
        corroboration_radius_km=float(
            os.environ.get("AGGREGATOR_CORROBORATION_RADIUS_KM", "50")
        ),
        p_cap=float(os.environ.get("AGGREGATOR_P_CAP", "0.85")),
    )


def _clamp_p(p: float, cap: float) -> float:
    if p < 0.0:
        return 0.0
    if p > cap:
        return cap
    return p


def _centroid(geometry: str | dict) -> tuple[float, float] | None:
    """Return (lon, lat) centroid from GeoJSON point or polygon envelope."""
    try:
        obj = json.loads(geometry) if isinstance(geometry, str) else geometry
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(obj, dict):
        return None
    coords = obj.get("coordinates")
    gtype = obj.get("type")
    if gtype == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
        return float(coords[0]), float(coords[1])

    lons: list[float] = []
    lats: list[float] = []

    def walk(c: Any) -> None:
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
            lons.append(float(c[0]))
            lats.append(float(c[1]))
            return
        if isinstance(c, (list, tuple)):
            for x in c:
                walk(x)

    walk(coords)
    if not lons or not lats:
        return None
    return (sum(lons) / len(lons), sum(lats) / len(lats))


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = a
    lon2, lat2 = b
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def _noisy_or(probs: list[float]) -> float:
    prod = 1.0
    for p in probs:
        prod *= 1.0 - max(0.0, min(1.0, p))
    return 1.0 - prod


def _hit_rate(skill_id: str, rates: dict[str, float]) -> float:
    return float(rates.get(skill_id, 0.0))


def _rank_key(f: Forecast, rates: dict[str, float]) -> tuple[float, float, str]:
    """Higher is better: hit_rate, then p, then skill_id (lexicographic for stability)."""
    # Negate skill_id sort by using skill_id ascending as last tie-break via
    # sorting reverse=True on a tuple where skill_id is inverted carefully:
    # we sort with reverse=True so skill_id should be ordered descending for
    # stable "first wins" — use skill_id ascending by sorting reverse on
    # (-hit, -p, skill_id) with reverse=False instead.
    return (_hit_rate(f.skill_id, rates), f.probability, f.skill_id)


def _pick_winner(members: list[Forecast], rates: dict[str, float]) -> Forecast:
    return max(members, key=lambda f: _rank_key(f, rates))


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        ri, rj = self.find(i), self.find(j)
        if ri != rj:
            # Deterministic: attach higher index under lower.
            if ri < rj:
                self.parent[rj] = ri
            else:
                self.parent[ri] = rj


def _copy_forecast(f: Forecast, *, probability: float | None = None) -> Forecast:
    out = deepcopy(f)
    if probability is not None:
        out.probability = probability
    return out


def _merge_corroboration(
    members: list[Forecast],
    rates: dict[str, float],
    cfg: AggregatorConfig,
) -> Forecast:
    probs = [float(m.probability) for m in members]
    combined = _noisy_or(probs)
    # Guard: never lower below any individual skill p.
    combined = max(combined, max(probs))
    combined = _clamp_p(combined, cfg.p_cap)

    winner = _pick_winner(members, rates)
    merged = _copy_forecast(winner, probability=combined)
    merged.id = str(uuid.uuid5(uuid.NAMESPACE_URL, "envision-agg:" + "|".join(
        sorted(str(m.id) for m in members)
    )))
    sig_ids: list[str] = []
    seen: set[str] = set()
    for m in sorted(members, key=lambda x: str(x.id)):
        for sid in m.contributing_signal_ids or []:
            s = str(sid)
            if s not in seen:
                seen.add(s)
                sig_ids.append(s)
    merged.contributing_signal_ids = sig_ids
    return merged


def aggregate(
    candidates: list[Forecast],
    skill_hit_rates: dict[str, float],
    cfg: AggregatorConfig,
) -> list[EmittedForecast]:
    """Price a candidate set. Pure and deterministic."""
    if not candidates:
        return []

    n = len(candidates)
    centroids: list[tuple[float, float] | None] = [
        _centroid(c.geometry) for c in candidates
    ]
    uf = _UnionFind(n)

    for i in range(n):
        if centroids[i] is None:
            continue
        for j in range(i + 1, n):
            if centroids[j] is None:
                continue
            if _haversine_km(centroids[i], centroids[j]) <= cfg.corroboration_radius_km:
                uf.union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        root = uf.find(i)
        clusters.setdefault(root, []).append(i)

    # Process clusters in stable order (by min member index).
    emitted: list[Forecast] = []
    for root in sorted(clusters.keys(), key=lambda r: min(clusters[r])):
        idxs = sorted(clusters[root])
        members = [candidates[i] for i in idxs]

        if len(members) == 1:
            m = members[0]
            emitted.append(
                _copy_forecast(m, probability=_clamp_p(float(m.probability), cfg.p_cap))
            )
            continue

        classes = {m.disaster_class for m in members}
        skill_ids = {m.skill_id for m in members}

        if len(classes) > 1:
            # Conflict: different hazard classes at the same point — hit-rate wins.
            winner = _pick_winner(members, skill_hit_rates)
            emitted.append(
                _copy_forecast(
                    winner,
                    probability=_clamp_p(float(winner.probability), cfg.p_cap),
                )
            )
            continue

        # Same disaster_class.
        if len(skill_ids) >= 2:
            # Corroboration across distinct skills.
            emitted.append(_merge_corroboration(members, skill_hit_rates, cfg))
            continue

        # Same skill only (cron single-skill multi-point cluster): emit each
        # individually — same skill never corroborates with itself.
        for m in members:
            emitted.append(
                _copy_forecast(m, probability=_clamp_p(float(m.probability), cfg.p_cap))
            )

    return emitted
