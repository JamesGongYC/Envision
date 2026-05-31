export type SkillCategory =
  | 'detection'
  | 'ingestion'
  | 'evaluation'
  | 'curation'
  | 'housekeeping';

export interface SkillMetadataEntry {
  id: string;
  displayName: string;
  plainDescription: string;
  category: SkillCategory;
}

export const SKILL_METADATA: Record<string, SkillMetadataEntry> = {
  wildfire_risk_elevated: {
    id: 'wildfire_risk_elevated',
    displayName: 'Wildfire Risk Elevated',
    plainDescription:
      'Looks for groups of active fire hotspots in areas that already have ' +
      'official fire weather warnings. Flags places where fires and warned ' +
      'conditions overlap.',
    category: 'detection',
  },
  wildfire_rapid_growth: {
    id: 'wildfire_rapid_growth',
    displayName: 'Wildfire Rapid Growth',
    plainDescription:
      'Tracks how fast new fire hotspots appear in the same region over ' +
      'several days. Issues a forecast when activity is growing quickly ' +
      'in a fixed area.',
    category: 'detection',
  },
  typhoon_intensifying: {
    id: 'typhoon_intensifying',
    displayName: 'Typhoon Intensifying',
    plainDescription:
      'Watches tropical cyclone advisories for a sharp drop in central ' +
      'pressure over about half a day. Signals storms that are strengthening ' +
      'faster than a set threshold.',
    category: 'detection',
  },
  typhoon_landfall_imminent: {
    id: 'typhoon_landfall_imminent',
    displayName: 'Typhoon Landfall Imminent',
    plainDescription:
      'Projects a storm’s path forward and checks whether populated towns ' +
      'fall inside that path. Focuses on places with at least ten thousand ' +
      'residents.',
    category: 'detection',
  },
  'firms-active-fires': {
    id: 'firms-active-fires',
    displayName: 'FIRMS Active Fires',
    plainDescription:
      'Pulls near-real-time satellite fire hotspot detections worldwide ' +
      'and stores each point as a signal for downstream skills.',
    category: 'ingestion',
  },
  'nws-fire-alerts': {
    id: 'nws-fire-alerts',
    displayName: 'NWS Fire Alerts',
    plainDescription:
      'Downloads active U.S. fire weather watches and warnings and saves ' +
      'their map areas as signals.',
    category: 'ingestion',
  },
  'nhc-cyclones': {
    id: 'nhc-cyclones',
    displayName: 'NHC Cyclones',
    plainDescription:
      'Reads Atlantic and eastern Pacific tropical cyclone bulletins from ' +
      'the National Hurricane Center.',
    category: 'ingestion',
  },
  'jtwc-cyclones': {
    id: 'jtwc-cyclones',
    displayName: 'JTWC Cyclones',
    plainDescription:
      'Ingests U.S. Joint Typhoon Warning Center bulletins for the western ' +
      'Pacific and related basins.',
    category: 'ingestion',
  },
  'open-meteo-fire-weather': {
    id: 'open-meteo-fire-weather',
    displayName: 'Open-Meteo Fire Weather',
    plainDescription:
      'Fetches short-range weather forecasts for fire-prone regions and ' +
      'flags periods that look dry, hot, or windy.',
    category: 'ingestion',
  },
  'gdacs-ground-truth': {
    id: 'gdacs-ground-truth',
    displayName: 'GDACS Ground Truth',
    plainDescription:
      'Collects confirmed disaster events from GDACS so forecasts can be ' +
      'scored against what actually happened.',
    category: 'ingestion',
  },
  'ecmwf-fire-weather-derived': {
    id: 'ecmwf-fire-weather-derived',
    displayName: 'ECMWF Fire Weather Derived',
    plainDescription:
      'Downloads ECMWF open forecast grids and turns high fire-weather ' +
      'risk areas into map polygons stored as signals.',
    category: 'ingestion',
  },
  'aifs-overlay': {
    id: 'aifs-overlay',
    displayName: 'AIFS Overlay',
    plainDescription:
      'Runs five ECMWF AIFS forecast pipelines (cyclone features, fire ' +
      'weather, wind, heavy rain, and heat) and writes each result as ' +
      'signals for later use.',
    category: 'ingestion',
  },
  'forecast-evaluator': {
    id: 'forecast-evaluator',
    displayName: 'Forecast Evaluator',
    plainDescription:
      'Compares expired forecasts to confirmed events and records whether ' +
      'each forecast was a hit or a false alarm, plus a calibration score.',
    category: 'evaluation',
  },
  curator: {
    id: 'curator',
    displayName: 'Curator',
    plainDescription:
      'Reviews recent forecast scores and may propose small parameter ' +
      'changes to detection skills. Every change waits for human approval.',
    category: 'curation',
  },
  'housekeeping-retention': {
    id: 'housekeeping-retention',
    displayName: 'Housekeeping Retention',
    plainDescription:
      'Deletes old signals and forecasts on a schedule and refreshes the ' +
      'catalog of what the system has seen.',
    category: 'housekeeping',
  },
};

export function getSkillMetadata(id: string): SkillMetadataEntry | undefined {
  return SKILL_METADATA[id];
}
