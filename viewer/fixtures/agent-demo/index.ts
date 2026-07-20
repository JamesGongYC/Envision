import { mixedCycloneCheck } from './mixed-cyclone-check';
import { quietRun } from './quiet-run';
import type { DemoVariant } from './types';
import { wildfireHeavy } from './wildfire-heavy';

export type { DemoFixtureStep, DemoVariant } from './types';

/** Flagship first; then mixed; then quiet. */
export const DEMO_VARIANTS: DemoVariant[] = [
  wildfireHeavy,
  mixedCycloneCheck,
  quietRun,
];

/**
 * Pick the next variant. Prefer random among others so repeat clicks
 * don't immediately replay the same run; fall back to cycle.
 */
export function pickNextVariant(prevId: string | null): DemoVariant {
  if (DEMO_VARIANTS.length === 0) {
    throw new Error('no demo variants');
  }
  if (DEMO_VARIANTS.length === 1) return DEMO_VARIANTS[0];

  const others = DEMO_VARIANTS.filter((v) => v.id !== prevId);
  const pool = others.length > 0 ? others : DEMO_VARIANTS;
  const idx = Math.floor(Math.random() * pool.length);
  return pool[idx] ?? DEMO_VARIANTS[0];
}

/** First click prefers the flagship wildfire-heavy run. */
export function pickInitialVariant(): DemoVariant {
  return wildfireHeavy;
}
