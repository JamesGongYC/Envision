'use client';

import dynamic from 'next/dynamic';
import type { Forecast } from '@/lib/types';

const ForecastMapImpl = dynamic(() => import('./forecast-map-impl'), {
  ssr: false,
  loading: () => (
    <div className="h-full w-full flex items-center justify-center bg-[var(--background)]">
      <p className="text-sm text-[var(--muted)] font-[family-name:var(--font-mono)]">
        Loading map…
      </p>
    </div>
  ),
});

export default function ForecastMap({
  forecasts,
  height,
}: {
  forecasts: Forecast[];
  height: string;
}) {
  return (
    <div className="h-full w-full" style={{ height, minHeight: 192 }}>
      <ForecastMapImpl forecasts={forecasts} />
    </div>
  );
}
