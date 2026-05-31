'use client';

import { useEffect, useState } from 'react';

export type TypingTextProps = {
  text: string;
  charsPerSecond?: number;
  showCursor?: boolean;
  skip?: boolean;
  onComplete?: () => void;
};

export function TypingText({
  text,
  charsPerSecond = 30,
  showCursor = true,
  skip = false,
  onComplete,
}: TypingTextProps) {
  const [displayedChars, setDisplayedChars] = useState(skip ? text.length : 0);
  const done = displayedChars >= text.length;

  useEffect(() => {
    if (skip) {
      setDisplayedChars(text.length);
      return;
    }
    setDisplayedChars(0);
  }, [text, skip]);

  useEffect(() => {
    if (skip || done) {
      if (done) onComplete?.();
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
  }, [text, charsPerSecond, skip, done, onComplete]);

  return (
    <span>
      {text.slice(0, displayedChars)}
      {showCursor && !done && !skip && (
        <span className="animate-pulse text-neutral-500">▊</span>
      )}
    </span>
  );
}
