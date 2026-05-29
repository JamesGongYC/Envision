import Link from 'next/link';

export function DisclaimerBanner() {
  return (
    <div className="bg-amber-50 border-b border-amber-200 text-amber-900 text-xs">
      <div className="container mx-auto px-4 py-2">
        <strong>Experimental research artifact.</strong>{' '}
        Not an alerting service. Do not use for safety-critical decisions.{' '}
        For authoritative information see{' '}
        <a
          href="https://www.weather.gov"
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          weather.gov
        </a>
        ,{' '}
        <a
          href="https://www.nhc.noaa.gov"
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          nhc.noaa.gov
        </a>
        , or your local emergency management authority.{' '}
        <Link href="/about" className="underline">
          Read more
        </Link>
        .
      </div>
    </div>
  );
}
