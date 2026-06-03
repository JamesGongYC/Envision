import 'server-only';

import { sql } from '@/lib/db';
import type {
  GenerationMethod,
  LineageEdgeData,
  LineageGraph,
  LineageNodeData,
  LineageStatus,
} from '@/lib/lineage-types';
import { getSkillMetadata } from '@/lib/skill-metadata';

export type {
  GenerationMethod,
  LineageEdgeData,
  LineageGraph,
  LineageNodeData,
  LineageStatus,
} from '@/lib/lineage-types';
export { MIN_SHADOW_EVALS } from '@/lib/lineage-types';

type LineageRow = {
  id: string;
  skill_id: string;
  parent_skill_id: string | null;
  version: number | null;
  generation_method: GenerationMethod;
  status: LineageStatus;
};

type LiveStatsRow = {
  skill_id: string;
  skill_version: number;
  brier: number | null;
  hits: number;
  false_positives: number;
  misses: number;
  emitted: number;
};

type ShadowStatsRow = {
  lineage_id: string;
  n_evals: number;
};

type SparklineRow = {
  skill_id: string;
  skill_version: number;
  brier: number;
};

function resolveParentLineageId(
  row: LineageRow,
  promotedBySkill: Map<string, LineageRow[]>
): string | null {
  if (!row.parent_skill_id) return null;

  const candidates = promotedBySkill.get(row.parent_skill_id) ?? [];
  if (candidates.length === 0) return null;

  if (row.version != null) {
    const older = candidates
      .filter((c) => c.version != null && c.version < row.version!)
      .sort((a, b) => (b.version ?? 0) - (a.version ?? 0));
    if (older.length > 0) return older[0]!.id;
  }

  const latest = candidates
    .filter((c) => c.version != null)
    .sort((a, b) => (b.version ?? 0) - (a.version ?? 0));
  return latest[0]?.id ?? candidates[0]?.id ?? null;
}

export async function getLineageGraph(): Promise<LineageGraph> {
  let lineageRows: LineageRow[] = [];
  let liveStats: LiveStatsRow[] = [];
  let shadowStats: ShadowStatsRow[] = [];
  let sparklines: SparklineRow[] = [];
  let orphanProposalCount = 0;

  try {
    const [
      lineageResult,
      statsResult,
      shadowResult,
      sparkResult,
      orphanResult,
    ] = await Promise.all([
      sql`
        SELECT id, skill_id, parent_skill_id, version,
               generation_method, status
        FROM skill_lineage
        ORDER BY skill_id, version NULLS LAST, created_at
      `,
      sql`
        SELECT f.skill_id, f.skill_version::int AS skill_version,
               AVG(e.brier_contribution)::float AS brier,
               COALESCE(SUM(CASE WHEN e.outcome = 'hit' THEN 1 ELSE 0 END), 0)::int AS hits,
               COALESCE(SUM(CASE WHEN e.outcome = 'false_positive' THEN 1 ELSE 0 END), 0)::int AS false_positives,
               COALESCE(SUM(CASE WHEN e.outcome = 'miss' THEN 1 ELSE 0 END), 0)::int AS misses,
               COUNT(DISTINCT f.id)::int AS emitted
        FROM forecasts f
        LEFT JOIN evaluations e ON e.forecast_id = f.id
        WHERE f.issued_at > now() - interval '30 days'
        GROUP BY f.skill_id, f.skill_version
      `,
      sql`
        SELECT fs.lineage_id,
               COUNT(*)::int AS n_evals
        FROM shadow_evaluations se
        JOIN forecasts_shadow fs ON fs.id = se.shadow_forecast_id
        WHERE fs.shadow_promotion_status = 'evaluating'
          AND fs.lineage_id IS NOT NULL
        GROUP BY fs.lineage_id
      `,
      sql`
        SELECT f.skill_id, f.skill_version::int AS skill_version,
               AVG(e.brier_contribution)::float AS brier
        FROM forecasts f
        JOIN evaluations e ON e.forecast_id = f.id
        WHERE f.issued_at > now() - interval '30 days'
        GROUP BY f.skill_id, f.skill_version
        ORDER BY f.skill_id, f.skill_version
      `,
      sql`
        SELECT COUNT(*)::int AS n
        FROM skill_edit_proposals
        WHERE lineage_id IS NULL
      `,
    ]);

    lineageRows = lineageResult as unknown as LineageRow[];
    liveStats = statsResult as unknown as LiveStatsRow[];
    shadowStats = shadowResult as unknown as ShadowStatsRow[];
    sparklines = sparkResult as unknown as SparklineRow[];
    orphanProposalCount = (orphanResult[0] as { n: number })?.n ?? 0;
  } catch (e) {
    console.error('[lineage-queries]', e);
    return { nodes: [], edges: [], orphanProposalCount: 0 };
  }

  const statsKey = (skillId: string, version: number | null) =>
    version != null ? `${skillId}:${version}` : skillId;

  const liveByKey = new Map<string, LiveStatsRow>();
  for (const s of liveStats) {
    liveByKey.set(statsKey(s.skill_id, s.skill_version), s);
  }

  const shadowByLineage = new Map<string, number>();
  for (const s of shadowStats) {
    shadowByLineage.set(s.lineage_id, s.n_evals);
  }

  const sparkBySkill = new Map<string, { version: number; brier: number }[]>();
  for (const s of sparklines) {
    const list = sparkBySkill.get(s.skill_id) ?? [];
    list.push({ version: s.skill_version, brier: s.brier });
    sparkBySkill.set(s.skill_id, list);
  }

  const promotedBySkill = new Map<string, LineageRow[]>();
  for (const row of lineageRows) {
    if (row.status === 'promoted' && row.version != null) {
      const list = promotedBySkill.get(row.skill_id) ?? [];
      list.push(row);
      promotedBySkill.set(row.skill_id, list);
    }
  }

  const nodes: LineageNodeData[] = lineageRows.map((row) => {
    const meta = getSkillMetadata(row.skill_id);
    const key = statsKey(row.skill_id, row.version);
    const live = liveByKey.get(key);
    const isShadowLike =
      row.status === 'shadow' || row.status === 'candidate';

    return {
      id: row.id,
      skillId: row.skill_id,
      parentSkillId: row.parent_skill_id,
      version: row.version,
      generationMethod: row.generation_method,
      status: row.status,
      displayName: meta?.displayName ?? row.skill_id,
      plainDescription: meta?.plainDescription ?? '',
      brier: isShadowLike ? null : (live?.brier ?? null),
      hits: live?.hits ?? 0,
      falsePositives: live?.false_positives ?? 0,
      misses: live?.misses ?? 0,
      emitted: live?.emitted ?? 0,
      shadowEvalCount: isShadowLike
        ? (shadowByLineage.get(row.id) ?? 0)
        : null,
      brierByVersion: sparkBySkill.get(row.skill_id) ?? [],
    };
  });

  const edges: LineageEdgeData[] = [];
  for (const row of lineageRows) {
    const parentId = resolveParentLineageId(row, promotedBySkill);
    if (parentId && parentId !== row.id) {
      edges.push({
        id: `${parentId}->${row.id}`,
        source: parentId,
        target: row.id,
      });
    }
  }

  return { nodes, edges, orphanProposalCount };
}
