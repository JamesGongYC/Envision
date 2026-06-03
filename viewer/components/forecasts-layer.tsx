'use client';

import L from 'leaflet';
import { GeoJSON, CircleMarker } from 'react-leaflet';
import type { Forecast } from '@/lib/types';

const FORECASTS_PANE = 'forecastsPane';

const CLASS_STYLES = {
  wildfire: { stroke: '#dc2626', fill: '#fca5a5' },
  typhoon: { stroke: '#2563eb', fill: '#93c5fd' },
} as const;

function geometryCentroid(
  geom: GeoJSON.Geometry
): [number, number] | null {
  let ring: GeoJSON.Position[] | null = null;

  if (geom.type === 'Polygon' && geom.coordinates[0]) {
    ring = geom.coordinates[0];
  } else if (
    geom.type === 'MultiPolygon' &&
    geom.coordinates[0]?.[0]
  ) {
    ring = geom.coordinates[0][0];
  } else if (geom.type === 'Point') {
    const [lon, lat] = geom.coordinates;
    return [lat, lon];
  }

  if (!ring || ring.length === 0) return null;

  let sumLon = 0;
  let sumLat = 0;
  for (const [lon, lat] of ring) {
    sumLon += lon;
    sumLat += lat;
  }
  return [sumLat / ring.length, sumLon / ring.length];
}

/** Active forecast polygons and centroid markers (click → floating popover). */
export function ForecastsLayer({
  forecasts,
  onForecastSelect,
}: {
  forecasts: Forecast[];
  onForecastSelect: (forecast: Forecast, latLng: L.LatLng) => void;
}) {
  return (
    <>
      {forecasts.map((f) => {
        const style = CLASS_STYLES[f.disaster_class];
        const fillOpacity = Math.max(
          0.2,
          Math.min(0.65, f.probability * 0.75)
        );
        return (
          <GeoJSON
            key={`${f.id}-poly`}
            data={f.geometry as GeoJSON.GeoJsonObject}
            pane={FORECASTS_PANE}
            style={() => ({
              color: style.stroke,
              fillColor: style.fill,
              fillOpacity,
              weight: 1.5,
              opacity: 0.85,
            })}
          />
        );
      })}

      {forecasts.map((f) => {
        const center = geometryCentroid(f.geometry);
        if (!center) return null;
        const style = CLASS_STYLES[f.disaster_class];
        const latLng = L.latLng(center[0], center[1]);
        return (
          <CircleMarker
            key={`${f.id}-marker`}
            center={center}
            radius={7}
            pane={FORECASTS_PANE}
            pathOptions={{
              color: style.stroke,
              fillColor: style.fill,
              fillOpacity: 0.9,
              weight: 2.5,
              opacity: 1,
            }}
            eventHandlers={{
              click: (e) => {
                L.DomEvent.stopPropagation(e);
                onForecastSelect(f, latLng);
              },
            }}
          />
        );
      })}
    </>
  );
}
