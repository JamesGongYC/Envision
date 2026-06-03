import {
  getActiveSkillCount,
  getLastCuratorActivity,
  getLastIngestionTimestamp,
} from '@/lib/agent-queries';
import { curatorStatusLabel } from '@/lib/curator-status';
import { formatTimeAgo } from '@/lib/time-ago';

export const revalidate = 60;

export async function StatusHeader() {
  const [skillCount, lastIngestion, lastCurator] = await Promise.all([
    getActiveSkillCount(),
    getLastIngestionTimestamp(),
    getLastCuratorActivity(),
  ]);

  return (
    <div className="bg-slate-100 border-b border-slate-200 text-slate-700 text-xs shrink-0">
      <div className="container mx-auto px-4 py-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono tabular-nums">
        <span className="font-sans font-semibold tracking-tight text-slate-900">
          Envision
        </span>
        <span className="text-slate-400" aria-hidden>
          |
        </span>
        <span>
          {skillCount} skill{skillCount === 1 ? '' : 's'} active
        </span>
        <span className="text-slate-400" aria-hidden>
          |
        </span>
        <span>
          Last ingestion: {formatTimeAgo(lastIngestion)}
        </span>
        <span className="text-slate-400" aria-hidden>
          |
        </span>
        <span className="font-sans">{curatorStatusLabel(lastCurator)}</span>
      </div>
    </div>
  );
}
