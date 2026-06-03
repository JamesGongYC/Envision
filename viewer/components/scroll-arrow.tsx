'use client';

import { scrollToMap } from '@/lib/landing-scroll';

export function ScrollArrow() {
  return (
    <button
      type="button"
      onClick={() => scrollToMap()}
      className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 flex h-10 w-10 items-center justify-center rounded-full border border-[var(--border)] text-[var(--foreground)] hover:border-[var(--foreground)] transition-colors"
      aria-label="Scroll to forecasts map"
    >
      <span className="text-lg leading-none" aria-hidden>
        ↓
      </span>
    </button>
  );
}
