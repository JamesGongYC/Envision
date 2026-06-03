'use client';

import { useEffect } from 'react';

/** Measures #map-controls-bar and sets --control-bar on :root for layout calcs. */
export function ControlBarHeight() {
  useEffect(() => {
    const el = document.getElementById('map-controls-bar');
    if (!el) return;

    const set = () => {
      document.documentElement.style.setProperty(
        '--control-bar',
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
