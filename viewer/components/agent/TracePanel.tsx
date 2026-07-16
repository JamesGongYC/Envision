'use client';

import { TypingText } from '@/components/typing-text';
import type { AgentStepEvent } from '@/lib/types';

function thoughtText(step: AgentStepEvent): string {
  const out = step.output;
  if (out && typeof out === 'object' && 'text' in out) {
    return String((out as { text: unknown }).text ?? '');
  }
  return '';
}

function endLabel(step: AgentStepEvent): string {
  if (step.step_type === 'gated') {
    const reason =
      step.output &&
      typeof step.output === 'object' &&
      'reason' in step.output
        ? String((step.output as { reason: unknown }).reason)
        : 'gated';
    return `Gated — ${reason}`;
  }
  if (step.step_type === 'terminal') {
    const ids =
      step.output &&
      typeof step.output === 'object' &&
      'emitted_ids' in step.output
        ? ((step.output as { emitted_ids?: string[] }).emitted_ids ?? [])
        : [];
    if (ids.length) return `Terminal — emitted ${ids.length} forecast(s)`;
    return 'Terminal — empty set';
  }
  return step.step_type;
}

export function TracePanel({
  steps,
  streaming,
}: {
  steps: AgentStepEvent[];
  streaming?: boolean;
}) {
  const visible = steps.filter(
    (s) =>
      s.step_type === 'thought' ||
      s.step_type === 'gated' ||
      s.step_type === 'terminal' ||
      s.step_type === 'action'
  );

  return (
    <div className="flex flex-col gap-3 font-[family-name:var(--font-mono)] text-sm max-h-[28rem] overflow-y-auto border border-[var(--border)] bg-[var(--surface)] p-3">
      <div className="text-[10px] uppercase tracking-wider text-[var(--muted)]">
        Trace{streaming ? ' · live' : ''}
      </div>
      {visible.length === 0 && (
        <p className="text-[var(--muted)] text-xs">
          {streaming ? 'Waiting for steps…' : 'No steps yet.'}
        </p>
      )}
      {visible.map((step) => (
        <div
          key={`${step.run_id}-${step.seq}`}
          className="border-b border-[var(--border)] pb-2 last:border-0"
        >
          <div className="text-[10px] uppercase tracking-wider text-[var(--muted)] mb-1">
            #{step.seq} · {step.step_type}
            {step.tool ? ` · ${step.tool}` : ''}
          </div>
          {step.step_type === 'thought' && (
            <div className="text-[var(--foreground)] leading-relaxed">
              <TypingText
                key={`thought-${step.seq}`}
                text={thoughtText(step) || '…'}
              />
            </div>
          )}
          {step.step_type === 'action' && (
            <pre className="text-xs text-[var(--muted)] whitespace-pre-wrap break-all">
              {JSON.stringify(step.input ?? {}, null, 2)}
            </pre>
          )}
          {(step.step_type === 'gated' || step.step_type === 'terminal') && (
            <p className="text-[var(--foreground)]">{endLabel(step)}</p>
          )}
        </div>
      ))}
    </div>
  );
}
