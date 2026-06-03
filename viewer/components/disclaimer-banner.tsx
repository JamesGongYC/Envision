import Link from 'next/link';

export function DisclaimerBanner() {
  return (
    <div className="bg-[var(--surface)] border-b border-[var(--border)] text-[var(--muted)] text-xs shrink-0">
      <div className="container mx-auto px-4 py-1.5 font-[family-name:var(--font-mono)]">
        <strong className="text-[var(--foreground)]">Experimental research artifact.</strong>{' '}
        Not an alerting service. Do not use for safety-critical decisions.{' '}
        For authoritative information see{' '}
        <a
          href="https://www.weather.gov"
          target="_blank"
          rel="noopener noreferrer"
          className="underline text-[var(--foreground)]"
        >
          weather.gov
        </a>
        ,{' '}
        <a
          href="https://www.nhc.noaa.gov"
          target="_blank"
          rel="noopener noreferrer"
          className="underline text-[var(--foreground)]"
        >
          nhc.noaa.gov
        </a>
        , or your local emergency management authority.{' '}
        <Link href="/disclaimer" className="underline text-[var(--foreground)]">
          Read more
        </Link>
        .
      </div>
    </div>
  );
}
