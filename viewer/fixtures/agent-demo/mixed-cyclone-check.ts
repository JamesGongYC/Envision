import {
  ALL_SIGNAL_LAYERS,
  SICILY,
  TYPHOON_INTENSIFYING_LAYERS,
  TYPHOON_LANDFALL_LAYERS,
  WILDFIRE_RAPID_LAYERS,
} from './geoms';
import type { DemoVariant } from './types';

const SICILY_CANDIDATE = {
  id: '572edb20-a017-4bc3-90e8-0dad445179c7',
  location: SICILY,
  hazard: 'wildfire',
  probability: 0.75,
  skill: 'wildfire_rapid_growth',
  label: 'Hotspot growth 7 → 25 → 76 over 72h — Sicily',
};

export const mixedCycloneCheck: DemoVariant = {
  id: 'mixed-cyclone-check',
  title: 'Mixed: cyclone check',
  steps: [
    {
      seq: 1,
      step_type: 'thought',
      dwell_ms: 3200,
      output: {
        text: 'Two hazard classes to consider this pass. I\'ll look at the signal picture first and let the data decide where the attention goes, rather than running all four detectors by rote.',
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
          { source: 'firms_viirs', count: 32217 },
          { source: 'firms_modis', count: 11275 },
          { source: 'open_meteo', count: 635 },
          { source: 'aifs', count: 402 },
          { source: 'nhc', count: 20 },
        ],
      },
    },
    {
      seq: 4,
      step_type: 'thought',
      dwell_ms: 3800,
      output: {
        text: 'Fire signals are healthy. The cyclone side is thinner than I\'d like — only about twenty NHC advisories in the last day, and a few dozen over the week despite AIFS features present. I\'ll still run both typhoon detectors, because ruling a hazard out is worth the two steps; I just won\'t expect much.',
      },
    },
    {
      seq: 5,
      step_type: 'action',
      tool: 'run_skill',
      dwell_ms: 900,
      skill_id: 'typhoon_intensifying',
      input_layers: [...TYPHOON_INTENSIFYING_LAYERS],
      input: {
        skill_id: 'typhoon_intensifying',
        input_layers: [...TYPHOON_INTENSIFYING_LAYERS],
      },
    },
    {
      seq: 6,
      step_type: 'observation',
      tool: 'run_skill',
      dwell_ms: 1200,
      skill_id: 'typhoon_intensifying',
      input_layers: [...TYPHOON_INTENSIFYING_LAYERS],
      output: {
        skill_id: 'typhoon_intensifying',
        count: 0,
        candidates: [],
      },
    },
    {
      seq: 7,
      step_type: 'thought',
      dwell_ms: 3000,
      output: {
        text: 'Nothing intensifying. With the current advisory coverage that\'s a weak negative rather than a confident all-clear — absence of signal isn\'t absence of storm. I\'ll note it as unresolved rather than clear.',
      },
    },
    {
      seq: 8,
      step_type: 'action',
      tool: 'run_skill',
      dwell_ms: 900,
      skill_id: 'typhoon_landfall_imminent',
      input_layers: [...TYPHOON_LANDFALL_LAYERS],
      input: {
        skill_id: 'typhoon_landfall_imminent',
        input_layers: [...TYPHOON_LANDFALL_LAYERS],
      },
    },
    {
      seq: 9,
      step_type: 'observation',
      tool: 'run_skill',
      dwell_ms: 1200,
      skill_id: 'typhoon_landfall_imminent',
      input_layers: [...TYPHOON_LANDFALL_LAYERS],
      output: {
        skill_id: 'typhoon_landfall_imminent',
        count: 0,
        candidates: [],
      },
    },
    {
      seq: 10,
      step_type: 'thought',
      dwell_ms: 3400,
      output: {
        text: 'Also empty. No track cone is intersecting populated coastline in the current advisories. Both cyclone detectors agree there\'s nothing to act on, so I\'ll move to wildfire where the coverage is real.',
      },
    },
    {
      seq: 11,
      step_type: 'action',
      tool: 'run_skill',
      dwell_ms: 900,
      skill_id: 'wildfire_rapid_growth',
      input_layers: [...WILDFIRE_RAPID_LAYERS],
      geo_focus: SICILY,
      input: {
        skill_id: 'wildfire_rapid_growth',
        input_layers: [...WILDFIRE_RAPID_LAYERS],
      },
    },
    {
      seq: 12,
      step_type: 'observation',
      tool: 'run_skill',
      dwell_ms: 1200,
      skill_id: 'wildfire_rapid_growth',
      input_layers: [...WILDFIRE_RAPID_LAYERS],
      geo_focus: SICILY,
      output: {
        skill_id: 'wildfire_rapid_growth',
        count: 1,
        candidates: [
          {
            id: SICILY_CANDIDATE.id,
            skill_id: SICILY_CANDIDATE.skill,
            disaster_class: SICILY_CANDIDATE.hazard,
            probability: SICILY_CANDIDATE.probability,
            geometry: SICILY_CANDIDATE.location,
            reasoning: SICILY_CANDIDATE.label,
          },
        ],
      },
    },
    {
      seq: 13,
      step_type: 'thought',
      dwell_ms: 3200,
      output: {
        text: 'One growth candidate, concentrated around Sicily — hotspot counts climbed 7 → 25 → 76 over seventy-two hours. That\'s enough to forecast on.',
      },
    },
    {
      seq: 14,
      step_type: 'action',
      tool: 'emit',
      dwell_ms: 900,
      input: { selected: [{ id: SICILY_CANDIDATE.id }] },
    },
    {
      seq: 15,
      step_type: 'terminal',
      tool: 'emit',
      dwell_ms: 1400,
      candidates: [SICILY_CANDIDATE],
      output: {
        emitted_ids: [SICILY_CANDIDATE.id],
        candidates: [SICILY_CANDIDATE],
        count: 1,
      },
    },
    {
      seq: 16,
      step_type: 'thought',
      dwell_ms: 3600,
      output: {
        text: 'One forecast emitted, wildfire. The cyclone half of this pass produced nothing — which is the correct outcome, not a failed one. A pass that emits less because the evidence is thin is doing its job.',
      },
    },
  ],
};
