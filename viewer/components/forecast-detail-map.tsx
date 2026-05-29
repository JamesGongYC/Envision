'use client';

import dynamic from 'next/dynamic';
import type { Forecast } from '@/lib/types';

const ForecastDetailMapImpl = dynamic(
  () => import('./forecast-detail-map-impl'),
  {
    ssr: false,
    loading: () => (
      <div className="h-full w-full flex items-center justify-center bg-neutral-50">
        <p className="text-sm text-neutral-500">Loading map…</p>
      </div>
    ),
  }
);

export default function ForecastDetailMap({
  forecast,
}: {
  forecast: Forecast;
}) {
  return <ForecastDetailMapImpl forecast={forecast} />;
}
