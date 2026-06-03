import ForecastMap from '@/components/forecast-map';
import { Hero } from '@/components/hero';
import { LandingSnapShell } from '@/components/landing-snap-shell';
import { MapControlsBar } from '@/components/map-controls-bar';
import { FORECASTS_MAP_ID } from '@/lib/landing-scroll';
import { getActiveForecasts } from '@/lib/queries';

export const revalidate = 60;

export default async function HomePage() {
  const forecasts = await getActiveForecasts();

  const wildfireCount = forecasts.filter(
    (f) => f.disaster_class === 'wildfire'
  ).length;
  const typhoonCount = forecasts.filter(
    (f) => f.disaster_class === 'typhoon'
  ).length;

  return (
    <LandingSnapShell>
      <Hero />
      <section
        id={FORECASTS_MAP_ID}
        className="landing-snap-pane flex flex-col px-4 py-3 gap-3 min-h-0 overflow-visible"
        aria-label="Forecasts map"
      >
        <MapControlsBar
          forecastCount={forecasts.length}
          wildfireCount={wildfireCount}
          typhoonCount={typhoonCount}
        />
        <div className="flex-1 h-0 min-h-[12rem] rounded-lg border border-[var(--border)] overflow-hidden bg-[var(--surface)]">
          <ForecastMap forecasts={forecasts} height="100%" />
        </div>
      </section>
    </LandingSnapShell>
  );
}
