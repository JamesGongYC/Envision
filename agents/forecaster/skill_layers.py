"""Static skill_id → viewer LayerId map for T12 layer-pulse events."""
from __future__ import annotations

# IDs match viewer LayerId / styleKeyForLayer (not model-authored).
SKILL_INPUT_LAYERS: dict[str, list[str]] = {
    "wildfire_rapid_growth": [
        "firms_hotspots",
        "open_meteo_fire_weather",
        "nws_fire_alerts",
    ],
    "wildfire_risk_elevated": [
        "firms_hotspots",
        "nws_fire_alerts",
        "open_meteo_fire_weather",
    ],
    "typhoon_intensifying": [
        "jtwc_advisories",
        "aifs_cyclone_features",
    ],
    "typhoon_landfall_imminent": [
        "jtwc_advisories",
        "nhc_advisories",
        "aifs_cyclone_features",
    ],
}


def input_layers_for(skill_id: str) -> list[str]:
    """Return static input layer ids for a detection skill (empty if unknown)."""
    return list(SKILL_INPUT_LAYERS.get(skill_id, []))
