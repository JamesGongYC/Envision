'use client';

import dynamic from 'next/dynamic';
import type { Forecast } from '@/lib/types';

// Leaflet touches `window` at import time, so the actual implementation
// must never be evaluated on the server. We isolate it behind a dynamic
// import with ssr:false. This wrapper is the only file that's
// directly imported from the server component.
const ForecastMapImpl = dynamic(() => import('./forecast-map-impl'), {
  ssr: false,
  loading: () => (
    <div className="h-full w-full flex items-center justify-center bg-neutral-50">
      <p className="text-sm text-neutral-500">Loading map…</p>
    </div>
  ),
});

export default function ForecastMap({ forecasts }: { forecasts: Forecast[] }) {
  return <ForecastMapImpl forecasts={forecasts} />;
}
