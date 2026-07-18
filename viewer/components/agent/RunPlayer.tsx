'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  resolveCandidates,
  resolveInputLayers,
  toLayerIds,
} from '@/lib/agent-step';
import type { LayerId } from '@/lib/layer-state';
import type { AgentEmitCandidate, AgentStepEvent } from '@/lib/types';

const DWELL_MS: Record<AgentStepEvent['step_type'], number> = {
  thought: 1600,
  action: 900,
  observation: 900,
  gated: 1200,
  failed: 1200,
  terminal: 1400,
};

function dwellMs(stepType: AgentStepEvent['step_type']): number {
  return DWELL_MS[stepType] ?? 900;
}

export type RunPlayerState = {
  visibleSteps: AgentStepEvent[];
  geoFocus: GeoJSON.Geometry | null;
  pulsingLayers: LayerId[];
  candidates: AgentEmitCandidate[];
  playing: boolean;
  playhead: number;
};

/**
 * Eased timeline over a buffered agent_step stream.
 * Live and replay share this clock; SSE only fills the buffer.
 */
export function useRunPlayer(
  buffer: AgentStepEvent[],
  options: { resetKey: string | number }
): RunPlayerState {
  const [playhead, setPlayhead] = useState(-1);

  useEffect(() => {
    setPlayhead(-1);
  }, [options.resetKey]);

  useEffect(() => {
    if (buffer.length === 0) return;
    const next = playhead + 1;
    if (next >= buffer.length) return;

    const delay = playhead < 0 ? 0 : dwellMs(buffer[playhead].step_type);
    const timer = window.setTimeout(() => setPlayhead(next), delay);
    return () => window.clearTimeout(timer);
  }, [buffer, buffer.length, playhead]);

  return useMemo(() => {
    const visibleSteps =
      playhead < 0 ? [] : buffer.slice(0, Math.min(playhead + 1, buffer.length));
    const active = playhead >= 0 && playhead < buffer.length ? buffer[playhead] : null;

    let geoFocus: GeoJSON.Geometry | null = null;
    for (const step of visibleSteps) {
      if (step.geo_focus) geoFocus = step.geo_focus;
    }

    let pulsingLayers: LayerId[] = [];
    if (
      active &&
      (active.step_type === 'action' || active.step_type === 'observation') &&
      active.tool === 'run_skill'
    ) {
      pulsingLayers = toLayerIds(resolveInputLayers(active));
    }

    const candidates: AgentEmitCandidate[] = [];
    const seen = new Set<string>();
    for (const step of visibleSteps) {
      if (step.step_type !== 'terminal' && step.tool !== 'emit') continue;
      for (const c of resolveCandidates(step)) {
        if (seen.has(c.id)) continue;
        seen.add(c.id);
        candidates.push(c);
      }
    }

    const playing = buffer.length > 0 && playhead < buffer.length - 1;

    return {
      visibleSteps,
      geoFocus,
      pulsingLayers,
      candidates,
      playing,
      playhead,
    };
  }, [buffer, playhead]);
}
