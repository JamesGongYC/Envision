'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { ToolCallRow } from '@/components/agent/ToolCallRow';
import { ProducerBadge } from '@/components/producer-badge';
import { TypingText } from '@/components/typing-text';
import type { AgentStepEvent } from '@/lib/types';

export type AgentTranscriptVariant = 'forecaster' | 'critic';

type TranscriptItem =
  | { kind: 'thought'; key: string; seq: number; text: string }
  | {
      kind: 'tool';
      key: string;
      seq: number;
      tool: string;
      input: unknown;
      output: unknown;
      waiting: boolean;
    }
  | { kind: 'gated'; key: string; seq: number; reason: string }
  | { kind: 'failed'; key: string; seq: number; reason: string }
  | { kind: 'terminal'; key: string; seq: number; step: AgentStepEvent };

function thoughtText(step: AgentStepEvent): string {
  const out = step.output;
  if (out && typeof out === 'object' && 'text' in out) {
    return String((out as { text: unknown }).text ?? '');
  }
  return '';
}

function reasonFrom(step: AgentStepEvent): string {
  if (step.output && typeof step.output === 'object' && 'reason' in step.output) {
    return String((step.output as { reason: unknown }).reason ?? step.step_type);
  }
  if (step.output && typeof step.output === 'object' && 'error' in step.output) {
    return String((step.output as { error: unknown }).error ?? step.step_type);
  }
  return step.step_type;
}

function foldSteps(steps: AgentStepEvent[]): TranscriptItem[] {
  const items: TranscriptItem[] = [];
  const usedObs = new Set<number>();

  for (let i = 0; i < steps.length; i++) {
    const step = steps[i];
    const key = `${step.run_id ?? 'run'}-${step.seq}`;

    if (step.step_type === 'thought') {
      items.push({
        kind: 'thought',
        key,
        seq: step.seq,
        text: thoughtText(step) || '…',
      });
      continue;
    }

    if (step.step_type === 'action' && step.tool) {
      let obs: AgentStepEvent | undefined;
      for (let j = i + 1; j < steps.length; j++) {
        const cand = steps[j];
        if (
          cand.step_type === 'observation' &&
          cand.tool === step.tool &&
          !usedObs.has(cand.seq)
        ) {
          obs = cand;
          usedObs.add(cand.seq);
          break;
        }
      }
      items.push({
        kind: 'tool',
        key,
        seq: step.seq,
        tool: step.tool,
        input: step.input,
        output: obs?.output ?? null,
        waiting: !obs,
      });
      continue;
    }

    if (step.step_type === 'observation') {
      if (usedObs.has(step.seq)) continue;
      // Orphan observation — still show as tool row
      items.push({
        kind: 'tool',
        key,
        seq: step.seq,
        tool: step.tool ?? 'tool',
        input: null,
        output: step.output,
        waiting: false,
      });
      continue;
    }

    if (step.step_type === 'gated') {
      items.push({ kind: 'gated', key, seq: step.seq, reason: reasonFrom(step) });
      continue;
    }

    if (step.step_type === 'failed') {
      items.push({ kind: 'failed', key, seq: step.seq, reason: reasonFrom(step) });
      continue;
    }

    if (step.step_type === 'terminal') {
      items.push({ kind: 'terminal', key, seq: step.seq, step });
    }
  }

  return items;
}

