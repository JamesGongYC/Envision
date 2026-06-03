import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ContributingSignalsList } from '@/components/contributing-signals-list';
import ForecastDetailMap from '@/components/forecast-detail-map';
import { groupContributingSignals } from '@/lib/group-contributing-signals';
import {
  getContributingSignals,
  getForecast,
} from '@/lib/queries';

export const revalidate = 60;

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  });
}

function isUuidLike(v: string): boolean {
  return /^[0-9a-fA-F-]{20,}$/.test(v);
}

export default async function ForecastPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!isUuidLike(id)) notFound();

  const forecast = await getForecast(id);
  if (!forecast) notFound();

  const signals = await getContributingSignals(
    forecast.contributing_signal_ids ?? []
  );
  const groups = groupContributingSignals(signals);

  const isWildfire = forecast.disaster_class === 'wildfire';
  const probabilityPct = (forecast.probability * 100).toFixed(0);

  return (
    <div className="container mx-auto px-4 py-6 max-w-5xl space-y-6 font-[family-name:var(--font-mono)]">
      <div>
        <Link
          href="/"
          className="text-xs text-[var(--muted)] hover:text-[var(--foreground)]"
        >
          ← Back to map
        </Link>
      </div>

      <div className="flex items-start justify-between gap-6 flex-wrap pb-4 border-b border-[var(--border)]">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span
              className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                isWildfire
                  ? 'bg-red-950 text-red-300 border border-red-800'
                  : 'bg-blue-950 text-blue-300 border border-blue-800'
              }`}
            >
              {forecast.disaster_class}
            </span>
            <code className="text-xs text-[var(--muted)]">
              {forecast.skill_id} v{forecast.skill_version}
            </code>
          </div>
          <h1 className="text-2xl font-[family-name:var(--font-display)] font-bold tracking-tight text-[var(--foreground)]">
            Forecast detail
          </h1>
          <div className="text-xs text-[var(--muted)] mt-1">
            ID <code>{forecast.id}</code>
          </div>
        </div>
        <div className="text-right">
          <div className="text-4xl font-bold tabular-nums text-[var(--foreground)]">
            {probabilityPct}%
          </div>
          <div className="text-xs text-[var(--muted)]">probability</div>
        </div>
      </div>

      <div className="h-[50vh] min-h-[400px] rounded border border-[var(--border)] overflow-hidden">
        <ForecastDetailMap forecast={forecast} />
      </div>

      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)] mb-2">
          Reasoning
        </h2>
        <p className="text-[var(--foreground)] leading-relaxed">
          {forecast.reasoning}
        </p>
      </section>

      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)] mb-2">
          Validity window
        </h2>
        <dl className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
          <div>
            <dt className="text-xs text-[var(--muted)]">Issued</dt>
            <dd className="font-medium text-[var(--foreground)]">
              {formatTime(forecast.issued_at)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--muted)]">Valid from</dt>
            <dd className="font-medium text-[var(--foreground)]">
              {formatTime(forecast.valid_from)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--muted)]">Valid until</dt>
            <dd className="font-medium text-[var(--foreground)]">
              {formatTime(forecast.valid_until)}
            </dd>
          </div>
        </dl>
      </section>

      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)] mb-2">
          Contributing signals
          <span className="ml-2 text-xs font-normal normal-case tracking-normal">
            {signals.length} of {forecast.contributing_signal_ids?.length ?? 0}
            {signals.length <
              (forecast.contributing_signal_ids?.length ?? 0) && (
              <> — older ones may have been purged by retention</>
            )}
          </span>
        </h2>
        <ContributingSignalsList groups={groups} />
      </section>

      <div className="pt-4 border-t border-[var(--border)] text-xs text-[var(--muted)]">
        Produced by an automated experimental system —{' '}
        <Link href="/disclaimer" className="underline hover:text-[var(--foreground)]">
          read disclaimer
        </Link>
        .
      </div>
    </div>
  );
}
