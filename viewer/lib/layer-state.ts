/** Granular layer ids used by map components and /api/signals. */
export type LayerId =
  | 'forecasts'
  | 'aifs_wind_field'
  | 'firms_hotspots'
  | 'nws_fire_alerts'
  | 'open_meteo_fire_weather'
  | 'ecmwf_fire_weather_grid'
  | 'aifs_fire_weather_grid'
  | 'nhc_advisories'
  | 'jtwc_advisories'
  | 'aifs_cyclone_features'
  | 'aifs_high_wind'
  | 'aifs_heavy_precipitation'
  | 'gdacs_ground_truth';

export type LayerVisibility = Record<LayerId, boolean>;

/** UI map layer toggles (v3.1 Option C). */
export type MapLayerToggle = 'forecasts' | 'signals' | 'model_signals';

export type MapLayerVisibility = Record<MapLayerToggle, boolean>;

export const ALL_LAYER_IDS: LayerId[] = [
  'forecasts',
  'aifs_wind_field',
  'firms_hotspots',
  'nws_fire_alerts',
  'open_meteo_fire_weather',
  'ecmwf_fire_weather_grid',
  'aifs_fire_weather_grid',
  'nhc_advisories',
  'jtwc_advisories',
  'aifs_cyclone_features',
  'aifs_high_wind',
  'aifs_heavy_precipitation',
  'gdacs_ground_truth',
];

export const DETECTION_LAYER_IDS: LayerId[] = [
  'firms_hotspots',
  'nws_fire_alerts',
  'open_meteo_fire_weather',
  'ecmwf_fire_weather_grid',
  'aifs_fire_weather_grid',
  'nhc_advisories',
  'jtwc_advisories',
  'aifs_cyclone_features',
  'aifs_high_wind',
  'aifs_heavy_precipitation',
  'gdacs_ground_truth',
];

export const DEFAULT_UI_VISIBILITY: MapLayerVisibility = {
  forecasts: true,
  signals: true,
  model_signals: false,
};

export const DEFAULT_GRANULAR_VISIBILITY: LayerVisibility = expandVisibility(
  DEFAULT_UI_VISIBILITY
);

export const STORAGE_KEY = 'envision.layers.v31';

export type LayerTreeLeaf = {
  id: MapLayerToggle;
  label: string;
};

export const LAYER_TREE: LayerTreeLeaf[] = [
  { id: 'forecasts', label: 'Forecasts' },
  { id: 'signals', label: 'Signals' },
  { id: 'model_signals', label: 'Model Signals' },
];

export function expandVisibility(ui: MapLayerVisibility): LayerVisibility {
  const on = (ids: LayerId[]) =>
    Object.fromEntries(ids.map((id) => [id, true])) as Partial<LayerVisibility>;

  return {
    forecasts: false,
    aifs_wind_field: false,
    firms_hotspots: false,
    nws_fire_alerts: false,
    open_meteo_fire_weather: false,
    ecmwf_fire_weather_grid: false,
    aifs_fire_weather_grid: false,
    nhc_advisories: false,
    jtwc_advisories: false,
    aifs_cyclone_features: false,
    aifs_high_wind: false,
    aifs_heavy_precipitation: false,
    gdacs_ground_truth: false,
    ...(ui.forecasts ? on(['forecasts']) : {}),
    ...(ui.signals ? on(DETECTION_LAYER_IDS) : {}),
    ...(ui.model_signals ? on(['aifs_wind_field']) : {}),
  };
}

export function mergeUiVisibility(
  stored: Partial<MapLayerVisibility> | null
): MapLayerVisibility {
  if (!stored) return { ...DEFAULT_UI_VISIBILITY };
  const legacy = stored as Partial<MapLayerVisibility> & {
    detections?: boolean;
    atmosphere?: boolean;
  };
  return {
    forecasts: legacy.forecasts ?? DEFAULT_UI_VISIBILITY.forecasts,
    signals:
      legacy.signals ??
      legacy.detections ??
      DEFAULT_UI_VISIBILITY.signals,
    model_signals:
      legacy.model_signals ??
      legacy.atmosphere ??
      DEFAULT_UI_VISIBILITY.model_signals,
  };
}
