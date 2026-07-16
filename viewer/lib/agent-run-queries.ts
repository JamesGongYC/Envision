import { sql } from './db';
import type { AgentRunSummary } from './types';

/** Newest finished agent run for replay (public surface). */
export async function getLatestCompletedRun(
  agentType: 'forecaster' | 'critic'
): Promise<AgentRunSummary | null> {
  const rows = await sql`
    SELECT
      id,
      agent_type,
      status,
      finished_at,
      step_count
    FROM agent_run
    WHERE agent_type = ${agentType}
      AND status IN ('completed', 'gated', 'failed')
      AND finished_at IS NOT NULL
    ORDER BY finished_at DESC
    LIMIT 1
  `;
  if (!rows[0]) return null;
  const r = rows[0] as Record<string, unknown>;
  return {
    id: String(r.id),
    agent_type: String(r.agent_type),
    status: String(r.status),
    finished_at: r.finished_at ? String(r.finished_at) : null,
    step_count: Number(r.step_count ?? 0),
  };
}
