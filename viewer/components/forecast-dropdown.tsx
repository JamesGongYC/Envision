'use client';

import { useState } from 'react';
import Link from 'next/link';
import type { Forecast } from '@/lib/types';
import { SKILL_METADATA } from '@/lib/skill-metadata';
import { TypingText } from '@/components/typing-text';

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  });
}

export function ForecastDropdown({ forecast }: { forecast: Forecast }) {
  const [skipAnimation, setSkipAnimation] = useState(false);
  const displayName =
    SKILL_METADATA[forecast.skill_id]?.displayName ?? forecast.skill_id;
  const reasoning = forecast.reasoning?.trim()
    ? forecast.reasoning
    : '(no reasoning available)';

  return (
    <div className="max-w-sm p-3 bg-white rounded shadow-lg text-sm">
      <div className="flex justify-between items-baseline gap-2 mb-2">
        <h3 className="font-medium text-neutral-900">{displayName}</h3>
        <span className="text-xs text-slate-500 shrink-0">
          v{forecast.skill_version}
        </span>
      </div>
      <div className="text-xs text-slate-600 mb-2">
        {forecast.disaster_class} · {(forecast.probability * 100).toFixed(0)}%
        confidence · valid through {formatTime(forecast.valid_until)}
      </div>
      <div className="text-sm leading-relaxed mb-3 text-neutral-800">
        <TypingText
          key={forecast.id}
          text={reasoning}
          skip={skipAnimation}
        />
      </div>
      {!skipAnimation && reasoning !== '(no reasoning available)' && (
        <button
          type="button"
          onClick={() => setSkipAnimation(true)}
          className="text-xs text-slate-500 underline mb-2 block"
        >
          Skip animation
        </button>
      )}
      <Link
        href={`/forecast/${forecast.id}`}
        className="text-xs text-blue-600 underline"
      >
        View detail page →
      </Link>
    </div>
  );
}
