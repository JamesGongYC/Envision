import { sql } from './db';
import type {
  Forecast,
  Signal,
  SkillBrier,
} from './types';

// All queries return ST_AsGeoJSON()::jsonb for geometry columns, which the
// Neon driver hands back as already-parsed JS objects. No JSON.parse needed.

export async function getActiveForecasts(): Promise<Forecast[]> {
  const rows = await sql`
    SELECT
      id,
      issued_at,
      valid_from,
      valid_until,
      disaster_class,
      ST_AsGeoJSON(geometry)::jsonb AS geometry,
      probability,
      skill_id,
      skill_version,
      contributing_signal_ids,
      reasoning,
      is_baseline
    FROM forecasts
    WHERE valid_until > now()
      AND is_baseline = false
    ORDER BY probability DESC, issued_at DESC
    LIMIT 200
  `;
  return rows as unknown as Forecast[];
}

export async function getForecast(id: string): Promise<Forecast | null> {
  const rows = await sql`
    SELECT
      id,
      issued_at,
      valid_from,
      valid_until,
      disaster_class,
      ST_AsGeoJSON(geometry)::jsonb AS geometry,
      probability,
      skill_id,
      skill_version,
      contributing_signal_ids,
      reasoning,
      is_baseline
    FROM forecasts
    WHERE id = ${id}
    LIMIT 1
  `;
  return (rows[0] as unknown as Forecast) ?? null;
}

export async function getContributingSignals(ids: string[]): Promise<Signal[]> {
  if (ids.length === 0) return [];
  const rows = await sql`
    SELECT
      id,
      timestamp,
      source,
      signal_type,
      ST_AsGeoJSON(geometry)::jsonb AS geometry,
      payload,
      ingested_at
    FROM signals
    WHERE id = ANY(${ids}::uuid[])
    ORDER BY timestamp DESC
  `;
  return rows as unknown as Signal[];
}

/**
 * Brier score per skill over the last 14 days. Used by /agent page.
 * Returns empty array if the evaluator hasn't run yet (no rows).
 */
export async function getSkillBriers(): Promise<SkillBrier[]> {
  const rows = await sql`
    SELECT
      f.skill_id,
      COUNT(*)::int AS n_evaluations,
      SUM(CASE WHEN e.outcome = 'hit' THEN 1 ELSE 0 END)::int AS hits,
      SUM(CASE WHEN e.outcome = 'false_positive' THEN 1 ELSE 0 END)::int AS false_positives,
      AVG(e.brier_contribution)::float AS mean_brier
    FROM evaluations e
    JOIN forecasts f ON f.id = e.forecast_id
    WHERE e.evaluated_at > now() - interval '14 days'
    GROUP BY f.skill_id
    ORDER BY mean_brier ASC
  `;
  return rows as unknown as SkillBrier[];
}

/**
 * Pending Curator proposals for the /agent page. Returns empty until
 * Day 6 when the Curator starts proposing.
 */
export async function getPendingProposals(): Promise<
  Array<{
    id: string;
    skill_id: string;
    current_version: number;
    proposed_at: string;
    curator_reasoning: string;
  }>
> {
  const rows = await sql`
    SELECT id, skill_id, current_version, proposed_at, curator_reasoning
    FROM skill_edit_proposals
    WHERE status = 'pending'
    ORDER BY proposed_at DESC
    LIMIT 20
  `;
  return rows as unknown as Array<{
    id: string;
    skill_id: string;
    current_version: number;
    proposed_at: string;
    curator_reasoning: string;
  }>;
}
