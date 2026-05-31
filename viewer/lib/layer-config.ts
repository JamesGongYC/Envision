import type { LayerId } from '@/lib/layer-state';

export type BBox = {
  west: number;
  south: number;
  east: number;
  north: number;
};

export type LayerQueryTarget = 'signals' | 'ground_truth';

export type LayerQueryConfig = {
  layerId: LayerId;
  target: LayerQueryTarget;
  sources: string[];
  signalType?: string;
  /** Canvas renderer for high-density point layers (FIRMS). */
  useCanvas?: boolean;
  label: string;
};

export const LAYER_QUERY_CONFIG: Record<LayerId, LayerQueryConfig | null> = {
  forecasts: null,
  aifs_wind_field: null,
  firms_hotspots: {
    layerId: 'firms_hotspots',
    target: 'signals',
    sources: ['firms_viirs', 'firms_modis'],
    signalType: 'hotspot',
    useCanvas: true,
    label: 'FIRMS hotspots',
  },
  nws_fire_alerts: {
    layerId: 'nws_fire_alerts',
    target: 'signals',
    sources: ['nws_alerts'],
    signalType: 'fire_warning',
    label: 'NWS fire alerts',
  },
  open_meteo_fire_weather: {
    layerId: 'open_meteo_fire_weather',
    target: 'signals',
    sources: ['open_meteo'],
    signalType: 'fire_weather',
    label: 'Open-Meteo fire weather',
  },
  ecmwf_fire_weather_grid: {
    layerId: 'ecmwf_fire_weather_grid',
    target: 'signals',
    sources: ['ecmwf_open_data'],
    signalType: 'fire_weather_grid',
    label: 'ECMWF fire weather grid',
  },
  aifs_fire_weather_grid: {
    layerId: 'aifs_fire_weather_grid',
    target: 'signals',
    sources: ['aifs'],
    signalType: 'fire_weather_grid',
    label: 'AIFS fire weather grid',
  },
  nhc_advisories: {
    layerId: 'nhc_advisories',
    target: 'signals',
    sources: ['nhc'],
    signalType: 'cyclone_advisory',
    label: 'NHC advisories',
  },
  jtwc_advisories: {
    layerId: 'jtwc_advisories',
    target: 'signals',
    sources: ['jtwc'],
    signalType: 'cyclone_advisory',
    label: 'JTWC advisories',
  },
  aifs_cyclone_features: {
    layerId: 'aifs_cyclone_features',
    target: 'signals',
    sources: ['aifs'],
    signalType: 'cyclone_feature',
    label: 'AIFS cyclone features',
  },
  aifs_high_wind: {
    layerId: 'aifs_high_wind',
    target: 'signals',
    sources: ['aifs'],
    signalType: 'high_wind_corridor',
    label: 'AIFS high wind',
  },
  aifs_heavy_precipitation: {
    layerId: 'aifs_heavy_precipitation',
    target: 'signals',
    sources: ['aifs'],
    signalType: 'heavy_precipitation_band',
    label: 'AIFS heavy precipitation',
  },
  gdacs_ground_truth: {
    layerId: 'gdacs_ground_truth',
    target: 'ground_truth',
    sources: ['gdacs'],
    label: 'GDACS events',
  },
};

export function getLayerQueryConfig(
  layerId: string
): LayerQueryConfig | null {
  return LAYER_QUERY_CONFIG[layerId as LayerId] ?? null;
}

export function parseBBoxParam(raw: string | null): BBox | null {
  if (!raw) return null;
  const parts = raw.split(',').map((s) => Number.parseFloat(s.trim()));
  if (parts.length !== 4 || parts.some((n) => !Number.isFinite(n))) return null;
  const [west, south, east, north] = parts;
  return { west, south, east, north };
}
