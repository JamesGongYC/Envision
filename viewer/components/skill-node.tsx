'use client';

import { memo, useCallback } from 'react';
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react';
import { BrierSparkline } from '@/components/brier-sparkline';
import {
  MIN_SHADOW_EVALS,
  type LineageNodeData,
} from '@/lib/lineage-types';

export type SkillNodeData = LineageNodeData & {
  expanded: boolean;
  onToggle: (id: string) => void;
};

function fmtBrier(b: number | null): string {
  if (b === null || Number.isNaN(b)) return '—';
  return b.toFixed(4);
}

function statusLabel(status: LineageNodeData['status']): string {
  switch (status) {
    case 'shadow':
    case 'candidate':
      return status;
    case 'promoted':
      return 'live';
    case 'archived':
      return 'archived';
    default:
      return status;
  }
}

function SkillNodeComponent({ id, data }: NodeProps<Node<SkillNodeData>>) {
  const {
    displayName,
    plainDescription,
    skillId,
    version,
    status,
    generationMethod,
    brier,
    hits,
    falsePositives,
    misses,
    emitted,
    shadowEvalCount,
    brierByVersion,
    expanded,
    onToggle,
  } = data;

  const handleClick = useCallback(() => {
    onToggle(id);
  }, [id, onToggle]);

  const isEvaluating =
    status === 'shadow' || status === 'candidate';

  return (
    <div
      className={`rounded border bg-[var(--surface-elevated)] text-xs font-[family-name:var(--font-mono)] shadow-sm min-w-[200px] max-w-[280px] ${
        expanded ? 'border-[var(--foreground)]' : 'border-[var(--border)]'
      }`}
    >
      <Handle type="target" position={Position.Top} className="!bg-[var(--muted)]" />
      <button
        type="button"
        onClick={handleClick}
        className="w-full text-left p-3 focus:outline-none focus-visible:ring-1 focus-visible:ring-[var(--foreground)]"
      >
        <div className="flex items-start justify-between gap-2 mb-1">
          <span className="font-semibold text-[var(--foreground)] leading-snug">
            {displayName}
          </span>
          <span
            className={`shrink-0 text-[10px] uppercase px-1 py-0.5 rounded border ${
              isEvaluating
                ? 'border-amber-700 text-amber-400'
                : status === 'promoted'
                  ? 'border-[var(--border)] text-[var(--muted)]'
                  : 'border-[var(--border)] text-[var(--muted)]'
            }`}
          >
            {statusLabel(status)}
          </span>
        </div>
        {!expanded && (
          <p className="text-[var(--muted)] leading-snug line-clamp-2">
            {plainDescription || skillId}
          </p>
        )}
        {isEvaluating && !expanded && (
          <p className="text-amber-500/90 mt-1 text-[10px]">
            evaluating · {shadowEvalCount ?? 0}/{MIN_SHADOW_EVALS}
          </p>
        )}
      </button>
      {expanded && (
        <div className="px-3 pb-3 pt-0 border-t border-[var(--border)] space-y-2">
          <p className="text-[var(--muted)] leading-snug text-[11px]">
            {plainDescription || skillId}
          </p>
          {isEvaluating ? (
            <p className="text-amber-500/90 text-[10px]">
              evaluating · {shadowEvalCount ?? 0}/{MIN_SHADOW_EVALS}
            </p>
          ) : (
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px]">
              <div>
                <dt className="text-[var(--muted)]">Brier (live)</dt>
                <dd className="tabular-nums text-[var(--foreground)]">
                  {fmtBrier(brier)}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--muted)]">Version</dt>
                <dd className="tabular-nums text-[var(--foreground)]">
                  {version != null ? `v${version}` : '—'}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--muted)]">Hits</dt>
                <dd className="tabular-nums text-green-400">{hits}</dd>
              </div>
              <div>
                <dt className="text-[var(--muted)]">False +</dt>
                <dd className="tabular-nums text-red-400">{falsePositives}</dd>
              </div>
              <div>
                <dt className="text-[var(--muted)]">Misses</dt>
                <dd className="tabular-nums text-[var(--foreground)]">
                  {misses}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--muted)]">Emitted</dt>
                <dd className="tabular-nums text-[var(--foreground)]">
                  {emitted}
                </dd>
              </div>
              <div className="col-span-2">
                <dt className="text-[var(--muted)]">Origin</dt>
                <dd className="text-[var(--foreground)]">{generationMethod}</dd>
              </div>
            </dl>
          )}
          {!isEvaluating && brierByVersion.length > 1 && (
            <div className="flex justify-end">
              <BrierSparkline
                data={brierByVersion}
                width={100}
                height={28}
              />
            </div>
          )}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} className="!bg-[var(--muted)]" />
    </div>
  );
}

export const SkillNode = memo(SkillNodeComponent);
