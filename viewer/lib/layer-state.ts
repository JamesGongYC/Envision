export type LayerCategory =
  | 'wildfires'
  | 'cyclones'
  | 'weather'
  | 'atmospheric_flow'
  | 'ground_truth'
  | 'forecasts';

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

export const DEFAULT_VISIBILITY: LayerVisibility = {
  forecasts: true,
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
};

export const STORAGE_KEY = 'envision.layers';

export type LayerTreeLeaf = {
  id: LayerId;
  label: string;
  enabled: boolean;
};

export type LayerTreeCategory = {
  category: LayerCategory;
  label: string;
  layers: LayerTreeLeaf[];
};

/** Matches docs/v2.5_plan.md §7 layer panel tree. */
export const LAYER_TREE: LayerTreeCategory[] = [
  {
    category: 'wildfires',
    label: 'Wildfires',
    layers: [
      {
        id: 'firms_hotspots',
        label: 'FIRMS hotspots',
        enabled: true,
      },
      {
        id: 'nws_fire_alerts',
        label: 'NWS fire alerts',
        enabled: true,
      },
      {
        id: 'open_meteo_fire_weather',
        label: 'Open-Meteo fire weather',
        enabled: true,
      },
      {
        id: 'ecmwf_fire_weather_grid',
        label: 'ECMWF fire weather grid',
        enabled: true,
      },
      {
        id: 'aifs_fire_weather_grid',
        label: 'AIFS fire weather grid',
        enabled: true,
      },
    ],
  },
  {
    category: 'cyclones',
    label: 'Cyclones',
    layers: [
      {
        id: 'nhc_advisories',
        label: 'NHC advisories',
        enabled: true,
      },
      {
        id: 'jtwc_advisories',
        label: 'JTWC advisories',
        enabled: true,
      },
      {
        id: 'aifs_cyclone_features',
        label: 'AIFS cyclone features',
        enabled: true,
      },
    ],
  },
  {
    category: 'weather',
    label: 'Weather features',
    layers: [
      {
        id: 'aifs_high_wind',
        label: 'AIFS high wind',
        enabled: true,
      },
      {
        id: 'aifs_heavy_precipitation',
        label: 'AIFS heavy precipitation',
        enabled: true,
      },
    ],
  },
  {
    category: 'atmospheric_flow',
    label: 'Atmospheric flow',
    layers: [
      {
        id: 'aifs_wind_field',
        label: 'Surface wind (AIFS +24h)',
        enabled: true,
      },
    ],
  },
  {
    category: 'ground_truth',
    label: 'Ground truth',
    layers: [
      {
        id: 'gdacs_ground_truth',
        label: 'GDACS events',
        enabled: true,
      },
    ],
  },
  {
    category: 'forecasts',
    label: 'Forecasts',
    layers: [
      {
        id: 'forecasts',
        label: 'Active forecasts',
        enabled: true,
      },
    ],
  },
];

export function mergeVisibility(stored: Partial<LayerVisibility> | null): LayerVisibility {
  if (!stored) return { ...DEFAULT_VISIBILITY };
  return { ...DEFAULT_VISIBILITY, ...stored };
}
