import { sql } from './db';

export interface SystemStatus {
  n_active_forecasts: number;
  n_total_forecasts: number;
  n_total_evaluations: number;
  n_pending_proposals: number;
  last_evaluator_run: string | null;
}

export interface SkillRegistryRow {
  skill_id: string;
  version: number;
  n_forecasts: number;
  n_active: number;
  latest_at: string | null;
  n_evaluations: number;
  mean_brier: number | null;
  hits: number;
  false_positives: number;
}

export interface ProposalRow {
  id: string;
  skill_id: string;
  current_version: number;
  proposed_at: string;
  reviewed_at: string | null;
  status: 'pending' | 'approved' | 'rejected';
  curator_reasoning: string;
}

export async function getSystemStatus(): Promise<SystemStatus> {
  const rows = await sql`
    SELECT
      (SELECT COUNT(*) FROM forecasts WHERE valid_until > now())::int
        AS n_active_forecasts,
      (SELECT COUNT(*) FROM forecasts)::int
        AS n_total_forecasts,
      (SELECT COUNT(*) FROM evaluations)::int
        AS n_total_evaluations,
      (SELECT COUNT(*) FROM skill_edit_proposals WHERE status = 'pending')::int
        AS n_pending_proposals,
      (SELECT MAX(evaluated_at) FROM evaluations)
        AS last_evaluator_run
  `;
  return rows[0] as unknown as SystemStatus;
}

export async function getSkillRegistry(): Promise<SkillRegistryRow[]> {
  const rows = await sql`
    WITH forecast_stats AS (
      SELECT
        skill_id,
        MAX(skill_version)::int AS version,
        COUNT(*)::int AS n_forecasts,
        SUM(CASE WHEN valid_until > now() THEN 1 ELSE 0 END)::int AS n_active,
        MAX(issued_at) AS latest_at
      FROM forecasts
      GROUP BY skill_id
    ),
    eval_stats AS (
      SELECT
        f.skill_id,
        COUNT(*)::int AS n_evaluations,
        AVG(e.brier_contribution)::float AS mean_brier,
        SUM(CASE WHEN e.outcome = 'hit' THEN 1 ELSE 0 END)::int AS hits,
        SUM(CASE WHEN e.outcome = 'false_positive' THEN 1 ELSE 0 END)::int AS false_positives
      FROM evaluations e
      JOIN forecasts f ON f.id = e.forecast_id
      WHERE e.evaluated_at > now() - interval '14 days'
      GROUP BY f.skill_id
    )
    SELECT
      fs.skill_id,
      fs.version,
      fs.n_forecasts,
      fs.n_active,
      fs.latest_at,
      COALESCE(es.n_evaluations, 0) AS n_evaluations,
      es.mean_brier,
      COALESCE(es.hits, 0) AS hits,
      COALESCE(es.false_positives, 0) AS false_positives
    FROM forecast_stats fs
    LEFT JOIN eval_stats es ON es.skill_id = fs.skill_id
    ORDER BY fs.skill_id
  `;
  return rows as unknown as SkillRegistryRow[];
}

export async function getRecentProposals(limit = 10): Promise<ProposalRow[]> {
  const rows = await sql`
    SELECT
      id, skill_id, current_version, proposed_at, reviewed_at,
      status, curator_reasoning
    FROM skill_edit_proposals
    ORDER BY proposed_at DESC
    LIMIT ${limit}
  `;
  return rows as unknown as ProposalRow[];
}
