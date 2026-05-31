import { BrierSparkline } from '@/components/brier-sparkline';
import { TOOLTIPS } from '@/lib/tooltips';

export type SkillCardProps = {
  id: string;
  displayName: string;
  plainDescription: string;
  currentVersion: number | null;
  brierMean: number | null;
  hits: number;
  falsePositives: number;
  brierByVersion: { version: number; brier: number }[];
};

function fmtBrier(b: number | null): string {
  if (b === null || b === undefined) return '—';
  return b.toFixed(4);
}

export function SkillCard({
  id,
  displayName,
  plainDescription,
  currentVersion,
  brierMean,
  hits,
  falsePositives,
  brierByVersion,
}: SkillCardProps) {
  return (
    <article className="border border-neutral-200 rounded-lg p-4 flex flex-col gap-3 bg-white">
      <header className="flex items-start justify-between gap-2">
        <h3 className="font-semibold text-neutral-900 leading-snug">
          {displayName}
        </h3>
        {currentVersion !== null && (
          <span className="shrink-0 text-xs font-mono tabular-nums px-1.5 py-0.5 rounded bg-neutral-100 text-neutral-600">
            v{currentVersion}
          </span>
        )}
      </header>
      {plainDescription ? (
        <p className="text-sm text-neutral-600 leading-snug">
          {plainDescription}
        </p>
      ) : (
        <p className="text-sm text-neutral-400 font-mono">{id}</p>
      )}
      <div className="flex items-end justify-between gap-3 mt-auto">
        <dl className="grid grid-cols-3 gap-x-4 gap-y-1 text-xs flex-1">
          <div>
            <dt
              className="text-neutral-500 cursor-help underline decoration-dotted decoration-neutral-300"
              title={TOOLTIPS.brier}
            >
              Brier
            </dt>
            <dd className="font-mono tabular-nums text-neutral-900 mt-0.5">
              {fmtBrier(brierMean)}
            </dd>
          </div>
          <div>
            <dt
              className="text-neutral-500 cursor-help underline decoration-dotted decoration-neutral-300"
              title={TOOLTIPS.hit}
            >
              Hits
            </dt>
            <dd className="font-mono tabular-nums text-green-800 mt-0.5">
              {hits}
            </dd>
          </div>
          <div>
            <dt
              className="text-neutral-500 cursor-help underline decoration-dotted decoration-neutral-300"
              title={TOOLTIPS.falsePositive}
            >
              False +
            </dt>
            <dd className="font-mono tabular-nums text-red-800 mt-0.5">
              {falsePositives}
            </dd>
          </div>
        </dl>
        <BrierSparkline data={brierByVersion} />
      </div>
    </article>
  );
}
