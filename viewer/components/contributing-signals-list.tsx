import type { GroupedContributingSignal } from '@/lib/group-contributing-signals';

type Props = {
  groups: GroupedContributingSignal[];
  compact?: boolean;
};

export function ContributingSignalsList({ groups, compact = false }: Props) {
  if (groups.length === 0) {
    return (
      <p className="text-sm text-[var(--muted)] italic font-[family-name:var(--font-mono)]">
        No contributing signals available.
      </p>
    );
  }

  return (
    <ul
      className={
        compact
          ? 'space-y-1.5 text-xs font-[family-name:var(--font-mono)]'
          : 'divide-y divide-[var(--border)] border border-[var(--border)] rounded'
      }
    >
      {groups.map((g) => (
        <li
          key={g.source}
          className={compact ? '' : 'px-4 py-3 text-sm'}
        >
          <div className="flex items-baseline justify-between gap-2 flex-wrap">
            <span className="font-medium text-[var(--foreground)]">
              {g.label}
              <span className="text-[var(--muted)] font-normal">
                {' '}
                · {g.count} detection{g.count === 1 ? '' : 's'}
              </span>
            </span>
            {!compact && g.signalTypes.length > 0 && (
              <span className="text-xs text-[var(--muted)]">
                {g.signalTypes.join(', ')}
              </span>
            )}
          </div>
          {g.url && (
            <a
              href={g.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-[var(--muted)] hover:text-[var(--foreground)] underline break-all mt-0.5 inline-block"
            >
              {g.url} ↗
            </a>
          )}
        </li>
      ))}
    </ul>
  );
}
