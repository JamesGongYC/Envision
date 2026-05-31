"""Locked v2.5 Day 3 reasoning prompts — fill from trace dicts."""
from __future__ import annotations

from typing import Any


def _trace_inputs(trace: dict) -> dict:
    return trace.get("inputs") or {}


def _trace_intermediate(trace: dict) -> dict:
    return trace.get("intermediate") or {}


def prompt_wildfire_rapid_growth(
    trace: dict,
    lat: float,
    lon: float,
    day_t: int,
    day_t1: int,
    day_t2: int,
) -> str:
    inter = _trace_intermediate(trace)
    growing = (inter.get("growing_cells") or [{}])[0]
    ratio = float(growing.get("growth_ratio") or (day_t / max(1, day_t1)))
    days_consecutive = int(growing.get("days_consecutive") or 2)
    return f"""You are explaining an automated wildfire/typhoon forecast to a curious operator.

A detection skill identified rapid wildfire growth:
- Region: approximately {lat:.1f}°, {lon:.1f}°
- Hotspot count last 24h: {day_t}
- Hotspot count prior 24h: {day_t1}
- Growth ratio: {ratio:.1f}x, sustained {days_consecutive} consecutive days

Write 2-3 sentences explaining the growth pattern and what it suggests. Lead with
the location and growth magnitude. Avoid jargon. Stay under 400 characters."""


def prompt_typhoon_intensifying(
    trace: dict,
    storm_name: str,
    source: str,
    lat: float,
    lon: float,
    drop_hpa: float,
    period_h: float,
    current_pressure_hpa: float,
) -> str:
    return f"""You are explaining an automated wildfire/typhoon forecast to a curious operator.

A detection skill identified a rapidly intensifying tropical cyclone:
- Storm: {storm_name} (source: {source})
- Current position: {lat:.1f}°, {lon:.1f}°
- Central pressure dropped by {drop_hpa:.0f} hPa over {period_h:.0f} hours
- Current pressure: {current_pressure_hpa:.0f} hPa

Write 2-3 sentences explaining what was detected and why it matters. Lead with
the storm name and the intensification rate. Avoid jargon. Stay under 400 characters."""


def prompt_typhoon_landfall(
    trace: dict,
    storm_name: str,
    source: str,
    population_at_risk: int,
    top_place_names: list[str],
    time_to_landfall_h: float,
) -> str:
    top_3 = ", ".join(top_place_names[:3]) if top_place_names else "unknown"
    return f"""You are explaining an automated wildfire/typhoon forecast to a curious operator.

A detection skill identified a tropical cyclone approaching populated coastline:
- Storm: {storm_name} (source: {source})
- Forecast cone intersects regions totaling {population_at_risk:,} people
- Top populated places in path: {top_3}
- Time to nearest landfall: {time_to_landfall_h:.0f} hours

Write 2-3 sentences explaining the threat. Lead with the storm name and population
scope. Avoid jargon. Stay under 400 characters."""


def prompt_wildfire_risk_elevated(
    trace: dict,
    lat: float,
    lon: float,
    cluster_size: int,
    cluster_radius_km: float,
    polygon_source: str,
    polygon_summary: str,
) -> str:
    return f"""You are explaining an automated wildfire/typhoon forecast to a curious operator.

A detection skill identified elevated wildfire risk where active fires meet
fire-weather conditions:
- Region: approximately {lat:.1f}°, {lon:.1f}°
- Active fire cluster: {cluster_size} hotspots within {cluster_radius_km:.0f} km
- Fire weather context: {polygon_source} ({polygon_summary})

Write 2-3 sentences explaining the convergence of active fire + warned weather.
Lead with the location and the combination. Avoid jargon. Stay under 400 characters."""
