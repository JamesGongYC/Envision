import Link from 'next/link';
import { notFound } from 'next/navigation';
import ForecastDetailMap from '@/components/forecast-detail-map';
import {
  getContributingSignals,
  getForecast,
} from '@/lib/queries';
import {
  signalSourceLabel,
  signalSourceUrl,
} from '@/lib/signal-sources';

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

  const isWildfire = forecast.disaster_class === 'wildfire';
  const probabilityPct = (forecast.probability * 100).toFixed(0);

  return (
    <div className="container mx-auto px-4 py-6 max-w-5xl space-y-6">
      <div>
        <Link
          href="/"
          className="text-xs text-neutral-500 hover:text-neutral-900"
        >
          ← Back to map
        </Link>
      </div>

      {/* Header */}
      <div className="flex items-start justify-between gap-6 flex-wrap pb-4 border-b border-neutral-200">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span
              className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                isWildfire
                  ? 'bg-red-100 text-red-700'
                  : 'bg-blue-100 text-blue-700'
              }`}
            >
              {forecast.disaster_class}
            </span>
            <code className="text-xs text-neutral-500">
              {forecast.skill_id} v{forecast.skill_version}
            </code>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Forecast detail
          </h1>
          <div className="text-xs text-neutral-500 mt-1">
            ID <code>{forecast.id}</code>
          </div>
        </div>
        <div className="text-right">
          <div className="text-4xl font-bold tabular-nums">
            {probabilityPct}%
          </div>
          <div className="text-xs text-neutral-500">probability</div>
        </div>
      </div>

      {/* Map */}
      <div className="h-[50vh] min-h-[400px] rounded border border-neutral-200 overflow-hidden">
        <ForecastDetailMap forecast={forecast} />
      </div>

      {/* Reasoning */}
      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500 mb-2">
          Reasoning
        </h2>
        <p className="text-neutral-800 leading-relaxed">
          {forecast.reasoning}
        </p>
      </section>

      {/* Validity */}
      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500 mb-2">
          Validity window
        </h2>
        <dl className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
          <div>
            <dt className="text-xs text-neutral-500">Issued</dt>
            <dd className="font-medium">{formatTime(forecast.issued_at)}</dd>
          </div>
          <div>
            <dt className="text-xs text-neutral-500">Valid from</dt>
            <dd className="font-medium">{formatTime(forecast.valid_from)}</dd>
          </div>
          <div>
            <dt className="text-xs text-neutral-500">Valid until</dt>
            <dd className="font-medium">{formatTime(forecast.valid_until)}</dd>
          </div>
        </dl>
      </section>

      {/* Contributing signals */}
      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500 mb-2">
          Contributing signals
          <span className="ml-2 text-xs font-normal text-neutral-400 normal-case tracking-normal">
            {signals.length} of {forecast.contributing_signal_ids?.length ?? 0}
            {signals.length <
              (forecast.contributing_signal_ids?.length ?? 0) && (
              <> &mdash; older ones may have been purged by retention</>
            )}
          </span>
        </h2>
        {signals.length === 0 ? (
          <p className="text-sm text-neutral-500 italic">
            No contributing signals available.
          </p>
        ) : (
          <ul className="divide-y divide-neutral-200 border border-neutral-200 rounded">
            {signals.map((s) => {
              const url = signalSourceUrl(s);
              return (
                <li key={s.id} className="px-4 py-3 text-sm">
                  <div className="flex items-baseline justify-between gap-3 flex-wrap">
                    <div>
                      <span className="font-medium">
                        {signalSourceLabel(s)}
                      </span>
                      <span className="text-neutral-500"> · {s.signal_type}</span>
                    </div>
                    <div className="text-xs text-neutral-500 tabular-nums">
                      {formatTime(s.timestamp)}
                    </div>
                  </div>
                  {url && (
                    <div className="mt-1">
                      <a
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-blue-600 hover:underline break-all"
                      >
                        {url} ↗
                      </a>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <div className="pt-4 border-t border-neutral-200 text-xs text-neutral-500">
        Source data:{' '}
        <a
          href="https://firms.modaps.eosdis.nasa.gov/"
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          NASA FIRMS
        </a>
        ,{' '}
        <a
          href="https://www.weather.gov/"
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          NWS
        </a>
        ,{' '}
        <a
          href="https://www.nhc.noaa.gov/"
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          NHC
        </a>
        . Produced by an automated experimental system —{' '}
        <Link href="/about" className="underline">
          read disclaimer
        </Link>
        .
      </div>
    </div>
  );
}
