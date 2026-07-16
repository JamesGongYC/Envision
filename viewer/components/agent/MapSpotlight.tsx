'use client';

import { useMap } from 'react-leaflet';
import { useEffect } from 'react';
import L from 'leaflet';

/** Fly/fit the Leaflet map to a GeoJSON envelope; no-op when geoFocus is null. */
export function MapSpotlight({
  geoFocus,
}: {
  geoFocus: GeoJSON.Geometry | null;
}) {
  const map = useMap();

  useEffect(() => {
    if (!geoFocus) return;
    try {
      const layer = L.geoJSON(geoFocus as GeoJSON.GeoJsonObject);
      const bounds = layer.getBounds();
      if (bounds.isValid()) {
        map.fitBounds(bounds.pad(0.2), { animate: true, maxZoom: 8 });
      }
    } catch {
      // ignore malformed geo_focus
    }
  }, [geoFocus, map]);

  return null;
}
