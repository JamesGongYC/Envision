import {
  ALL_SIGNAL_LAYERS,
  WILDFIRE_RAPID_LAYERS,
} from './geoms';
import type { DemoVariant } from './types';

const ELEVATED_LAYERS = [
  'firms_hotspots',
  'nws_fire_alerts',
  'open_meteo_fire_weather',
] as const;

/** Restraint: look, find nothing actionable, emit empty. */
export const quietRun: DemoVariant = {
  id: 'quiet-run',
  title: 'Quiet run',
  steps: [
    {
      seq: 1,
      step_type: 'thought',
      dwell_ms: 2600,
      output: {
        text: 'Routine pass. Checking what\'s come in since the last cycle.',
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
          { source: 'nws_alerts', count: 14 },
          { source: 'nhc', count: 20 },
        ],
      },
    },
    {
      seq: 4,
      step_type: 'thought',
      dwell_ms: 3600,
      output: {
        text: 'Plenty of hotspots in absolute terms, but nothing here is obviously urgent — the fire-weather fields aren\'t showing the dryness or wind that turns detections into events. I\'d rather confirm that with a detector than assume it from the signal counts alone.',
      },
    },
    {
      seq: 5,
      step_type: 'action',
      tool: 'run_skill',
      dwell_ms: 900,
      skill_id: 'wildfire_rapid_growth',
      input_layers: [...WILDFIRE_RAPID_LAYERS],
      input: {
        skill_id: 'wildfire_rapid_growth',
        input_layers: [...WILDFIRE_RAPID_LAYERS],
      },
    },
    {
      seq: 6,
      step_type: 'observation',
      tool: 'run_skill',
      dwell_ms: 1200,
      skill_id: 'wildfire_rapid_growth',
      input_layers: [...WILDFIRE_RAPID_LAYERS],
      output: {
        skill_id: 'wildfire_rapid_growth',
        count: 0,
        candidates: [],
      },
    },
    {
      seq: 7,
      step_type: 'thought',
      dwell_ms: 3400,
      output: {
        text: 'Nothing meeting the growth threshold. The hotspots that are active aren\'t expanding day over day — they read as isolated burns, not developing events.',
      },
    },
    {
      seq: 8,
      step_type: 'action',
      tool: 'run_skill',
      dwell_ms: 900,
      skill_id: 'wildfire_risk_elevated',
      input_layers: [...ELEVATED_LAYERS],
      input: {
        skill_id: 'wildfire_risk_elevated',
        input_layers: [...ELEVATED_LAYERS],
      },
    },
    {
      seq: 9,
      step_type: 'observation',
      tool: 'run_skill',
      dwell_ms: 1200,
      skill_id: 'wildfire_risk_elevated',
      input_layers: [...ELEVATED_LAYERS],
      output: {
        skill_id: 'wildfire_risk_elevated',
        count: 0,
        candidates: [],
      },
    },
    {
      seq: 10,
      step_type: 'thought',
      dwell_ms: 3000,
      output: {
        text: 'The second detector agrees — no clusters coinciding with active fire-weather warnings. Two independent reads both coming back empty is a much stronger negative than one.',
      },
    },
    {
      seq: 11,
      step_type: 'action',
      tool: 'emit',
      dwell_ms: 900,
      input: { selected: [] },
    },
    {
      seq: 12,
      step_type: 'terminal',
      tool: 'emit',
      dwell_ms: 1400,
      candidates: [],
      output: { emitted_ids: [], candidates: [], count: 0 },
    },
    {
      seq: 13,
      step_type: 'thought',
      dwell_ms: 3800,
      output: {
        text: 'Nothing emitted this pass. A quiet cycle is a real result. Emitting on weak evidence would cost more than it\'s worth — false alarms are how a warning system loses the attention it needs when something genuine develops.',
      },
    },
  ],
};
