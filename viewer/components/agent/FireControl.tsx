'use client';

type FireControlProps = {
  busy: boolean;
  onFire: () => void;
  label?: string;
};

/** Operator-only fire button. Parent must only mount when canFire. */
export function FireControl({
  busy,
  onFire,
  label = 'Fire forecaster',
}: FireControlProps) {
  return (
    <button
      type="button"
      onClick={onFire}
      disabled={busy}
      className="font-[family-name:var(--font-mono)] text-xs uppercase tracking-wider px-3 py-2 border border-[var(--border)] bg-[var(--surface-elevated)] text-[var(--foreground)] hover:bg-[var(--surface)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
    >
      {busy ? 'Running…' : label}
    </button>
  );
}
