'use client';

import { MapContainer, TileLayer } from 'react-leaflet';
import type { Forecast } from '@/lib/types';
import { useLayerVisibility } from '@/components/layer-visibility-provider';
import { ForecastsLayer } from '@/components/forecasts-layer';

// Day 2+: FIRMSHotspotsLayer, NwsFireAlertsLayer, GdacsGroundTruthLayer, etc.

export default function ForecastMapImpl({
  forecasts,
}: {
  forecasts: Forecast[];
}) {
  const { visibility } = useLayerVisibility();

  return (
    <MapContainer
      center={[20, 0]}
      zoom={2}
      minZoom={2}
      worldCopyJump
      scrollWheelZoom
      style={{ height: '100%', width: '100%' }}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener">CARTO</a>'
        url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        subdomains="abcd"
        maxZoom={19}
      />

      {visibility.forecasts && <ForecastsLayer forecasts={forecasts} />}
    </MapContainer>
  );
}
