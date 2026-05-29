import type { Signal } from './types';

/**
 * Best-effort link from a contributing signal back to its source.
 * Field names vary by ingester; we check the common candidates and
 * fall back to a public landing page for the data source.
 */
export function signalSourceUrl(signal: Signal): string | null {
  const p = (signal.payload ?? {}) as Record<string, unknown>;
  const pick = (...keys: string[]): string | null => {
    for (const k of keys) {
      const v = p[k];
      if (typeof v === 'string' && /^https?:\/\//.test(v)) return v;
    }
    return null;
  };

  if (signal.source === 'nws_alerts') {
    return (
      pick('id', '@id', 'url') ??
      'https://www.weather.gov/alerts'
    );
  }

  if (signal.source === 'nhc') {
    return (
      pick(
        'forecastAdvisory',
        'publicAdvisory',
        'forecastTrack',
        'forecastCone',
        'url'
      ) ?? 'https://www.nhc.noaa.gov/'
    );
  }

  if (signal.source.startsWith('firms')) {
    // FIRMS hotspots don't have per-detection URLs; link to the data portal.
    return 'https://firms.modaps.eosdis.nasa.gov/map/';
  }

  return null;
}

/**
 * Short, human-readable display label for the signal's source.
 */
export function signalSourceLabel(signal: Signal): string {
  const map: Record<string, string> = {
    firms_viirs: 'NASA FIRMS (VIIRS)',
    firms_modis: 'NASA FIRMS (MODIS)',
    firms: 'NASA FIRMS',
    nws_alerts: 'NWS Alerts',
    nhc: 'NHC',
    jma: 'JMA',
  };
  return map[signal.source] ?? signal.source;
}
