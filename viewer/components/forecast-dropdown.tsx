'use client';

import { forwardRef } from 'react';
import Link from 'next/link';
import { TypingText } from '@/components/typing-text';
import type { Forecast } from '@/lib/types';
import { SKILL_METADATA } from '@/lib/skill-metadata';

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  });
}

export type ForecastDropdownProps = {
  forecast: Forecast;
  className?: string;
  style?: React.CSSProperties;
};

export const ForecastDropdown = forwardRef<HTMLDivElement, ForecastDropdownProps>(
  function ForecastDropdown({ forecast, className = '', style }, ref) {
    const displayName =
      SKILL_METADATA[forecast.skill_id]?.displayName ?? forecast.skill_id;
    const reasoning = forecast.reasoning?.trim()
      ? forecast.reasoning
      : '(no reasoning available)';

    return (
      <div
        ref={ref}
        style={style}
        className={`max-w-xl w-[min(36rem,100%)] p-3 bg-[var(--surface-elevated)] rounded border border-[var(--border)] shadow-lg text-sm font-[family-name:var(--font-mono)] overflow-y-auto ${className}`.trim()}
      >
        <div className="flex justify-between items-baseline gap-2 mb-2">
          <h3 className="font-medium text-[var(--foreground)]">{displayName}</h3>
          <span className="text-xs text-[var(--muted)] shrink-0">
            v{forecast.skill_version}
          </span>
        </div>
        <div className="text-xs text-[var(--muted)] mb-2">
          {forecast.disaster_class} · {(forecast.probability * 100).toFixed(0)}%
          confidence · valid through {formatTime(forecast.valid_until)}
        </div>
        <div className="text-sm leading-relaxed mb-3 text-[var(--foreground)]">
          <TypingText key={forecast.id} text={reasoning} />
        </div>
        <Link
          href={`/forecast/${forecast.id}`}
          className="text-xs text-[var(--muted)] hover:text-[var(--foreground)] underline"
        >
          View detail page →
        </Link>
      </div>
    );
  }
);
