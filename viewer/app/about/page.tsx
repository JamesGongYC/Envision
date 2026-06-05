export const metadata = {
  title: 'About — Envision',
};

export default function AboutPage() {
  return (
    <article className="container mx-auto px-4 py-12 max-w-prose prose prose-neutral">
      <h1 className="text-3xl font-semibold tracking-tight">About Envision</h1>

      <p className="mt-4 text-neutral-700">
        Envision is an experimental research artifact built to explore
        self-evolving agent architectures for disaster signal detection. It is{' '}
        <strong>not</strong> an alerting service and must <strong>not</strong>{' '}
        be used for safety-critical decisions. For authoritative information
        consult the U.S. National Weather Service (
        <a
          href="https://www.weather.gov"
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          weather.gov
        </a>
        ), the National Hurricane Center (
        <a
          href="https://www.nhc.noaa.gov"
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          nhc.noaa.gov
        </a>
        ), the Japan Meteorological Agency (
        <a
          href="https://www.jma.go.jp"
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          jma.go.jp
        </a>
        ), or your local emergency management authority. Forecasts published
        here are produced by an automated system with limited validation and
        known false-positive rates.
      </p>

      <h2 className="mt-10 text-xl font-semibold">Non-goals</h2>
      <ul className="mt-3 list-disc pl-6 text-neutral-700 space-y-1">
        <li>Envision does not replace official warning systems.</li>
        <li>Envision does not provide individual-location risk assessments.</li>
      </ul>

      <h2 className="mt-10 text-xl font-semibold">Scoring terms</h2>
      <ul className="mt-3 list-disc pl-6 text-neutral-700 space-y-2 text-sm">
        <li title="Brier score: a calibration metric for probabilistic forecasts. Lower is better.">
          <strong>Brier score</strong> — calibration metric for probabilistic forecasts. Lower is better.
        </li>
        <li title="Hit: forecast issued and a matching ground-truth event occurred within the validity window.">
          <strong>Hit</strong> — a forecast was issued and a matching
          ground-truth event occurred within the validity window.
        </li>
        <li title="False positive: forecast issued but no matching ground-truth event occurred within the validity window.">
          <strong>False positive</strong> — a forecast was issued but no
          matching ground-truth event occurred within the validity window.
        </li>
      </ul>

      <h2 className="mt-10 text-xl font-semibold">Self-evolution (v3)</h2>
      <p className="mt-3 text-neutral-700 text-sm leading-relaxed">
        Envision can propose and test changes to its own detection code.
        A change reaches the public map only after automated backtesting, a
        live shadow trial (invisible to this site), and explicit human
        approval. Self-evolution makes the experimental disclaimer above
        more important, not less — treat every forecast as unvalidated
        research output.
      </p>

      <h2 className="mt-10 text-xl font-semibold">Data sources</h2>
      <ul className="mt-3 list-disc pl-6 text-neutral-700 space-y-1">
        <li>
          <a
            href="https://firms.modaps.eosdis.nasa.gov/"
            className="underline"
            target="_blank"
            rel="noopener noreferrer"
          >
            NASA FIRMS
          </a>{' '}
          — active fire detections (MODIS + VIIRS)
        </li>
        <li>
          <a
            href="https://www.weather.gov/documentation/services-web-api"
            className="underline"
            target="_blank"
            rel="noopener noreferrer"
          >
            NWS Alerts API
          </a>{' '}
          — fire-weather watches and warnings
        </li>
        <li>
          <a
            href="https://www.nhc.noaa.gov/"
            className="underline"
            target="_blank"
            rel="noopener noreferrer"
          >
            NHC CurrentStorms.json
          </a>{' '}
          — Atlantic and East Pacific cyclone advisories
        </li>
        <li>
          <a
            href="https://www.gdacs.org/"
            className="underline"
            target="_blank"
            rel="noopener noreferrer"
          >
            GDACS
          </a>{' '}
          — global disaster ground-truth (evaluator only)
        </li>
        <li>
          <a
            href="https://www.geonames.org/"
            className="underline"
            target="_blank"
            rel="noopener noreferrer"
          >
            GeoNames cities5000
          </a>{' '}
          — populated places for landfall detection
        </li>
      </ul>
    </article>
  );
}
