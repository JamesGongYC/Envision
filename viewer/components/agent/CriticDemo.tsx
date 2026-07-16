'use client';

import { useCallback, useRef, useState } from 'react';
import Link from 'next/link';
import { FireControl } from '@/components/agent/FireControl';
import { TracePanel } from '@/components/agent/TracePanel';
import { ToolUseCards } from '@/components/agent/ToolUseCards';
import { EvolutionSkillTreeLoader } from '@/components/evolution-skill-tree-loader';
import { streamAgentSse } from '@/lib/sse';
import type { AgentStepEvent, SkillBrier } from '@/lib/types';
import type { LineageGraph } from '@/lib/lineage-types';

type CriticDemoProps = {
  canFire: boolean;
  briers: SkillBrier[];
  lineageGraph: LineageGraph;
};

function proposalIdFromSteps(steps: AgentStepEvent[]): string | null {
  for (let i = steps.length - 1; i >= 0; i--) {
    const s = steps[i];
    if (s.step_type !== 'terminal' || !s.output || typeof s.output !== 'object') {
      continue;
    }
    const o = s.output as Record<string, unknown>;
    if (typeof o.proposal_id === 'string') return o.proposal_id;
    if (Array.isArray(o.proposal_ids) && typeof o.proposal_ids[0] === 'string') {
      return o.proposal_ids[0];
    }
  }
  return null;
}

export function CriticDemo({ canFire, briers, lineageGraph }: CriticDemoProps) {
  const [steps, setSteps] = useState<AgentStepEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const startFire = useCallback(async () => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setSteps([]);
    setError(null);
    setBusy(true);
    await streamAgentSse({
      url: '/api/agent/critic/fire',
      method: 'POST',
      signal: ac.signal,
      onStep: (event) => setSteps((prev) => [...prev, event]),
      onDone: () => setBusy(false),
      onError: (err) => {
        setError(err.message);
        setBusy(false);
      },
    });
  }, []);

  const proposalId = proposalIdFromSteps(steps);

  return (
    <section className="space-y-4">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h2 className="font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight">
            Critic
          </h2>
          <p className="mt-1 text-sm font-[family-name:var(--font-mono)] text-[var(--muted)] max-w-xl">
            Trace window over skill fitness and lineage — no map. Targets the
            mutator/generator invention points (stub until T6).
          </p>
        </div>
        {canFire && (
          <FireControl busy={busy} onFire={() => void startFire()} label="Fire critic" />
        )}
      </div>

      {error && (
        <p className="text-xs font-[family-name:var(--font-mono)] text-red-400">
          {error}
        </p>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="space-y-3">
          <TracePanel steps={steps} streaming={busy} />
          <ToolUseCards steps={steps} />
          {proposalId && (
            <p className="text-xs font-[family-name:var(--font-mono)]">
              Proposal{' '}
              <Link
                href="/agent#proposals"
                className="underline text-[var(--muted)] hover:text-[var(--foreground)]"
              >
                {proposalId.slice(0, 8)}… in review queue
              </Link>
            </p>
          )}
        </div>
        <div className="space-y-3">
          <div className="border border-[var(--border)] bg-[var(--surface)] p-3 font-[family-name:var(--font-mono)]">
            <div className="text-[10px] uppercase tracking-wider text-[var(--muted)] mb-2">
              14d Brier
            </div>
            {briers.length === 0 ? (
              <p className="text-xs text-[var(--muted)]">No evaluations yet.</p>
            ) : (
              <table className="w-full text-xs text-left">
                <thead className="text-[var(--muted)]">
                  <tr>
                    <th className="pr-2 py-1">Skill</th>
                    <th className="pr-2 py-1">Brier</th>
                    <th className="py-1">Hits</th>
                  </tr>
                </thead>
                <tbody>
                  {briers.slice(0, 8).map((b) => (
                    <tr
                      key={b.skill_id}
                      className="border-t border-[var(--border)]"
                    >
                      <td className="pr-2 py-1">{b.skill_id}</td>
                      <td className="pr-2 py-1">
                        {b.mean_brier?.toFixed(3) ?? '—'}
                      </td>
                      <td className="py-1">{b.hits}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="border border-[var(--border)] bg-[var(--surface)] p-2 min-h-[16rem]">
            <div className="text-[10px] uppercase tracking-wider text-[var(--muted)] font-[family-name:var(--font-mono)] px-1 mb-2">
              Lineage
            </div>
            <EvolutionSkillTreeLoader graph={lineageGraph} />
          </div>
        </div>
      </div>
    </section>
  );
}
