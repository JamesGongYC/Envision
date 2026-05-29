import ForecastMap from '@/components/forecast-map';
import { getActiveForecasts } from '@/lib/queries';

export const revalidate = 60;

// 5.5rem accounts for the disclaimer banner (~2rem) plus the header nav
// (~3.5rem). Explicit viewport units sidestep the cascading-percentage
// height problem that breaks Leaflet's mount-time clientHeight measurement.
const MAP_HEIGHT = 'calc(100dvh - 5.5rem)';

export default async function HomePage() {
  const forecasts = await getActiveForecasts();

  const wildfireCount = forecasts.filter(
    (f) => f.disaster_class === 'wildfire'
  ).length;
  const typhoonCount = forecasts.filter(
    (f) => f.disaster_class === 'typhoon'
  ).length;

  return (
    <div className="relative" style={{ height: MAP_HEIGHT }}>
      <ForecastMap forecasts={forecasts} />

      {/* Status badge — top-left */}
      <div className="absolute top-4 left-4 z-[400] bg-white/95 backdrop-blur px-3 py-2 rounded shadow-sm border border-neutral-200 text-xs">
        <div className="font-medium text-neutral-900">
          {forecasts.length} active forecast{forecasts.length === 1 ? '' : 's'}
        </div>
        {forecasts.length > 0 && (
          <div className="text-neutral-500 mt-0.5">
            {wildfireCount} wildfire · {typhoonCount} typhoon
          </div>
        )}
        {forecasts.length === 0 && (
          <div className="text-neutral-500 mt-0.5 max-w-[16rem]">
            No active forecasts right now. Detectors may still be warming up,
            or no events meet detection thresholds.
          </div>
        )}
      </div>

      {/* Legend — top-right */}
      <div className="absolute top-4 right-4 z-[400] bg-white/95 backdrop-blur px-3 py-2 rounded shadow-sm border border-neutral-200 text-xs space-y-1">
        <div className="flex items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded-sm border-2 border-red-600 bg-red-300/70" />
          <span>Wildfire</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded-sm border-2 border-blue-600 bg-blue-300/70" />
          <span>Typhoon</span>
        </div>
        <div className="text-neutral-500 pt-1 mt-1 border-t border-neutral-200">
          Opacity ∝ probability
        </div>
      </div>
    </div>
  );
}
