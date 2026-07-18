import type { LayerId } from '@/lib/layer-state';
import { ALL_LAYER_IDS } from '@/lib/layer-state';
import type { AgentEmitCandidate, AgentStepEvent } from '@/lib/types';

const LAYER_ID_SET = new Set<string>(ALL_LAYER_IDS);

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function layersFromBag(bag: Record<string, unknown> | null): string[] | null {
  if (!bag || !Array.isArray(bag.input_layers)) return null;
  return bag.input_layers.map(String).filter(Boolean);
}

function candidatesFromBag(
  bag: Record<string, unknown> | null
): AgentEmitCandidate[] | null {
  if (!bag || !Array.isArray(bag.candidates)) return null;
  return bag.candidates
    .map(normalizeCandidate)
    .filter((c): c is AgentEmitCandidate => c != null);
}

function normalizeCandidate(raw: unknown): AgentEmitCandidate | null {
  const bag = asRecord(raw);
  if (!bag || bag.id == null) return null;
  const location =
    bag.location && typeof bag.location === 'object'
      ? (bag.location as GeoJSON.Geometry)
      : null;
  return {
    id: String(bag.id),
    location,
    hazard: String(bag.hazard ?? ''),
    probability:
      typeof bag.probability === 'number'
        ? bag.probability
        : bag.probability == null
          ? null
          : Number(bag.probability),
    skill: String(bag.skill ?? bag.skill_id ?? ''),
    label: String(bag.label ?? bag.skill ?? ''),
  };
}

/** Resolve input_layers from promoted top-level or nested input/output. */
export function resolveInputLayers(step: AgentStepEvent): string[] {
  if (Array.isArray(step.input_layers) && step.input_layers.length > 0) {
    return step.input_layers.map(String);
  }
  return (
    layersFromBag(asRecord(step.input)) ??
    layersFromBag(asRecord(step.output)) ??
    []
  );
}

/** Resolve emit candidates from promoted top-level or nested output/input. */
export function resolveCandidates(step: AgentStepEvent): AgentEmitCandidate[] {
  if (Array.isArray(step.candidates) && step.candidates.length > 0) {
    return step.candidates
      .map(normalizeCandidate)
      .filter((c): c is AgentEmitCandidate => c != null);
  }
  return (
    candidatesFromBag(asRecord(step.output)) ??
    candidatesFromBag(asRecord(step.input)) ??
    []
  );
}

/** Keep only known viewer LayerIds. */
export function toLayerIds(ids: string[]): LayerId[] {
  return ids.filter((id): id is LayerId => LAYER_ID_SET.has(id));
}
