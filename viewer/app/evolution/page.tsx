import { EvolutionSkillTreeLoader } from '@/components/evolution-skill-tree-loader';
import { MetricLegend } from '@/components/metric-legend';
import { getLineageGraph } from '@/lib/lineage-queries';

export const revalidate = 60;

export const metadata = {
  title: 'Evolution',
};

export default async function EvolutionPage() {
  const graph = await getLineageGraph();

  return (
    <div className="container mx-auto px-4 py-8 max-w-6xl flex flex-col gap-6 min-h-[calc(100dvh-8rem)]">
      <header className="shrink-0 space-y-4 max-w-3xl">
        <h1 className="font-[family-name:var(--font-display)] text-3xl font-bold tracking-tight">
          Evolution
        </h1>
        <p className="font-[family-name:var(--font-mono)] text-sm text-[var(--muted)] leading-relaxed">
          Skill versions the curator mutates, backtests, and shadow-evaluates
          before operator promotion.
        </p>
        <MetricLegend />
      </header>

      <section className="flex-1 min-h-0">
        <EvolutionSkillTreeLoader graph={graph} />
        {graph.orphanProposalCount > 0 && (
          <p className="mt-3 text-[10px] text-[var(--muted)] font-[family-name:var(--font-mono)]">
            {graph.orphanProposalCount} proposal
            {graph.orphanProposalCount === 1 ? '' : 's'} without lineage
            (legacy) — not shown on the graph.
          </p>
        )}
      </section>
    </div>
  );
}
