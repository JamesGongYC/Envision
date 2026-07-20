/** Real forecast geometries from Neon (producer=rule), Jul 2026. */

export const MOZ_PRIMARY = {
  type: 'Polygon' as const,
  coordinates: [
    [
      [34.135980797, -17.678914238],
      [34.135980797, -17.250463019],
      [34.585138439, -17.250463019],
      [34.585138439, -17.678914238],
      [34.135980797, -17.678914238],
    ],
  ],
};

export const MOZ_SIBLING = {
  type: 'Polygon' as const,
  coordinates: [
    [
      [33.237665512, -17.250463019],
      [33.237665512, -16.82101462],
      [33.686823154, -16.82101462],
      [33.686823154, -17.250463019],
      [33.237665512, -17.250463019],
    ],
  ],
};

export const ANGOLA = {
  type: 'Polygon' as const,
  coordinates: [
    [
      [15.27135983, -10.275102814],
      [15.27135983, -9.832843722],
      [15.720517472, -9.832843722],
      [15.720517472, -10.275102814],
      [15.27135983, -10.275102814],
    ],
  ],
};

export const SICILY = {
  type: 'Polygon' as const,
  coordinates: [
    [
      [13.474729262, 37.435607203],
      [13.474729262, 37.791404291],
      [13.923886904, 37.791404291],
      [13.923886904, 37.435607203],
      [13.474729262, 37.435607203],
    ],
  ],
};

/** Envelope around the two Mozambique rapid-growth cells. */
export const MOZ_FOCUS = {
  type: 'Polygon' as const,
  coordinates: [
    [
      [33.2, -17.7],
      [33.2, -16.8],
      [34.6, -16.8],
      [34.6, -17.7],
      [33.2, -17.7],
    ],
  ],
};

export const ALL_SIGNAL_LAYERS = [
  'firms_hotspots',
  'open_meteo_fire_weather',
  'nws_fire_alerts',
  'nhc_advisories',
  'jtwc_advisories',
  'aifs_cyclone_features',
] as const;

export const WILDFIRE_RAPID_LAYERS = [
  'firms_hotspots',
  'open_meteo_fire_weather',
  'nws_fire_alerts',
] as const;

export const TYPHOON_INTENSIFYING_LAYERS = [
  'jtwc_advisories',
  'aifs_cyclone_features',
] as const;

export const TYPHOON_LANDFALL_LAYERS = [
  'jtwc_advisories',
  'nhc_advisories',
  'aifs_cyclone_features',
] as const;
