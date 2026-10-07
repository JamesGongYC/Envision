'use client';

import { useMemo } from 'react';
import { MapContainer, TileLayer, GeoJSON } from 'react-leaflet';
import { cartoTileUrl, CARTO_ATTRIBUTION } from '@/lib/basemap';
import type { LatLngBoundsLiteral } from 'leaflet';
import type { Forecast } from '@/lib/types';

const CLASS_STYLES = {
  wildfire: { stroke: '#dc2626', fill: '#fca5a5' },
  typhoon: { stroke: '#2563eb', fill: '#93c5fd' },
} as const;

/**
 * Compute a [[south, west], [north, east]] bounding box from any
 * GeoJSON geometry by recursively walking the coordinates. Returns
 * null if the geometry is empty or unrecognized.
 */
function computeBounds(
  geometry: GeoJSON.Geometry
): LatLngBoundsLiteral | null {
  let minLat = Infinity,
    minLng = Infinity,
    maxLat = -Infinity,
    maxLng = -Infinity;

  function walk(coords: unknown): void {
    if (!Array.isArray(coords)) return;
    if (typeof coords[0] === 'number' && typeof coords[1] === 'number') {
      const [lng, lat] = coords as [number, number];
      if (lng < minLng) minLng = lng;
      if (lng > maxLng) maxLng = lng;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
      return;
    }
    for (const c of coords) walk(c);
  }

  if ('coordinates' in geometry) {
    walk(geometry.coordinates);
  }

  if (!isFinite(minLat)) return null;
  return [
    [minLat, minLng],
    [maxLat, maxLng],
  ];
}

export default function ForecastDetailMapImpl({
  forecast,
}: {
  forecast: Forecast;
}) {
  const bounds = useMemo(
    () => computeBounds(forecast.geometry),
    [forecast.geometry]
  );

  const style = CLASS_STYLES[forecast.disaster_class];
  const fillOpacity = Math.max(
    0.25,
    Math.min(0.65, forecast.probability * 0.75)
  );

  return (
    <MapContainer
      bounds={bounds ?? undefined}
      boundsOptions={{ padding: [30, 30] }}
      center={bounds ? undefined : [20, 0]}
      zoom={bounds ? undefined : 2}
      scrollWheelZoom
      style={{ height: '100%', width: '100%' }}
    >
      <TileLayer
        attribution={CARTO_ATTRIBUTION}
        url={cartoTileUrl('light_all')}
        subdomains="abcd"
        maxZoom={19}
      />
      <GeoJSON
        data={forecast.geometry as GeoJSON.GeoJsonObject}
        style={() => ({
          color: style.stroke,
          fillColor: style.fill,
          fillOpacity,
          weight: 2,
          opacity: 0.9,
        })}
      />
    </MapContainer>
  );
}
