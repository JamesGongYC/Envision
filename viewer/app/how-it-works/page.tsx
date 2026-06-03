import { PipelineFigure } from '@/components/how-it-works/pipeline-figure';
import type { PipelinePanelData } from '@/components/how-it-works/pipeline-figure';
import {
  getActiveSkillCount,
  getLastCuratorActivity,
  getLastIngestionTimestamp,
} from '@/lib/agent-queries';
import { curatorStatusLabel } from '@/lib/curator-status';
import { formatTimeAgo } from '@/lib/time-ago';

export const revalidate = 60;

export const metadata = {
  title: 'How it works',
};

const DATA_SOURCES = (
  <ul className="list-disc pl-5 space-y-2 text-xs">
    <li>
      <a
        href="https://firms.modaps.eosdis.nasa.gov/"
        className="underline text-[var(--foreground)]"
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
        className="underline text-[var(--foreground)]"
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
        className="underline text-[var(--foreground)]"
        target="_blank"
        rel="noopener noreferrer"
      >
        NHC CurrentStorms.json
      </a>{' '}
      — Atlantic and East Pacific cyclone advisories
    </li>
    <li>
      <a
        href="https://www.metoc.navy.mil/jtwc/"
        className="underline text-[var(--foreground)]"
        target="_blank"
        rel="noopener noreferrer"
      >
        JTWC
      </a>{' '}
      — Western Pacific cyclone advisories
    </li>
    <li>
      <a
        href="https://open-meteo.com/"
        className="underline text-[var(--foreground)]"
        target="_blank"
        rel="noopener noreferrer"
      >
        Open-Meteo
      </a>{' '}
      — fire-weather indices
    </li>
    <li>
      <a
        href="https://www.ecmwf.int/en/forecasts/datasets/open-data"
        className="underline text-[var(--foreground)]"
        target="_blank"
        rel="noopener noreferrer"
      >
        ECMWF Open Data
      </a>{' '}
      — fire-weather grids
    </li>
    <li>
      <a
        href="https://www.ecmwf.int/en/about/media-centre/news/2024/aifs-our-new-ml-model"
        className="underline text-[var(--foreground)]"
        target="_blank"
        rel="noopener noreferrer"
      >
        AIFS (ECMWF)
      </a>{' '}
      — AI forecast grids and derived features
    </li>
    <li>
      <a
        href="https://www.gdacs.org/"
        className="underline text-[var(--foreground)]"
        target="_blank"
        rel="noopener noreferrer"
      >
        GDACS
      </a>{' '}
      — global disaster ground truth (evaluator only)
    </li>
    <li>
      <a
        href="https://www.geonames.org/"
        className="underline text-[var(--foreground)]"
        target="_blank"
        rel="noopener noreferrer"
      >
        GeoNames cities5000
      </a>{' '}
      — populated places for landfall detection
    </li>
  </ul>
);

export default async function HowItWorksPage() {
  const [lastIngestion, skillsActive, lastCurator] = await Promise.all([
    getLastIngestionTimestamp(),
    getActiveSkillCount(),
    getLastCuratorActivity(),
  ]);

  const panels: PipelinePanelData[] = [
    {
      id: 'ingest',
      title: 'Ingest',
      summary:
        'Pulls public hazard feeds on cadences from 30 minutes to 12 hours.',
      telemetry: `Last ingestion: ${formatTimeAgo(lastIngestion)}`,
      detail: (
        <>
          <p>
            The Ingest layer is responsible for collecting observations from
            FIRMS, NWS, NHC, JTWC, Open-Meteo, ECMWF, and AIFS; every 30
            minutes to 12 hours (per source), it normalizes payloads into the{' '}
            <code>signals</code> table and retains GDACS ground truth for
            scoring.
          </p>
          <div>
            <p className="text-[var(--foreground)] font-medium mb-2">
              Data sources & attribution
            </p>
            {DATA_SOURCES}
          </div>
        </>
      ),
    },
    {
      id: 'forecast',
      title: 'Forecast',
      summary:
        'Detection skills read signals and emit capped probabilistic forecasts.',
      telemetry: `${skillsActive} skill${skillsActive === 1 ? '' : 's'} active (24h)`,
      detail: (
        <p>
          The Forecast layer is responsible for running detection skills on
          each skill cadence; every cycle, it clusters and interprets signals,
          writes probabilistic forecasts (capped at 0.85), and attaches LLM
          reasoning for the map.
        </p>
      ),
    },
    {
      id: 'evolve',
      title: 'Evolve',
      summary:
        'Daily curator proposes code changes; promotion is operator-gated.',
      telemetry: curatorStatusLabel(lastCurator),
      detail: (
        <p>
          The Evolve layer is responsible for improving the skill library; every
          24 hours, it reads live Brier scores, mutates skill code, backtests
          candidates, shadow-evaluates on live traffic, and queues proposals for
          human review before anything reaches the public map.
        </p>
      ),
    },
  ];

  return (
    <div className="container mx-auto px-4 py-12 max-w-5xl space-y-8">
      <header>
        <h1 className="font-[family-name:var(--font-display)] text-3xl font-bold tracking-tight">
          How it works
        </h1>
        <p className="mt-3 font-[family-name:var(--font-mono)] text-sm text-[var(--muted)] max-w-2xl">
          Three layers — ingest observations, forecast risk, evolve the skill
          library.
        </p>
      </header>
      <PipelineFigure panels={panels} />
    </div>
  );
}
