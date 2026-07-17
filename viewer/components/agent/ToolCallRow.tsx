'use client';

import { summarizeTool } from '@/components/agent/summarizeTool';

export type ToolCallRowProps = {
  tool: string;
  input: unknown;
  output: unknown;
};

function safeJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? null, null, 2) ?? 'null';
  } catch {
    return String(value);
  }
}

export function ToolCallRow({ tool, input, output }: ToolCallRowProps) {
  const summary = summarizeTool(tool, input, output);

  return (
    <details className="group border-t border-[var(--border)] first:border-t-0">
      <summary className="cursor-pointer list-none flex items-baseline gap-2 py-1.5 px-0.5 text-xs font-[family-name:var(--font-mono)] text-[var(--muted)] hover:text-[var(--foreground)] focus-visible:outline focus-visible:outline-1 focus-visible:outline-[var(--foreground)] focus-visible:outline-offset-2 [&::-webkit-details-marker]:hidden">
        <span className="shrink-0 text-[var(--muted)] group-open:rotate-90 transition-transform inline-block">
          ▸
        </span>
        <span className="shrink-0 uppercase tracking-wider">{tool}</span>
        <span className="min-w-0 truncate">{summary}</span>
      </summary>
      <div className="pb-2 pl-4 space-y-2">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-[var(--muted)] mb-1">
            input
          </div>
          <pre className="text-[11px] leading-relaxed text-[var(--muted)] whitespace-pre-wrap break-all max-h-48 overflow-y-auto">
            {safeJson(input)}
          </pre>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-[var(--muted)] mb-1">
            output
          </div>
          <pre className="text-[11px] leading-relaxed text-[var(--muted)] whitespace-pre-wrap break-all max-h-56 overflow-y-auto">
            {safeJson(output)}
          </pre>
        </div>
      </div>
    </details>
  );
}
