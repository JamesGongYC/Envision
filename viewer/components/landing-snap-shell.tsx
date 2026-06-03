'use client';

import { useCallback, useEffect, useRef, type ReactNode } from 'react';
import {
  FORECASTS_MAP_ID,
  LANDING_HERO_ID,
  scrollToHero,
  scrollToMap,
} from '@/lib/landing-scroll';

export function LandingSnapShell({ children }: { children: ReactNode }) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const lockRef = useRef(false);

  const releaseLock = useCallback(() => {
    lockRef.current = false;
  }, []);

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;

    scroller.addEventListener('scrollend', releaseLock);
    return () => scroller.removeEventListener('scrollend', releaseLock);
  }, [releaseLock]);

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;

    const hero = document.getElementById(LANDING_HERO_ID);
    const map = document.getElementById(FORECASTS_MAP_ID);
    if (!hero || !map) return;

    const onWheel = (e: WheelEvent) => {
      if (lockRef.current) {
        e.preventDefault();
        return;
      }

      const target = e.target as HTMLElement;
      if (target.closest('.leaflet-container')) return;

      const heroRect = hero.getBoundingClientRect();
      const mapRect = map.getBoundingClientRect();
      const chrome =
        parseFloat(
          getComputedStyle(document.documentElement).getPropertyValue('--chrome')
        ) || 0;

      const heroVisible =
        heroRect.top >= chrome - 2 && heroRect.top < window.innerHeight * 0.5;
      const mapAtTop =
        Math.abs(mapRect.top - chrome) < 8 || mapRect.top <= chrome + 4;

      if (e.deltaY > 0 && heroVisible && !mapAtTop) {
        e.preventDefault();
        lockRef.current = true;
        scrollToMap();
        return;
      }

      if (e.deltaY < 0 && mapAtTop && scroller.scrollTop > 0) {
        e.preventDefault();
        lockRef.current = true;
        scrollToHero();
      }
    };

    const onKeyDown = (e: KeyboardEvent) => {
      if (lockRef.current) return;
      const down =
        e.key === 'ArrowDown' ||
        e.key === 'PageDown' ||
        e.key === ' ' ||
        e.key === 'End';
      const up = e.key === 'ArrowUp' || e.key === 'PageUp' || e.key === 'Home';
      if (!down && !up) return;

      const heroRect = hero.getBoundingClientRect();
      const mapRect = map.getBoundingClientRect();
      const chrome =
        parseFloat(
          getComputedStyle(document.documentElement).getPropertyValue('--chrome')
        ) || 0;
      const heroVisible = heroRect.top >= chrome - 2 && heroRect.top < 400;
      const mapAtTop = Math.abs(mapRect.top - chrome) < 12;

      if (down && heroVisible && !mapAtTop) {
        e.preventDefault();
        lockRef.current = true;
        scrollToMap();
      } else if (up && mapAtTop) {
        e.preventDefault();
        lockRef.current = true;
        scrollToHero();
      }
    };

    scroller.addEventListener('wheel', onWheel, { passive: false });
    window.addEventListener('keydown', onKeyDown);
    return () => {
      scroller.removeEventListener('wheel', onWheel);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, []);

  return (
    <div ref={scrollerRef} className="landing-snap flex-1 min-h-0">
      {children}
    </div>
  );
}
