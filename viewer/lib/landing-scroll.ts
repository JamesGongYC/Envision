export const LANDING_HERO_ID = 'landing-hero';
export const FORECASTS_MAP_ID = 'forecasts-map';

export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function scrollToSection(id: string) {
  const el = document.getElementById(id);
  if (!el) return;
  el.scrollIntoView({
    behavior: prefersReducedMotion() ? 'auto' : 'smooth',
    block: 'start',
  });
}

export function scrollToMap() {
  scrollToSection(FORECASTS_MAP_ID);
}

export function scrollToHero() {
  scrollToSection(LANDING_HERO_ID);
}
