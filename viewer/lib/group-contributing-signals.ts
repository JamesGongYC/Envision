import {
  signalSourceLabel,
  signalSourceUrl,
} from '@/lib/signal-sources';
import type { Signal } from '@/lib/types';

export type GroupedContributingSignal = {
  source: string;
  label: string;
  count: number;
  url: string | null;
  signalTypes: string[];
};

/**
 * One row per distinct source; single attribution link per group (TOS).
 */
export function groupContributingSignals(
  signals: Signal[]
): GroupedContributingSignal[] {
  const bySource = new Map<string, Signal[]>();

  for (const s of signals) {
    const list = bySource.get(s.source) ?? [];
    list.push(s);
    bySource.set(s.source, list);
  }

  return [...bySource.entries()]
    .map(([source, group]) => {
      const representative = group[0]!;
      const signalTypes = [...new Set(group.map((s) => s.signal_type))].sort();
      return {
        source,
        label: signalSourceLabel(representative),
        count: group.length,
        url: signalSourceUrl(representative),
        signalTypes,
      };
    })
    .sort((a, b) => b.count - a.count);
}
