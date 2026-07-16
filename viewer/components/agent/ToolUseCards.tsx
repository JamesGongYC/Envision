'use client';

import Link from 'next/link';
import type { AgentStepEvent } from '@/lib/types';

type ToolCard = {
  seq: number;
  tool: string;
  input: unknown;
  output: unknown;
};

function pairCards(steps: AgentStepEvent[]): ToolCard[] {
  const actions = steps.filter((s) => s.step_type === 'action' && s.tool);
  const observations = steps.filter(
    (s) => s.step_type === 'observation' && s.tool
  );
  return actions.map((action) => {
    const obs = observations.find(
      (o) => o.tool === action.tool && o.seq > action.seq
    );
    return {
      seq: action.seq,
      tool: action.tool!,
      input: action.input,
      output: obs?.output ?? null,
    };
  });
}

function InspectSignalsBody({ output }: { output: unknown }) {
  if (!output || typeof output !== 'object') {
    return <p className="text-[var(--muted)] text-xs">No data</p>;
  }
  const o = output as {
    catalog?: Array<{ source: string; signal_type: string; row_count: number }>;
    freshness?: Record<string, string | null>;
    scoped_counts?: Array<{ source: string; signal_type: string; count: number }>;
  };
  const rows = o.scoped_counts?.length
    ? o.scoped_counts.map((r) => ({
        source: r.source,
        type: r.signal_type,
        n: r.count,
      }))
    : (o.catalog ?? []).map((r) => ({
        source: r.source,
        type: r.signal_type,
        n: r.row_count,
      }));
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs text-left">
        <thead className="text-[var(--muted)]">
          <tr>
            <th className="pr-2 py-1">Source</th>
            <th className="pr-2 py-1">Type</th>
            <th className="py-1">N</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 12).map((r) => (
            <tr key={`${r.source}-${r.type}`} className="border-t border-[var(--border)]">
              <td className="pr-2 py-1">{r.source}</td>
              <td className="pr-2 py-1">{r.type}</td>
              <td className="py-1">{r.n}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {o.freshness && (
        <p className="text-[10px] text-[var(--muted)] mt-2">
          Freshness:{' '}
          {Object.entries(o.freshness)
            .slice(0, 4)
            .map(([k, v]) => `${k}=${v ?? '—'}`)
            .join(' · ')}
        </p>
      )}
    </div>
  );
}

function RunSkillBody({ output }: { output: unknown }) {
  const candidates =
    output &&
    typeof output === 'object' &&
    'candidates' in output &&
    Array.isArray((output as { candidates: unknown }).candidates)
      ? ((output as { candidates: Array<Record<string, unknown>> }).candidates)
      : [];
  if (!candidates.length) {
    return <p className="text-[var(--muted)] text-xs">No candidates</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs text-left">
        <thead className="text-[var(--muted)]">
          <tr>
            <th className="pr-2 py-1">Skill</th>
            <th className="pr-2 py-1">Class</th>
            <th className="py-1">p</th>
          </tr>
        </thead>
        <tbody>
          {candidates.slice(0, 8).map((c, i) => (
            <tr key={String(c.id ?? i)} className="border-t border-[var(--border)]">
              <td className="pr-2 py-1">{String(c.skill_id ?? '—')}</td>
              <td className="pr-2 py-1">{String(c.disaster_class ?? '—')}</td>
              <td className="py-1">
                {typeof c.probability === 'number'
                  ? c.probability.toFixed(2)
                  : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EmitBody({ output }: { output: unknown }) {
  const ids =
    output &&
    typeof output === 'object' &&
    'emitted_ids' in output &&
    Array.isArray((output as { emitted_ids: unknown }).emitted_ids)
      ? ((output as { emitted_ids: string[] }).emitted_ids)
      : [];
  if (!ids.length) {
    return <p className="text-[var(--muted)] text-xs">Empty selection</p>;
  }
  return (
    <ul className="text-xs space-y-1">
      {ids.map((id) => (
        <li key={id}>
          <Link
            href={`/forecast/${id}`}
            className="underline text-[var(--muted)] hover:text-[var(--foreground)]"
          >
            {id.slice(0, 8)}…
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function ToolUseCards({ steps }: { steps: AgentStepEvent[] }) {
  const cards = pairCards(steps);
  if (!cards.length) {
    return (
      <div className="border border-[var(--border)] bg-[var(--surface)] p-3 text-xs text-[var(--muted)] font-[family-name:var(--font-mono)]">
        Tool use will appear here.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2 font-[family-name:var(--font-mono)]">
      {cards.map((card) => (
        <div
          key={card.seq}
          className="border border-[var(--border)] bg-[var(--surface)] p-3"
        >
          <div className="text-[10px] uppercase tracking-wider text-[var(--muted)] mb-2">
            #{card.seq} · {card.tool}
          </div>
          {card.tool === 'inspect_signals' && (
            <InspectSignalsBody output={card.output} />
          )}
          {card.tool === 'run_skill' && <RunSkillBody output={card.output} />}
          {card.tool === 'emit' && <EmitBody output={card.output} />}
          {card.tool === 'list_skills' && (
            <pre className="text-xs text-[var(--muted)] whitespace-pre-wrap break-all max-h-40 overflow-y-auto">
              {JSON.stringify(card.output, null, 2)?.slice(0, 800)}
            </pre>
          )}
          {!['inspect_signals', 'run_skill', 'emit', 'list_skills'].includes(
            card.tool
          ) && (
            <pre className="text-xs text-[var(--muted)] whitespace-pre-wrap break-all max-h-32 overflow-y-auto">
              {JSON.stringify(card.output ?? card.input, null, 2)?.slice(0, 600)}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}
