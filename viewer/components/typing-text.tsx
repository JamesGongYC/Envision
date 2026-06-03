'use client';

import { useEffect, useState } from 'react';

export type TypingTextProps = {
  text: string;
  charsPerSecond?: number;
  showCursor?: boolean;
  onComplete?: () => void;
};

export function TypingText({
  text,
  charsPerSecond = 30,
  showCursor = true,
  onComplete,
}: TypingTextProps) {
  const [displayedChars, setDisplayedChars] = useState(0);
  const done = displayedChars >= text.length;

  useEffect(() => {
    setDisplayedChars(0);
  }, [text]);

  useEffect(() => {
    if (done) {
      onComplete?.();
      return;
    }
    const interval = setInterval(() => {
      setDisplayedChars((c) => {
        const next = Math.min(c + 1, text.length);
        if (next >= text.length) {
          clearInterval(interval);
        }
        return next;
      });
    }, 1000 / charsPerSecond);
    return () => clearInterval(interval);
  }, [text, charsPerSecond, done, onComplete]);

  return (
    <span>
      {text.slice(0, displayedChars)}
      {showCursor && !done && (
        <span className="animate-pulse text-[var(--muted)]">▊</span>
      )}
    </span>
  );
}