function TerminalSummary({
  variant,
  step,
}: {
  variant: AgentTranscriptVariant;
  step: AgentStepEvent;
}) {
  const out =
    step.output && typeof step.output === 'object'
      ? (step.output as Record<string, unknown>)
      : {};

  if (variant === 'forecaster') {
    const ids = Array.isArray(out.emitted_ids)
      ? (out.emitted_ids as string[])
      : [];
    return (
      <div className="border border-[var(--border)] bg-[var(--surface)] px-3 py-3 space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <p className="text-sm font-[family-name:var(--font-display)] font-semibold tracking-tight">
            Emitted {ids.length} forecast{ids.length === 1 ? '' : 's'}
          </p>
          <ProducerBadge producer="agent" />
        </div>
        {ids.length > 0 && (
          <ul className="text-xs font-[family-name:var(--font-mono)] text-[var(--muted)] space-y-1">
            {ids.slice(0, 12).map((id) => (
              <li key={id}>
                <Link
                  href={`/forecast/${id}`}
                  className="underline hover:text-[var(--foreground)]"
                >
                  {id.slice(0, 8)}…
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  const proposalIds = Array.isArray(out.proposal_ids)
    ? (out.proposal_ids as string[])
    : typeof out.proposal_id === 'string'
      ? [out.proposal_id]
      : [];
  const tool = step.tool ?? 'mutate/generate';
  const target =
    proposalIds.length > 0
      ? proposalIds.map((id) => id.slice(0, 8)).join(', ')
      : 'no proposal';

  return (
    <div className="border border-[var(--border)] bg-[var(--surface)] px-3 py-3 space-y-2">
      <p className="text-sm font-[family-name:var(--font-display)] font-semibold tracking-tight">
        Proposed {tool} — {target}
      </p>
      {proposalIds.length > 0 && (
        <p className="text-xs font-[family-name:var(--font-mono)] text-[var(--muted)]">
          <Link
            href="/agent#proposals"
            className="underline hover:text-[var(--foreground)]"
          >
            Open review queue
          </Link>
          {proposalIds.length === 1 ? ` · ${proposalIds[0].slice(0, 8)}…` : ''}
        </p>
      )}
    </div>
  );
}

export function AgentTranscript({
  steps,
  streaming,
  variant,
}: {
  steps: AgentStepEvent[];
  streaming?: boolean;
  variant: AgentTranscriptVariant;
}) {
  const items = foldSteps(steps);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [stickToBottom, setStickToBottom] = useState(true);
  const [showJump, setShowJump] = useState(false);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !stickToBottom) {
      setShowJump(!stickToBottom && items.length > 0);
      return;
    }
    el.scrollTop = el.scrollHeight;
    setShowJump(false);
  }, [items, stickToBottom, streaming]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    const nearBottom = distance < 48;
    setStickToBottom(nearBottom);
    setShowJump(!nearBottom);
  };

  const jumpToLatest = () => {
    setStickToBottom(true);
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    setShowJump(false);
  };

  const last = items[items.length - 1];
  const waitingTool = items.some((it) => it.kind === 'tool' && it.waiting);
  const afterThoughtAwaitingTool =
    Boolean(streaming) && last?.kind === 'thought';
  const pulseThinking = afterThoughtAwaitingTool || (Boolean(streaming) && waitingTool);

  return (
    <div className="relative border border-[var(--border)] bg-[var(--surface)]">
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border)]">
        <div className="text-[10px] uppercase tracking-wider font-[family-name:var(--font-mono)] text-[var(--muted)]">
          Transcript{streaming ? ' · playing' : ''}
        </div>
      </div>

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="max-h-[32rem] overflow-y-auto px-3 py-4 space-y-5"
      >
        {items.length === 0 && (
          <p className="text-sm text-[var(--muted)] font-[family-name:var(--font-mono)]">
            {streaming ? 'Waiting for steps…' : 'No steps yet.'}
          </p>
        )}

        {items.map((item) => {
          if (item.kind === 'thought') {
            return (
              <div key={item.key} className="space-y-1.5">
                <p className="text-base md:text-lg leading-relaxed text-[var(--foreground)] font-[family-name:var(--font-display)]">
                  <TypingText
                    key={`thought-${item.seq}`}
                    text={item.text}
                    charsPerSecond={36}
                  />
                </p>
              </div>
            );
          }

          if (item.kind === 'tool') {
            return (
              <div key={item.key} className="py-0.5">
                <ToolCallRow
                  tool={item.tool}
                  input={item.input}
                  output={item.output}
                />
                {item.waiting && streaming && (
                  <p className="pl-2 text-[10px] font-[family-name:var(--font-mono)] text-[var(--muted)] animate-pulse">
                    waiting for result…
                  </p>
                )}
              </div>
            );
          }

          if (item.kind === 'gated') {
            return (
              <div
                key={item.key}
                className="border border-[var(--border)] px-3 py-2 text-sm font-[family-name:var(--font-mono)] text-[var(--muted)]"
              >
                Run paused — {humanizeGate(item.reason)}
              </div>
            );
          }

          if (item.kind === 'failed') {
            return (
              <div
                key={item.key}
                className="border border-red-500/40 px-3 py-2 text-sm font-[family-name:var(--font-mono)] text-red-400"
              >
                Run failed — {item.reason}
              </div>
            );
          }

          return (
            <TerminalSummary
              key={item.key}
              variant={variant}
              step={item.step}
            />
          );
        })}

        {pulseThinking && last?.kind === 'thought' && (
          <p className="text-xs font-[family-name:var(--font-mono)] text-[var(--muted)] animate-pulse">
            thinking…
          </p>
        )}
      </div>

      {showJump && (
        <button
          type="button"
          onClick={jumpToLatest}
          className="absolute bottom-3 right-3 z-10 px-2.5 py-1.5 text-[10px] uppercase tracking-wider font-[family-name:var(--font-mono)] border border-[var(--border)] bg-[var(--background)] text-[var(--muted)] hover:text-[var(--foreground)] shadow-sm"
        >
          Jump to latest
        </button>
      )}
    </div>
  );
}

function humanizeGate(reason: string): string {
  if (reason.includes('max_in_flight')) return 'provider capacity (max in-flight)';
  if (reason.includes('preflight')) return 'provider degraded (preflight)';
  if (reason.includes('529') || reason.includes('rolling')) {
    return 'provider degraded (rolling 529)';
  }
  if (reason.includes('critic_not_shipped')) return 'critic unavailable';
  return reason.replace(/_/g, ' ');
}
