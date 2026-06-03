import { formatTimeAgo } from '@/lib/time-ago';

const CURATOR_STALE_MS = 30 * 60 * 60 * 1000;

export function curatorStatusLabel(lastProposed: string | null): string {
  if (!lastProposed) return 'Curator: inactive (stale)';
  const age = Date.now() - new Date(lastProposed).getTime();
  if (age > CURATOR_STALE_MS) {
    return 'Curator: inactive (stale)';
  }
  return `Curator: active (last run ${formatTimeAgo(lastProposed)})`;
}
