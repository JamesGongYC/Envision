'use client';

import dynamic from 'next/dynamic';
import type { LineageGraph } from '@/lib/lineage-types';

const SkillTree = dynamic(
  () => import('@/components/skill-tree').then((m) => m.SkillTree),
  {
    ssr: false,
    loading: () => (
      <div className="h-[min(70vh,720px)] border border-[var(--border)] rounded flex items-center justify-center text-xs text-[var(--muted)] font-[family-name:var(--font-mono)]">
        Loading lineage…
      </div>
    ),
  }
);

export function EvolutionSkillTreeLoader({ graph }: { graph: LineageGraph }) {
  return <SkillTree graph={graph} />;
}
