export const metadata = {
  title: 'Disclaimer',
};

export default function DisclaimerPage() {
  return (
    <article className="container mx-auto px-4 py-12 max-w-prose font-[family-name:var(--font-mono)]">
      <h1 className="font-[family-name:var(--font-display)] text-3xl font-bold tracking-tight text-[var(--foreground)] mb-6">
        Disclaimer
      </h1>

      <p className="text-sm text-[var(--muted)] leading-relaxed">
        Envision is an experimental research artifact built to explore
        self-evolving agent architectures for disaster signal detection. It is{' '}
        <strong className="text-[var(--foreground)]">not</strong> an alerting
        service and must <strong className="text-[var(--foreground)]">not</strong>{' '}
        be used for safety-critical decisions. For authoritative information
        consult the U.S. National Weather Service (
        <a
          href="https://www.weather.gov"
          target="_blank"
          rel="noopener noreferrer"
          className="underline text-[var(--foreground)]"
        >
          weather.gov
        </a>
        ), the National Hurricane Center (
        <a
          href="https://www.nhc.noaa.gov"
          target="_blank"
          rel="noopener noreferrer"
          className="underline text-[var(--foreground)]"
        >
          nhc.noaa.gov
        </a>
        ), the Japan Meteorological Agency (
        <a
          href="https://www.jma.go.jp"
          target="_blank"
          rel="noopener noreferrer"
          className="underline text-[var(--foreground)]"
        >
          jma.go.jp
        </a>
        ), or your local emergency management authority. Forecasts published
        here are produced by an automated system with limited validation and
        known false-positive rates.
      </p>

      <h2 className="mt-10 text-lg font-[family-name:var(--font-display)] font-bold text-[var(--foreground)]">
        Non-goals
      </h2>
      <ul className="mt-3 list-disc pl-6 text-sm text-[var(--muted)] space-y-1">
        <li>Envision does not replace official warning systems.</li>
        <li>Envision does not provide individual-location risk assessments.</li>
      </ul>
    </article>
  );
}
