import {
  ALL_SIGNAL_LAYERS,
  ANGOLA,
  MOZ_FOCUS,
  MOZ_PRIMARY,
  MOZ_SIBLING,
  WILDFIRE_RAPID_LAYERS,
} from './geoms';
import type { DemoVariant } from './types';

const CANDIDATES = [
  {
    id: '6df570c8-b61d-4a24-86ac-cf612b2975aa',
    location: MOZ_PRIMARY,
    hazard: 'wildfire',
    probability: 0.677,
    skill: 'wildfire_rapid_growth',
    label: 'Hotspot growth 12 → 32 → 101 over 72h — central Mozambique',
  },
  {
    id: '7e90c36a-7429-4daa-9bba-ffdc34ae2db4',
    location: MOZ_SIBLING,
    hazard: 'wildfire',
    probability: 0.68,
    skill: 'wildfire_rapid_growth',
    label: 'Hotspot growth 4 → 10 → 34 over 72h — neighboring Mozambique cell',
  },
  {
    id: '72fd09f4-91b2-47ae-b2ea-df14ae5f11ff',
    location: ANGOLA,
    hazard: 'wildfire',
    probability: 0.75,
    skill: 'wildfire_rapid_growth',
    label: 'Hotspot growth 3 → 12 → 43 over 72h — Angola plateau',
  },
];

/** Flagship: southern Africa rapid-growth cluster (no dual-skill corroboration). */
export const wildfireHeavy: DemoVariant = {
  id: 'wildfire-heavy',
  title: 'Wildfire-heavy',
  steps: [
    {
      seq: 1,
      step_type: 'thought',
      dwell_ms: 3800,
      output: {
        text: 'Starting a detection pass. Before running anything I want to see what\'s actually arrived — there\'s no point running a detector against a stale feed, so I\'ll check freshness and volume across every source first.',
      },
    },
    {
      seq: 2,
      step_type: 'action',
      tool: 'inspect_signals',
      dwell_ms: 900,
      input_layers: [...ALL_SIGNAL_LAYERS],
      input: {},
    },
    {
      seq: 3,
      step_type: 'observation',
      tool: 'inspect_signals',
      dwell_ms: 1200,
      output: {
        sources: [
          { source: 'firms_viirs', count: 32217, latest: '2026-07-19T21:10:00Z' },
          { source: 'firms_modis', count: 11275, latest: '2026-07-19T21:59:00Z' },
          { source: 'open_meteo', count: 635, latest: '2026-07-22T00:00:00Z' },
          { source: 'aifs', count: 402, latest: '2026-07-22T00:00:00Z' },
          { source: 'ecmwf_open_data', count: 185, latest: '2026-07-20T00:00:00Z' },
          { source: 'nhc', count: 20, latest: '2026-07-20T00:00:00Z' },
          { source: 'nws_alerts', count: 14, latest: '2026-07-20T20:00:00Z' },
        ],
      },
    },
    {
      seq: 4,
      step_type: 'thought',
      dwell_ms: 4000,
      output: {
        text: 'Good coverage on the fire side — 32k VIIRS and 11k MODIS hotspots in the last cycle, and the fire-weather fields are current. Central Mozambique is dense enough that something is likely burning at scale. The cyclone feeds are quiet (about 20 NHC advisories), which is expected right now. I\'ll focus the pass on wildfire.',
      },
    },
    {
      seq: 5,
      step_type: 'action',
      tool: 'list_skills',
      dwell_ms: 900,
      input: {},
    },
    {
      seq: 6,
      step_type: 'observation',
      tool: 'list_skills',
      dwell_ms: 1200,
      output: {
        skills: [
          {
            skill_id: 'wildfire_rapid_growth',
            n_evaluations: 3041,
            mean_brier: 0.5577,
            hit_rate: 0.0,
          },
          {
            skill_id: 'wildfire_risk_elevated',
            n_evaluations: 10951,
            mean_brier: 0.5762,
            hit_rate: 0.003,
          },
          {
            skill_id: 'typhoon_landfall_imminent',
            n_evaluations: 8,
            mean_brier: 0.536,
            hit_rate: 0.0,
          },
        ],
      },
    },
    {
      seq: 7,
      step_type: 'thought',
      dwell_ms: 3600,
      output: {
        text: 'Three detectors with recent scores. wildfire_rapid_growth is looking for day-over-day expansion rather than a single hot day, which is the harder thing to fake. I\'ll run it first and treat it as my primary read.',
      },
    },
    {
      seq: 8,
      step_type: 'action',
      tool: 'run_skill',
      dwell_ms: 900,
      skill_id: 'wildfire_rapid_growth',
      input_layers: [...WILDFIRE_RAPID_LAYERS],
      geo_focus: MOZ_FOCUS,
      input: { skill_id: 'wildfire_rapid_growth', input_layers: [...WILDFIRE_RAPID_LAYERS] },
    },
    {
      seq: 9,
      step_type: 'observation',
      tool: 'run_skill',
      dwell_ms: 1200,
      skill_id: 'wildfire_rapid_growth',
      input_layers: [...WILDFIRE_RAPID_LAYERS],
      geo_focus: MOZ_FOCUS,
      output: {
        skill_id: 'wildfire_rapid_growth',
        input_layers: [...WILDFIRE_RAPID_LAYERS],
        count: 3,
        candidates: CANDIDATES.map((c) => ({
          id: c.id,
          skill_id: c.skill,
          disaster_class: c.hazard,
          probability: c.probability,
          geometry: c.location,
          reasoning: c.label,
        })),
      },
    },
    {
      seq: 10,
      step_type: 'thought',
      dwell_ms: 4000,
      output: {
        text: 'Three areas showing sustained growth. The cluster over central Mozambique stands out — hotspot counts climbed 12 → 32 → 101 over seventy-two hours, with a neighboring cell expanding on the same arc. That\'s the profile that usually precedes a significant event rather than a burn that self-extinguishes. I\'ll carry these forward and let the aggregator price the set.',
      },
    },
    {
      seq: 11,
      step_type: 'action',
      tool: 'emit',
      dwell_ms: 900,
      input: {
        selected: CANDIDATES.map((c) => ({ id: c.id })),
      },
    },
    {
      seq: 12,
      step_type: 'terminal',
      tool: 'emit',
      dwell_ms: 1400,
      candidates: CANDIDATES,
      output: {
        emitted_ids: CANDIDATES.map((c) => c.id),
        candidates: CANDIDATES,
        count: 3,
      },
    },
    {
      seq: 13,
      step_type: 'thought',
      dwell_ms: 3800,
      output: {
        text: 'Emitted three forecasts from the rapid-growth detector. Where cells sit near each other, the aggregator can combine confidence up to the 0.85 ceiling — that cap is fixed, so corroboration can raise certainty but never push it past what the evidence supports. I don\'t set these numbers; the aggregator does.',
      },
    },
  ],
};
