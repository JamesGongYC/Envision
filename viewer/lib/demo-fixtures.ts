import type { DemoFixtureStep, DemoVariant } from '@/fixtures/agent-demo';
import type { AgentStepEvent } from '@/lib/types';

/** Normalize an authored fixture step into the AgentStepEvent shape RunPlayer expects. */
export function fixtureStepToEvent(
  step: DemoFixtureStep,
  variantId: string,
  nowIso: string
): AgentStepEvent {
  return {
    run_id: `demo:${variantId}`,
    seq: step.seq,
    step_type: step.step_type,
    tool: step.tool ?? null,
    input: step.input ?? null,
    output: step.output ?? null,
    geo_focus: step.geo_focus ?? null,
    ts: nowIso,
    skill_id: step.skill_id ?? null,
    input_layers: step.input_layers ?? null,
    candidates: step.candidates ?? null,
    dwell_ms: step.dwell_ms,
  };
}

export function variantToEvents(variant: DemoVariant): AgentStepEvent[] {
  const nowIso = new Date().toISOString();
  return variant.steps.map((s) => fixtureStepToEvent(s, variant.id, nowIso));
}
