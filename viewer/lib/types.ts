// Mirrors envision_plan.md §6 schemas. Keep in sync with db/schemas.py.

export type DisasterClass = 'wildfire' | 'typhoon';

export type ForecastOutcome = 'hit' | 'miss' | 'false_positive';

export interface Forecast {
  id: string;
  issued_at: string; // ISO timestamp
  valid_from: string;
  valid_until: string;
  disaster_class: DisasterClass;
  geometry: GeoJSON.Geometry; // ST_AsGeoJSON output, parsed
  probability: number;
  skill_id: string;
  skill_version: number;
  contributing_signal_ids: string[]; // UUIDs
  reasoning: string;
  is_baseline: boolean;
}

export interface Signal {
  id: string;
  timestamp: string;
  source: string;
  signal_type: string;
  geometry: GeoJSON.Geometry | null;
  payload: Record<string, unknown>;
  ingested_at: string;
}

export interface GroundTruthEvent {
  id: string;
  occurred_at: string;
  source: string;
  disaster_class: string;
  geometry: GeoJSON.Geometry | null;
  severity: string | null;
  payload: Record<string, unknown>;
}

export interface Evaluation {
  id: string;
  forecast_id: string;
  matched_ground_truth_id: string | null;
  outcome: ForecastOutcome;
  brier_contribution: number;
  evaluated_at: string;
}

// Aggregated for the /agent page
export interface SkillBrier {
  skill_id: string;
  n_evaluations: number;
  hits: number;
  false_positives: number;
  mean_brier: number;
}
