'use client';

import { useEffect, useMemo, useState } from 'react';
import type { LatLng } from 'leaflet';
import { MapContainer, TileLayer, useMap, useMapEvents } from 'react-leaflet';
import type { AgentEmitCandidate, Forecast } from '@/lib/types';
import { LAYER_QUERY_CONFIG } from '@/lib/layer-config';
import type { LayerId } from '@/lib/layer-state';
import { useLayerVisibility } from '@/components/layer-visibility-provider';
import { ForecastMapPopover } from '@/components/forecast-map-popover';
import { ForecastsLayer } from '@/components/forecasts-layer';
import { GroundTruthLayer } from '@/components/ground-truth-layer';
import { MapPanes } from '@/components/map-panes';
import { SignalLayer } from '@/components/signal-layer';
import { PolygonSignalLayer } from '@/components/polygon-signal-layer';
import { WindLayer } from '@/components/wind-layer';
import { MapSpotlight } from '@/components/agent/MapSpotlight';
import { AgentCandidatePopups } from '@/components/agent/AgentCandidatePopups';

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

function LayerPulsePanes({ pulsing }: { pulsing: Set<LayerId> }) {
  const map = useMap();

  useEffect(() => {
    const signalsPane = map.getPane('signalsPane');
    const polygonsPane = map.getPane('polygonsPane');
    const pulseSignals = SIGNAL_LAYER_IDS.some((id) => pulsing.has(id));
    const pulsePolygons = POLYGON_LAYER_IDS.some((id) => pulsing.has(id));
    signalsPane?.classList.toggle('envision-layer-pulse', pulseSignals);
    polygonsPane?.classList.toggle('envision-layer-pulse', pulsePolygons);
    return () => {
      signalsPane?.classList.remove('envision-layer-pulse');
      polygonsPane?.classList.remove('envision-layer-pulse');
    };
  }, [map, pulsing]);

  return null;
}

function MapInvalidateSize() {
  const map = useMap();

  useEffect(() => {
    const invalidate = () => {
      map.invalidateSize();
    };

    invalidate();
    const t = window.setTimeout(invalidate, 100);

    const container = map.getContainer();
    const ro = new ResizeObserver(() => {
      invalidate();
    });
    ro.observe(container);
    window.addEventListener('resize', invalidate);

    return () => {
      window.clearTimeout(t);
      ro.disconnect();
      window.removeEventListener('resize', invalidate);
    };
  }, [map]);

  return null;
}

function ActiveSignalLayers({ pulsing }: { pulsing: Set<LayerId> }) {
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
        return (
          <SignalLayer
            key={layerId}
            config={config}
            pulsing={pulsing.has(layerId)}
          />
        );
      })}
    </>
  );
}

function ActivePolygonLayers({ pulsing }: { pulsing: Set<LayerId> }) {
  const { visibility } = useLayerVisibility();

  return (
    <>
      {POLYGON_LAYER_IDS.map((layerId) => {
        if (!visibility[layerId]) return null;
        const config = LAYER_QUERY_CONFIG[layerId];
        if (!config) return null;
        return (
          <PolygonSignalLayer
            key={layerId}
            config={config}
            pulsing={pulsing.has(layerId)}
          />
        );
      })}
    </>
  );
}

type SelectedForecast = { forecast: Forecast; latLng: LatLng };

function ForecastMapOverlays({ forecasts }: { forecasts: Forecast[] }) {
  const { visibility } = useLayerVisibility();
  const [selected, setSelected] = useState<SelectedForecast | null>(null);

  useMapEvents({
    click() {
      setSelected(null);
    },
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelected(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <>
      {visibility.forecasts && (
        <ForecastsLayer
          forecasts={forecasts}
          onForecastSelect={(forecast, latLng) =>
            setSelected({ forecast, latLng })
          }
        />
      )}
      {selected && (
        <ForecastMapPopover
          forecast={selected.forecast}
          latLng={selected.latLng}
        />
      )}
    </>
  );
}

export default function ForecastMapImpl({
  forecasts,
  geoFocus = null,
  pulsingLayers = [],
  candidates = [],
}: {
  forecasts: Forecast[];
  geoFocus?: GeoJSON.Geometry | null;
  pulsingLayers?: LayerId[];
  candidates?: AgentEmitCandidate[];
}) {
  const { visibility } = useLayerVisibility();
  const pulsing = useMemo(() => new Set(pulsingLayers), [pulsingLayers]);

  return (
    <MapContainer
      center={[20, 0]}
      zoom={2}
      minZoom={2}
      worldCopyJump
      scrollWheelZoom
      style={{ height: '100%', width: '100%' }}
    >
      <MapInvalidateSize />
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener">CARTO</a>'
        url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        subdomains="abcd"
        maxZoom={19}
      />

      <MapPanes />
      <LayerPulsePanes pulsing={pulsing} />
      <MapSpotlight geoFocus={geoFocus} />
      {visibility.aifs_wind_field && <WindLayer />}
      <ActiveSignalLayers pulsing={pulsing} />
      <ActivePolygonLayers pulsing={pulsing} />
      <ForecastMapOverlays forecasts={forecasts} />
      <AgentCandidatePopups candidates={candidates} />
    </MapContainer>
  );
}
