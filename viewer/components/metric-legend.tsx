import { TOOLTIPS } from '@/lib/tooltips';

export function MetricLegend() {
  return (
    <dl className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs font-[family-name:var(--font-mono)] border border-[var(--border)] rounded p-4 bg-[var(--surface)]">
      <div>
        <dt className="font-semibold text-[var(--foreground)] uppercase tracking-wide text-[10px] mb-1">
          Brier score
        </dt>
        <dd className="text-[var(--muted)] leading-relaxed">{TOOLTIPS.brier}</dd>
      </div>
      <div>
        <dt className="font-semibold text-[var(--foreground)] uppercase tracking-wide text-[10px] mb-1">
          Hit
        </dt>
        <dd className="text-[var(--muted)] leading-relaxed">{TOOLTIPS.hit}</dd>
      </div>
      <div>
        <dt className="font-semibold text-[var(--foreground)] uppercase tracking-wide text-[10px] mb-1">
          False positive
        </dt>
        <dd className="text-[var(--muted)] leading-relaxed">
          {TOOLTIPS.falsePositive}
        </dd>
      </div>
    </dl>
  );
}
