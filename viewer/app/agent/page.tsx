import Link from 'next/link';
import {
  getRecentProposals,
  getSkillRegistry,
  getSystemStatus,
} from '@/lib/agent-queries';
import { isCuratorEnabled } from '@/lib/kill-switch';
import { SKILL_METADATA } from '@/lib/skill-metadata';

export const revalidate = 60;

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

function formatBrier(b: number | null): string {
  if (b === null || b === undefined) return '—';
  return b.toFixed(3);
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

export default async function AgentPage() {
  const [status, skills, proposals] = await Promise.all([
    getSystemStatus(),
    getSkillRegistry(),
    getRecentProposals(10),
  ]);

  const curatorEnabled = isCuratorEnabled();
  const pendingProposals = proposals.filter((p) => p.status === 'pending');

  return (
    <div className="container mx-auto px-4 py-6 max-w-5xl space-y-10">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Agent log</h1>
        <p className="mt-2 text-sm text-neutral-600 max-w-prose">
          Read-only operational view of the Envision agent. Skill library,
          14-day evaluation scores, and pending Curator activity. Auto-refreshes
          every 60 seconds.
        </p>
      </div>

      {/* System status */}
      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-3">
          System status
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Stat
            label="Curator mutation"
            value={
              <span className="flex items-center gap-1.5">
                <StatusPill state={curatorEnabled ? 'on' : 'off'} />
                {curatorEnabled ? 'Enabled' : 'Halted'}
              </span>
            }
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

      {/* Skill library */}
      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-3">
          Skill library
        </h2>
        {skills.length === 0 ? (
          <p className="text-sm text-neutral-500 italic">
            No skills have produced forecasts yet.
          </p>
        ) : (
          <div className="border border-neutral-200 rounded overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-neutral-50 text-xs text-neutral-500 uppercase tracking-wide">
                <tr>
                  <th className="text-left px-4 py-2 font-medium">Skill</th>
                  <th className="text-right px-4 py-2 font-medium">Cadence</th>
                  <th className="text-right px-4 py-2 font-medium">
                    Active / Total
                  </th>
                  <th className="text-right px-4 py-2 font-medium">
                    Brier (14d)
                  </th>
                  <th className="text-right px-4 py-2 font-medium">
                    Hits / FP
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-200">
                {skills.map((s) => {
                  const meta = SKILL_METADATA[s.skill_id];
                  return (
                    <tr key={s.skill_id}>
                      <td className="px-4 py-3 align-top">
                        <div className="font-medium">
                          {meta?.label ?? s.skill_id}{' '}
                          <code className="text-xs text-neutral-400 font-normal">
                            v{s.version}
                          </code>
                        </div>
                        {meta?.description && (
                          <div className="text-xs text-neutral-500 mt-0.5 leading-snug max-w-prose">
                            {meta.description}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right text-neutral-600 tabular-nums">
                        {meta?.cadence ?? '—'}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        <span className="font-medium">{s.n_active}</span>
                        <span className="text-neutral-400"> / </span>
                        <span className="text-neutral-600">{s.n_forecasts}</span>
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {formatBrier(s.mean_brier)}
                        <div className="text-xs text-neutral-400">
                          {s.n_evaluations
                            ? `${s.n_evaluations} eval${s.n_evaluations === 1 ? '' : 's'}`
                            : 'no evals yet'}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        <span className="text-green-700">{s.hits}</span>
                        <span className="text-neutral-400"> / </span>
                        <span className="text-red-700">{s.false_positives}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-xs text-neutral-400 mt-2">
          Lower Brier scores indicate better-calibrated forecasts. Probability is
          capped at 0.85 server-side, so a perfect hit has Brier 0.0225.
        </p>
      </section>

      {/* Approval queue */}
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
            No proposals awaiting review. The Curator has not made any
            mutations yet (or all proposals have been approved/rejected).
          </p>
        ) : (
          <ul className="border border-neutral-200 rounded divide-y divide-neutral-200">
            {pendingProposals.map((p) => (
              <ProposalRowView key={p.id} p={p} />
            ))}
          </ul>
        )}
      </section>

      {/* Recent activity */}
      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-3">
          Recent Curator activity
        </h2>
        {proposals.length === 0 ? (
          <p className="text-sm text-neutral-500 italic">
            No Curator proposals on record. The Curator becomes active in Day 6.
          </p>
        ) : (
          <ul className="border border-neutral-200 rounded divide-y divide-neutral-200">
            {proposals.map((p) => (
              <ProposalRowView key={p.id} p={p} />
            ))}
          </ul>
        )}
      </section>

      <div className="pt-6 border-t border-neutral-200 text-xs text-neutral-500">
        This is a read-only view. Approval, rejection, and deployment of
        Curator proposals are gated behind the operator CLI (
        <code>tools/review_proposals.py</code>) — see{' '}
        <Link href="/about" className="underline">
          about
        </Link>
        .
      </div>
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
          <code className="text-xs">{p.skill_id}</code>
          <span className="text-xs text-neutral-400">v{p.current_version} → v{p.current_version + 1}</span>
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
