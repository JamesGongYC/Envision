'use client';

import { useEffect } from 'react';

/** Measures #site-chrome and sets --chrome on :root for snap/map height calcs. */
export function ChromeHeight() {
  useEffect(() => {
    const el = document.getElementById('site-chrome');
    if (!el) return;

    const set = () => {
      document.documentElement.style.setProperty(
        '--chrome',
        `${el.offsetHeight}px`
      );
    };

    set();
    const ro = new ResizeObserver(set);
    ro.observe(el);
    window.addEventListener('resize', set);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', set);
    };
  }, []);

  return null;
}
