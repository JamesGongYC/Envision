import type { DisasterClass } from './types';

export interface SkillMetadata {
  label: string;
  description: string;
  cadence: string;
  // null = not a detection skill (evaluator, ingester, etc.)
  disaster_class: DisasterClass | null;
}

export const SKILL_METADATA: Record<string, SkillMetadata> = {
  wildfire_risk_elevated: {
    label: 'Wildfire risk elevated',
    description:
      'DBSCAN cluster (eps=10km, min_samples=5) on FIRMS hotspots, ' +
      'intersected with active NWS fire-weather alerts.',
    cadence: '30 min',
    disaster_class: 'wildfire',
  },
  wildfire_rapid_growth: {
    label: 'Wildfire rapid growth',
    description:
      '50 km grid cell with hotspot count growing >50% day-over-day ' +
      'for 2 consecutive days.',
    cadence: '30 min',
    disaster_class: 'wildfire',
  },
  typhoon_intensifying: {
    label: 'Typhoon intensifying',
    description:
      'NHC central pressure dropping >5 hPa over a ~12 h window.',
    cadence: '3 h',
    disaster_class: 'typhoon',
  },
  typhoon_landfall_imminent: {
    label: 'Typhoon landfall imminent',
    description:
      '72 h projected cone (from current heading + speed) intersecting ' +
      'a populated place with pop ≥ 10⁴.',
    cadence: '3 h',
    disaster_class: 'typhoon',
  },
  forecast_evaluator: {
    label: 'Forecast evaluator',
    description:
      'Matches expired forecasts against GDACS ground truth. Writes ' +
      'Brier contributions to the evaluations table.',
    cadence: '24 h',
    disaster_class: null,
  },
};
