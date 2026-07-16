import { ForecasterDemo } from '@/components/agent/ForecasterDemo';
import { CriticDemo } from '@/components/agent/CriticDemo';
import {
  buildSkillCards,
  getLlmApiHealth,
  getRecentProposals,
  getSystemStatus,
} from '@/lib/agent-queries';
import { getLatestCompletedRun } from '@/lib/agent-run-queries';
import { isCuratorEnabled } from '@/lib/kill-switch';
import { getLineageGraph } from '@/lib/lineage-queries';
import { getActiveForecasts, getSkillBriers } from '@/lib/queries';
import { getSkillMetadata } from '@/lib/skill-metadata';

export const revalidate = 60;

export const metadata = {
  title: 'Agent',
};

function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  });
}

export default async function AgentPage() {
  const canFire = Boolean(process.env.ENVISION_OPERATOR_TOKEN);

  const [
    forecasts,
    lastForecaster,
    briers,
    lineageGraph,
    status,
    proposals,
    llmHealth,
    skillCards,
  ] = await Promise.all([
    getActiveForecasts(),
    getLatestCompletedRun('forecaster'),
    getSkillBriers(),
    getLineageGraph(),
    getSystemStatus(),
    getRecentProposals(8),
    getLlmApiHealth(),
    buildSkillCards(),
  ]);

  const curatorEnabled = isCuratorEnabled();
  const pendingProposals = proposals.filter((p) => p.status === 'pending');

  return (
    <div className="container mx-auto px-4 py-8 max-w-6xl flex flex-col gap-12">
      <header className="space-y-3 max-w-3xl">
        <h1 className="font-[family-name:var(--font-display)] text-3xl font-bold tracking-tight">
          Agent
        </h1>
        <p className="font-[family-name:var(--font-mono)] text-sm text-[var(--muted)] leading-relaxed">
          Watch the forecaster reason over signals and skills, and the critic
          inspect fitness. Live fire is operator-gated; the public surface
          replays the last real run.
        </p>
      </header>

      <ForecasterDemo
        canFire={canFire}
        lastRunId={lastForecaster?.id ?? null}
        forecasts={forecasts}
      />

      <CriticDemo
        canFire={canFire}
        briers={briers}
        lineageGraph={lineageGraph}
      />

      <section className="space-y-4 border-t border-[var(--border)] pt-8">
        <h2 className="font-[family-name:var(--font-display)] text-xl font-bold tracking-tight">
          System
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 font-[family-name:var(--font-mono)]">
          <Stat
            label="Curator"
            value={curatorEnabled ? 'Enabled' : 'Halted'}
          />
          <Stat
            label="Active forecasts"
            value={String(status.n_active_forecasts)}
          />
          <Stat
            label="Evaluations"
            value={String(status.n_total_evaluations)}
            sub={`last ${formatTime(status.last_evaluator_run)}`}
          />
          <Stat
            label="LLM (10m)"
            value={
              !llmHealth || llmHealth.attempts === 0
                ? 'No calls'
                : `${Math.round((llmHealth.successes / llmHealth.attempts) * 100)}% ok`
            }
          />
        </div>
      </section>

      <section id="proposals" className="space-y-3">
        <h2 className="font-[family-name:var(--font-display)] text-xl font-bold tracking-tight">
          Approval queue
          <span className="ml-2 text-sm font-normal font-[family-name:var(--font-mono)] text-[var(--muted)]">
            {pendingProposals.length === 0
              ? 'empty'
              : `${pendingProposals.length} pending`}
          </span>
        </h2>
        {pendingProposals.length === 0 ? (
          <p className="text-sm font-[family-name:var(--font-mono)] text-[var(--muted)]">
            No proposals awaiting review.
          </p>
        ) : (
          <ul className="border border-[var(--border)] divide-y divide-[var(--border)]">
            {pendingProposals.map((p) => {
              const meta = getSkillMetadata(p.skill_id);
              return (
                <li
                  key={p.id}
                  className="px-4 py-3 text-sm font-[family-name:var(--font-mono)]"
                >
                  <div className="flex items-baseline justify-between gap-3 flex-wrap">
                    <span className="text-[var(--foreground)]">
                      {meta?.displayName ?? p.skill_id}
                      <span className="text-[var(--muted)] ml-2">
                        v{p.current_version}
                      </span>
                    </span>
                    <span className="text-xs text-[var(--muted)]">
                      {formatTime(p.proposed_at)}
                    </span>
                  </div>
                  {p.curator_reasoning && (
                    <p className="text-xs text-[var(--muted)] mt-1 leading-snug">
                      {p.curator_reasoning}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {skillCards.length > 0 && (
        <p className="text-[10px] font-[family-name:var(--font-mono)] text-[var(--muted)]">
          Attribution: FIRMS, NWS, Open-Meteo, NHC, JTWC, ECMWF, AIFS, GDACS —
          see How it works. {skillCards.length} skills with recent activity.
        </p>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="border border-[var(--border)] bg-[var(--surface)] p-3">
      <div className="text-[10px] uppercase tracking-wider text-[var(--muted)]">
        {label}
      </div>
      <div className="text-lg mt-1 tabular-nums text-[var(--foreground)]">
        {value}
      </div>
      {sub && (
        <div className="text-[10px] text-[var(--muted)] mt-0.5">{sub}</div>
      )}
    </div>
  );
}
