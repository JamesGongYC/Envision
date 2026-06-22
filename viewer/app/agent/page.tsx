import {
  buildSkillCards,
  getLlmApiHealth,
  getRecentProposals,
  getSystemStatus,
} from '@/lib/agent-queries';
import { isCuratorEnabled } from '@/lib/kill-switch';
import { getSkillMetadata } from '@/lib/skill-metadata';
import { SkillCard } from '@/components/skill-card';

export const revalidate = 60;

const AGENT_EXPLAINER =
  'Envision is an experimental, self-evolving agent system that monitors ' +
  'global wildfires and tropical cyclones. Detection skills consume signals ' +
  'from public data sources and emit probabilistic forecasts; an evaluator ' +
  'scores forecasts against ground truth events; a curator periodically ' +
  'proposes refinements to the skill library, gated by operator review. ' +
  'The system is research, not a calibrated alerting product.';

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

function StatusPill({
  state,
}: {
  state: 'on' | 'off' | 'neutral';
}) {
  const color =
    state === 'on'
      ? 'bg-green-500'
      : state === 'off'
        ? 'bg-red-500'
        : 'bg-neutral-400';
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${color} align-middle`}
    />
  );
}

function llmHealthLabel(
  health: Awaited<ReturnType<typeof getLlmApiHealth>>
): { text: string; state: 'on' | 'off' | 'neutral' } {
  if (!health || health.attempts === 0) {
    return { text: 'No recent calls', state: 'neutral' };
  }
  if (health.overloaded_rate >= 0.5 && health.attempts >= 5) {
    return {
      text: `Degraded (${health.overloaded}×529 / ${health.attempts})`,
      state: 'off',
    };
  }
  const pct = Math.round((health.successes / health.attempts) * 100);
  return { text: `Healthy (${pct}% ok)`, state: 'on' };
}

export default async function AgentPage() {
  const [status, skillCards, proposals, llmHealth] = await Promise.all([
    getSystemStatus(),
    buildSkillCards(),
    getRecentProposals(10),
    getLlmApiHealth(),
  ]);

  const curatorEnabled = isCuratorEnabled();
  const pendingProposals = proposals.filter((p) => p.status === 'pending');
  const llmStatus = llmHealthLabel(llmHealth);
  const signalStale =
    llmHealth?.signal_catalog_stalest_hours != null
      ? `${Math.round(llmHealth.signal_catalog_stalest_hours)}h since oldest source`
      : undefined;

  return (
    <div className="container mx-auto px-4 py-6 max-w-5xl space-y-10">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Agent log</h1>
        <p className="mt-4 max-w-2xl text-slate-700 text-sm leading-relaxed">
          {AGENT_EXPLAINER}
        </p>
      </div>

      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-3">
          System status
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <Stat
            label="Curator mutation (Vercel env)"
            value={
              <span className="flex items-center gap-1.5">
                <StatusPill state={curatorEnabled ? 'on' : 'off'} />
                {curatorEnabled ? 'Enabled' : 'Halted'}
              </span>
            }
          />
          <Stat
            label="LLM API (10m)"
            value={
              <span className="flex items-center gap-1.5 text-slate-800">
                <StatusPill state={llmStatus.state} />
                {llmStatus.text}
              </span>
            }
            sub={signalStale}
          />
          <Stat
            label="Active forecasts"
            value={status.n_active_forecasts.toLocaleString()}
            sub={`${status.n_total_forecasts.toLocaleString()} total`}
          />
          <Stat
            label="Evaluations"
            value={status.n_total_evaluations.toLocaleString()}
            sub={`last run ${formatTime(status.last_evaluator_run)}`}
          />
          <Stat
            label="Pending proposals"
            value={status.n_pending_proposals.toLocaleString()}
            sub={status.n_pending_proposals === 0 ? 'queue empty' : 'review via CLI'}
          />
        </div>
      </section>

      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-3">
          Skill library
        </h2>
        {skillCards.length === 0 ? (
          <p className="text-sm text-neutral-500 italic">
            No skills have produced forecasts in the last 30 days.
          </p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {skillCards.map((card) => (
              <SkillCard key={card.id} {...card} />
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-3">
          Approval queue
          <span className="ml-2 normal-case tracking-normal text-neutral-400 font-normal">
            {pendingProposals.length === 0
              ? 'empty'
              : `${pendingProposals.length} pending`}
          </span>
        </h2>
        {pendingProposals.length === 0 ? (
          <p className="text-sm text-neutral-500 italic">
            No proposals awaiting review.
          </p>
        ) : (
          <ul className="border border-neutral-200 rounded divide-y divide-neutral-200">
            {pendingProposals.map((p) => (
              <ProposalRowView key={p.id} p={p} />
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-3">
          Recent Curator activity
        </h2>
        {proposals.length === 0 ? (
          <p className="text-sm text-neutral-500 italic">
            No Curator proposals on record.
          </p>
        ) : (
          <ul className="border border-neutral-200 rounded divide-y divide-neutral-200">
            {proposals.map((p) => (
              <ProposalRowView key={p.id} p={p} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: React.ReactNode;
  sub?: string;
}) {
  return (
    <div className="border border-neutral-200 rounded p-3">
      <div className="text-xs text-neutral-500">{label}</div>
      <div className="text-lg font-semibold mt-1 tabular-nums">{value}</div>
      {sub && <div className="text-xs text-neutral-400 mt-0.5">{sub}</div>}
    </div>
  );
}

function ProposalRowView({
  p,
}: {
  p: {
    id: string;
    skill_id: string;
    current_version: number;
    proposed_at: string;
    reviewed_at: string | null;
    status: 'pending' | 'approved' | 'rejected';
    curator_reasoning: string;
  };
}) {
  const meta = getSkillMetadata(p.skill_id);
  const statusColor =
    p.status === 'pending'
      ? 'bg-amber-100 text-amber-700'
      : p.status === 'approved'
        ? 'bg-green-100 text-green-700'
        : 'bg-neutral-100 text-neutral-700';
  return (
    <li className="px-4 py-3 text-sm">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <span
            className={`inline-block px-1.5 py-0.5 rounded text-xs font-medium ${statusColor}`}
          >
            {p.status}
          </span>
          <span className="font-medium">
            {meta?.displayName ?? p.skill_id}
          </span>
          <span className="text-xs text-neutral-400 font-mono">
            v{p.current_version} → v{p.current_version + 1}
          </span>
        </div>
        <div className="text-xs text-neutral-500 tabular-nums">
          {new Date(p.proposed_at).toLocaleString(undefined, {
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
          })}
        </div>
      </div>
      {p.curator_reasoning && (
        <p className="text-xs text-neutral-700 mt-1 leading-snug">
          {p.curator_reasoning}
        </p>
      )}
    </li>
  );
}
