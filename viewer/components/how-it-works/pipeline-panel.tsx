'use client';

import type { ReactNode } from 'react';

export type PipelinePanelProps = {
  id: string;
  title: string;
  summary: string;
  detail: ReactNode;
  telemetry: string;
  expanded: boolean;
  onToggle: () => void;
  showConnector?: boolean;
};

export function PipelinePanel({
  id,
  title,
  summary,
  detail,
  telemetry,
  expanded,
  onToggle,
  showConnector = true,
}: PipelinePanelProps) {
  return (
    <div className="flex items-stretch flex-1 min-w-0">
      <article
        className={`flex-1 min-w-0 border border-[var(--border)] rounded bg-[var(--surface)] overflow-hidden transition-colors ${
          expanded ? 'border-[var(--foreground)]/40' : ''
        }`}
      >
        <button
          type="button"
          id={`panel-${id}`}
          aria-expanded={expanded}
          aria-controls={`panel-${id}-detail`}
          onClick={onToggle}
          className="w-full text-left p-4 focus:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-[var(--foreground)]"
        >
          <h2 className="font-[family-name:var(--font-display)] font-bold text-lg text-[var(--foreground)]">
            {title}
          </h2>
          <p className="mt-2 text-xs text-[var(--muted)] font-[family-name:var(--font-mono)] leading-relaxed">
            {summary}
          </p>
          <p className="mt-3 text-[10px] uppercase tracking-wide text-[var(--foreground)] font-[family-name:var(--font-mono)] tabular-nums">
            {telemetry}
          </p>
        </button>
        <div
          id={`panel-${id}-detail`}
          className={`grid transition-[grid-template-rows] duration-300 motion-reduce:transition-none ${
            expanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
          }`}
        >
          <div className="overflow-hidden">
            <div className="px-4 pb-4 pt-0 border-t border-[var(--border)] text-sm text-[var(--muted)] font-[family-name:var(--font-mono)] leading-relaxed space-y-3">
              {detail}
            </div>
          </div>
        </div>
      </article>
      {showConnector && (
        <div
          className="hidden md:flex items-center shrink-0 w-8 justify-center text-[var(--border)]"
          aria-hidden
        >
          <span className="text-2xl">→</span>
        </div>
      )}
    </div>
  );
}
