export type SignalStyleKey =
  | 'hotspot'
  | 'fire_warning'
  | 'cyclone_nhc'
  | 'cyclone_jtwc'
  | 'cyclone_feature'
  | 'fire_weather'
  | 'gdacs';

export type SignalStyle = {
  color: string;
  fillColor: string;
  shape: 'circle' | 'square' | 'diamond' | 'cross';
  radius: number;
  opacity: number;
  weight: number;
};

export const SIGNAL_STYLES: Record<SignalStyleKey, SignalStyle> = {
  hotspot: {
    color: '#dc2626',
    fillColor: '#fca5a5',
    shape: 'circle',
    radius: 3,
    opacity: 0.6,
    weight: 1,
  },
  fire_warning: {
    color: '#ea580c',
    fillColor: '#fdba74',
    shape: 'circle',
    radius: 5,
    opacity: 0.8,
    weight: 1.5,
  },
  cyclone_nhc: {
    color: '#2563eb',
    fillColor: '#93c5fd',
    shape: 'square',
    radius: 8,
    opacity: 0.9,
    weight: 2,
  },
  cyclone_jtwc: {
    color: '#4f46e5',
    fillColor: '#a5b4fc',
    shape: 'square',
    radius: 8,
    opacity: 0.9,
    weight: 2,
  },
  cyclone_feature: {
    color: '#0891b2',
    fillColor: '#67e8f9',
    shape: 'diamond',
    radius: 6,
    opacity: 0.7,
    weight: 1.5,
  },
  fire_weather: {
    color: '#d97706',
    fillColor: '#fcd34d',
    shape: 'circle',
    radius: 4,
    opacity: 0.6,
    weight: 1,
  },
  gdacs: {
    color: '#6b7280',
    fillColor: '#d1d5db',
    shape: 'cross',
    radius: 6,
    opacity: 0.5,
    weight: 2,
  },
};

export function styleKeyForLayer(layerId: string, source?: string): SignalStyleKey {
  switch (layerId) {
    case 'firms_hotspots':
      return 'hotspot';
    case 'nws_fire_alerts':
      return 'fire_warning';
    case 'nhc_advisories':
      return 'cyclone_nhc';
    case 'jtwc_advisories':
      return 'cyclone_jtwc';
    case 'aifs_cyclone_features':
      return 'cyclone_feature';
    case 'open_meteo_fire_weather':
      return 'fire_weather';
    case 'gdacs_ground_truth':
      return 'gdacs';
    default:
      if (source === 'jtwc') return 'cyclone_jtwc';
      if (source === 'nhc') return 'cyclone_nhc';
      return 'hotspot';
  }
}

/** Optional recency fade (Day 3 polish); returns multiplier 0.4–1.0 */
export type PolygonStyle = {
  fill: string;
  stroke: string;
  opacity: number;
  weight: number;
};

export const POLYGON_STYLES: Record<string, PolygonStyle> = {
  ecmwf_fire_weather_grid: {
    fill: '#FB923C',
    stroke: '#C2410C',
    opacity: 0.25,
    weight: 1.5,
  },
  aifs_fire_weather_grid: {
    fill: '#FBBF24',
    stroke: '#C2410C',
    opacity: 0.25,
    weight: 1.5,
  },
  aifs_high_wind: {
    fill: '#A78BFA',
    stroke: '#6D28D9',
    opacity: 0.2,
    weight: 1.5,
  },
  aifs_heavy_precipitation: {
    fill: '#60A5FA',
    stroke: '#1E40AF',
    opacity: 0.25,
    weight: 1.5,
  },
};

export function applyRecencyFade(
  opacity: number,
  timestampIso: string,
  now: Date = new Date()
): number {
  const ts = new Date(timestampIso).getTime();
  const ageHours = (now.getTime() - ts) / (1000 * 60 * 60);
  if (ageHours > 12) return opacity * 0.4;
  return opacity;
}
