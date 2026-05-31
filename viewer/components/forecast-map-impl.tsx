'use client';

import { MapContainer, TileLayer } from 'react-leaflet';
import type { Forecast } from '@/lib/types';
import { LAYER_QUERY_CONFIG } from '@/lib/layer-config';
import type { LayerId } from '@/lib/layer-state';
import { useLayerVisibility } from '@/components/layer-visibility-provider';
import { ForecastsLayer } from '@/components/forecasts-layer';
import { GroundTruthLayer } from '@/components/ground-truth-layer';
import { MapPanes } from '@/components/map-panes';
import { SignalLayer } from '@/components/signal-layer';
import { PolygonSignalLayer } from '@/components/polygon-signal-layer';
import { WindLayer } from '@/components/wind-layer';

const SIGNAL_LAYER_IDS: LayerId[] = [
  'firms_hotspots',
  'nws_fire_alerts',
  'open_meteo_fire_weather',
  'nhc_advisories',
  'jtwc_advisories',
  'aifs_cyclone_features',
  'gdacs_ground_truth',
];

const POLYGON_LAYER_IDS: LayerId[] = [
  'ecmwf_fire_weather_grid',
  'aifs_fire_weather_grid',
  'aifs_high_wind',
  'aifs_heavy_precipitation',
];

function ActiveSignalLayers() {
  const { visibility } = useLayerVisibility();

  return (
    <>
      {SIGNAL_LAYER_IDS.map((layerId) => {
        if (!visibility[layerId]) return null;
        const config = LAYER_QUERY_CONFIG[layerId];
        if (!config) return null;
        if (config.target === 'ground_truth') {
          return <GroundTruthLayer key={layerId} config={config} />;
        }
        return <SignalLayer key={layerId} config={config} />;
      })}
    </>
  );
}

function ActivePolygonLayers() {
  const { visibility } = useLayerVisibility();

  return (
    <>
      {POLYGON_LAYER_IDS.map((layerId) => {
        if (!visibility[layerId]) return null;
        const config = LAYER_QUERY_CONFIG[layerId];
        if (!config) return null;
        return <PolygonSignalLayer key={layerId} config={config} />;
      })}
    </>
  );
}

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

      <MapPanes />
      {visibility.aifs_wind_field && <WindLayer />}
      <ActiveSignalLayers />
      <ActivePolygonLayers />
      {visibility.forecasts && <ForecastsLayer forecasts={forecasts} />}
    </MapContainer>
  );
}
