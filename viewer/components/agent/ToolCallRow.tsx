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

/** Single-line collapsed chip; expand for full raw input/output. */
export function ToolCallRow({ tool, input, output }: ToolCallRowProps) {
  const summary = summarizeTool(tool, input, output);

  return (
    <details className="group my-1 max-w-full">
      <summary className="cursor-pointer list-none inline-flex items-center gap-1.5 max-w-full py-0.5 px-2 rounded-sm border border-[var(--border)] bg-[var(--background)]/60 text-[11px] leading-tight font-[family-name:var(--font-mono)] text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--muted)] focus-visible:outline focus-visible:outline-1 focus-visible:outline-[var(--foreground)] focus-visible:outline-offset-2 [&::-webkit-details-marker]:hidden">
        <span
          aria-hidden
          className="shrink-0 text-[9px] opacity-70 group-open:rotate-90 transition-transform"
        >
          ▸
        </span>
        <span className="shrink-0 uppercase tracking-wider opacity-80">
          {tool}
        </span>
        <span className="min-w-0 truncate opacity-90">{summary}</span>
      </summary>
      <div className="mt-1.5 mb-2 ml-1 pl-2 border-l border-[var(--border)] space-y-2">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-[var(--muted)] mb-0.5">
            input
          </div>
          <pre className="text-[11px] leading-relaxed text-[var(--muted)] whitespace-pre-wrap break-all max-h-40 overflow-y-auto">
            {safeJson(input)}
          </pre>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-[var(--muted)] mb-0.5">
            output
          </div>
          <pre className="text-[11px] leading-relaxed text-[var(--muted)] whitespace-pre-wrap break-all max-h-48 overflow-y-auto">
            {safeJson(output)}
          </pre>
        </div>
      </div>
    </details>
  );
}
