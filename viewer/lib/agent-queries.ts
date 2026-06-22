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

export interface LlmApiHealth {
  attempts: number;
  successes: number;
  overloaded: number;
  overloaded_rate: number;
  signal_catalog_stalest_hours: number | null;
}

export async function getLlmApiHealth(
  windowMinutes = 10
): Promise<LlmApiHealth | null> {
  try {
    const rows = await sql`
      SELECT
        count(*)::int AS attempts,
        count(*) FILTER (WHERE outcome = 'success')::int AS successes,
        count(*) FILTER (WHERE status_code = 529)::int AS overloaded,
        coalesce(
          count(*) FILTER (WHERE status_code = 529)::float
            / NULLIF(count(*), 0),
          0
        ) AS overloaded_rate
      FROM llm_call_log
      WHERE created_at >= now() - (${windowMinutes} * interval '1 minute')
    `;
    const staleRows = await sql`
      SELECT EXTRACT(EPOCH FROM (now() - MIN(last_seen))) / 3600.0 AS stalest_hours
      FROM signal_catalog
    `;
    const row = rows[0] as {
      attempts: number;
      successes: number;
      overloaded: number;
      overloaded_rate: number;
    };
    const stale = staleRows[0] as { stalest_hours: number | null };
    return {
      attempts: row.attempts,
      successes: row.successes,
      overloaded: row.overloaded,
      overloaded_rate: row.overloaded_rate,
      signal_catalog_stalest_hours: stale?.stalest_hours ?? null,
    };
  } catch {
    return null;
  }
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

export async function getActiveSkillCount(): Promise<number> {
  const rows = await sql`
    SELECT count(DISTINCT skill_id)::int AS n
    FROM forecasts
    WHERE issued_at > now() - interval '24 hours'
  `;
  return (rows[0] as { n: number }).n;
}

export async function getLastIngestionTimestamp(): Promise<string | null> {
  const rows = await sql`
    SELECT max(ingested_at) AS ts FROM signals
  `;
  const ts = (rows[0] as { ts: string | null }).ts;
  return ts ?? null;
}

export async function getLastCuratorActivity(): Promise<string | null> {
  const rows = await sql`
    SELECT max(proposed_at) AS ts FROM skill_edit_proposals
  `;
  const ts = (rows[0] as { ts: string | null }).ts;
  return ts ?? null;
}

export interface SkillCardStats {
  skill_id: string;
  current_version: number | null;
  brier_mean: number | null;
  hits: number;
  false_positives: number;
  eval_count: number;
}

export interface SkillVersionBrier {
  skill_id: string;
  skill_version: number;
  brier: number;
}

export async function getSkillCardStats(): Promise<SkillCardStats[]> {
  const rows = await sql`
    SELECT
      f.skill_id,
      max(f.skill_version)::int AS current_version,
      avg(e.brier_contribution)::float AS brier_mean,
      coalesce(sum(CASE WHEN e.outcome = 'hit' THEN 1 ELSE 0 END), 0)::int AS hits,
      coalesce(sum(CASE WHEN e.outcome = 'false_positive' THEN 1 ELSE 0 END), 0)::int
        AS false_positives,
      count(e.id)::int AS eval_count
    FROM forecasts f
    LEFT JOIN evaluations e ON e.forecast_id = f.id
    WHERE f.issued_at > now() - interval '30 days'
    GROUP BY f.skill_id
    ORDER BY f.skill_id
  `;
  return rows as unknown as SkillCardStats[];
}

export async function getBrierByVersion(): Promise<SkillVersionBrier[]> {
  const rows = await sql`
    SELECT
      f.skill_id,
      f.skill_version::int AS skill_version,
      avg(e.brier_contribution)::float AS brier
    FROM forecasts f
    JOIN evaluations e ON e.forecast_id = f.id
    WHERE f.issued_at > now() - interval '30 days'
    GROUP BY f.skill_id, f.skill_version
    ORDER BY f.skill_id, f.skill_version
  `;
  return rows as unknown as SkillVersionBrier[];
}

export interface SkillCardViewModel {
  id: string;
  displayName: string;
  plainDescription: string;
  currentVersion: number | null;
  brierMean: number | null;
  hits: number;
  falsePositives: number;
  brierByVersion: { version: number; brier: number }[];
}

export async function buildSkillCards(): Promise<SkillCardViewModel[]> {
  const { getSkillMetadata } = await import('./skill-metadata');
  const [stats, byVersion] = await Promise.all([
    getSkillCardStats(),
    getBrierByVersion(),
  ]);

  const versionMap = new Map<string, { version: number; brier: number }[]>();
  for (const row of byVersion) {
    const list = versionMap.get(row.skill_id) ?? [];
    list.push({ version: row.skill_version, brier: row.brier });
    versionMap.set(row.skill_id, list);
  }

  return stats.map((s) => {
    const meta = getSkillMetadata(s.skill_id);
    return {
      id: s.skill_id,
      displayName: meta?.displayName ?? s.skill_id,
      plainDescription: meta?.plainDescription ?? '',
      currentVersion: s.current_version,
      brierMean: s.brier_mean,
      hits: s.hits,
      falsePositives: s.false_positives,
      brierByVersion: versionMap.get(s.skill_id) ?? [],
    };
  });
}
