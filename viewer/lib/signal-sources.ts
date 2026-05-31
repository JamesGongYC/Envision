import type { Signal } from './types';

export const SIGNAL_SOURCE_ATTRIBUTION: Record<
  string,
  { label: string; url: string; license: string }
> = {
  open_meteo: {
    label: 'Open-Meteo',
    url: 'https://open-meteo.com/',
    license: 'CC BY 4.0',
  },
  jtwc: {
    label: 'Joint Typhoon Warning Center',
    url: 'https://www.metoc.navy.mil/jtwc/',
    license: 'Public domain (US Government work)',
  },
  ecmwf_open_data: {
    label: 'ECMWF Open Data',
    url: 'https://www.ecmwf.int/en/forecasts/datasets/open-data',
    license: 'CC BY 4.0',
  },
  aifs: {
    label: 'AIFS (ECMWF AI Forecasting System)',
    url: 'https://www.ecmwf.int/en/about/media-centre/news/2024/aifs-our-new-ml-model',
    license: 'ECMWF Open Data terms',
  },
};

/**
 * Best-effort link from a contributing signal back to its source.
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
    return pick('id', '@id', 'url') ?? 'https://www.weather.gov/alerts';
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

  if (signal.source === 'open_meteo') {
    return SIGNAL_SOURCE_ATTRIBUTION.open_meteo.url;
  }

  if (signal.source === 'jtwc') {
    return SIGNAL_SOURCE_ATTRIBUTION.jtwc.url;
  }

  if (signal.source === 'ecmwf_open_data') {
    return SIGNAL_SOURCE_ATTRIBUTION.ecmwf_open_data.url;
  }

  if (signal.source === 'aifs') {
    return SIGNAL_SOURCE_ATTRIBUTION.aifs.url;
  }

  if (signal.source.startsWith('firms')) {
    return 'https://firms.modaps.eosdis.nasa.gov/map/';
  }

  return null;
}

/**
 * Short, human-readable display label for the signal's source.
 */
export function signalSourceLabel(signal: Signal): string {
  const attr = SIGNAL_SOURCE_ATTRIBUTION[signal.source];
  if (attr) return attr.label;

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
