/** Small rule/agent provenance badge. */
export function ProducerBadge({
  producer,
}: {
  producer: 'rule' | 'agent' | string | null | undefined;
}) {
  const p = producer === 'agent' ? 'agent' : 'rule';
  return (
    <span
      className={`inline-block px-1.5 py-0.5 text-[10px] uppercase tracking-wider font-[family-name:var(--font-mono)] border ${
        p === 'agent'
          ? 'border-[var(--foreground)] text-[var(--foreground)]'
          : 'border-[var(--border)] text-[var(--muted)]'
      }`}
    >
      {p}
    </span>
  );
}
