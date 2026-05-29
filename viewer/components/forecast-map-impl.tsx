'use client';

import { MapContainer, TileLayer, GeoJSON, Popup } from 'react-leaflet';
import Link from 'next/link';
import type { Forecast } from '@/lib/types';

const CLASS_STYLES = {
  wildfire: { stroke: '#dc2626', fill: '#fca5a5' }, // red-600 / red-300
  typhoon: { stroke: '#2563eb', fill: '#93c5fd' }, // blue-600 / blue-300
} as const;

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  });
}

export default function ForecastMapImpl({
  forecasts,
}: {
  forecasts: Forecast[];
}) {
  return (
    <MapContainer
      center={[20, 0]}
      zoom={2}
      minZoom={2}
      worldCopyJump
      scrollWheelZoom
      style={{ height: '100%', width: '100%' }}
    >
      {/* CartoDB Positron — light, neutral, globally accessible (including from
          regions where tile.openstreetmap.org is unreliable). Free, no API key. */}
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener">CARTO</a>'
        url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        subdomains="abcd"
        maxZoom={19}
      />

      {forecasts.map((f) => {
        const style = CLASS_STYLES[f.disaster_class];
        const fillOpacity = Math.max(0.2, Math.min(0.65, f.probability * 0.75));

        return (
          <GeoJSON
            key={f.id}
            data={f.geometry as GeoJSON.GeoJsonObject}
            style={() => ({
              color: style.stroke,
              fillColor: style.fill,
              fillOpacity,
              weight: 1.5,
              opacity: 0.85,
            })}
          >
            <Popup>
              <div className="text-sm space-y-1.5 min-w-[220px]">
                <div className="flex items-center justify-between gap-2">
                  <span
                    className={`inline-block px-1.5 py-0.5 rounded text-xs font-medium ${
                      f.disaster_class === 'wildfire'
                        ? 'bg-red-100 text-red-700'
                        : 'bg-blue-100 text-blue-700'
                    }`}
                  >
                    {f.disaster_class}
                  </span>
                  <span className="text-xs text-neutral-600">
                    {(f.probability * 100).toFixed(0)}% probability
                  </span>
                </div>

                <p className="text-xs text-neutral-700 leading-snug">
                  {f.reasoning}
                </p>

                <div className="text-[11px] text-neutral-500 pt-1.5 border-t border-neutral-200">
                  <div>
                    <span className="text-neutral-400">Skill:</span>{' '}
                    <code className="text-[10px]">{f.skill_id}</code> v
                    {f.skill_version}
                  </div>
                  <div>
                    <span className="text-neutral-400">Valid:</span>{' '}
                    {formatTime(f.valid_from)} → {formatTime(f.valid_until)}
                  </div>
                </div>

                <Link
                  href={`/forecast/${f.id}`}
                  className="inline-block text-xs text-blue-600 hover:underline pt-0.5"
                >
                  Details →
                </Link>
              </div>
            </Popup>
          </GeoJSON>
        );
      })}
    </MapContainer>
  );
}
