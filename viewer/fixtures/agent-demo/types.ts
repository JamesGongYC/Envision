import type { AgentEmitCandidate } from '@/lib/types';

export type DemoStepType =
  | 'thought'
  | 'action'
  | 'observation'
  | 'terminal'
  | 'gated'
  | 'failed';

/** Authored fixture step before normalization to AgentStepEvent. */
export type DemoFixtureStep = {
  seq: number;
  step_type: DemoStepType;
  tool?: string | null;
  dwell_ms: number;
  skill_id?: string | null;
  input_layers?: string[] | null;
  geo_focus?: GeoJSON.Geometry | null;
  input?: unknown;
  output?: unknown;
  candidates?: AgentEmitCandidate[] | null;
};

export type DemoVariant = {
  id: string;
  title: string;
  steps: DemoFixtureStep[];
};
