import { ScrollArrow } from '@/components/scroll-arrow';
import { LANDING_HERO_ID } from '@/lib/landing-scroll';

const GHOST_SOURCE = `"""
wildfire_risk_elevated — Envision detection skill (Day 3, v1).

Reads recent FIRMS hotspots and active NWS fire-weather alerts from signals,
clusters the hotspots with DBSCAN (eps=10km, min_samples=5), keeps clusters
whose convex hull intersects an active alert polygon, and writes one
Forecast row per surviving cluster.
"""

def run(now: datetime, db: Connection) -> int:
    """Emit elevated wildfire risk forecasts from clustered hotspots."""
    ...`;

export function Hero() {
  return (
    <section
      id={LANDING_HERO_ID}
      className="landing-snap-pane relative bg-[var(--background)] overflow-hidden"
    >
      <pre
        className="pointer-events-none absolute inset-0 p-8 text-[10px] sm:text-xs leading-relaxed font-[family-name:var(--font-mono)] text-[var(--foreground)] opacity-[0.04] whitespace-pre-wrap select-none overflow-hidden"
        aria-hidden
      >
        {GHOST_SOURCE}
      </pre>

      <div className="relative z-10 flex h-full flex-col px-6 sm:px-10 lg:px-16 pt-12 sm:pt-16 pb-20">
        <div className="flex-1">
          <h1 className="font-[family-name:var(--font-display)] font-bold text-[clamp(3.5rem,12vw,9rem)] leading-[0.88] tracking-tight text-[var(--foreground)]">
            ENVISION
          </h1>
          <p className="mt-4 font-[family-name:var(--font-mono)] text-sm sm:text-base text-[var(--muted)] tracking-widest uppercase">
            WILDFIRE · CYCLONE
          </p>
          <p className="mt-1 font-[family-name:var(--font-mono)] text-sm sm:text-base text-[var(--muted)] tracking-widest uppercase">
            GLOBAL · SELF-EVOLVING
          </p>
        </div>

        <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-12 pb-4">
          <p className="max-w-md font-[family-name:var(--font-mono)] text-[10px] sm:text-xs uppercase tracking-[0.2em] leading-relaxed text-[var(--muted)]">
            An experimental self-evolving agent monitoring global wildfire and
            tropical-cyclone risk.
          </p>
          <p
            className="font-[family-name:var(--font-mono)] text-[clamp(3rem,10vw,6rem)] font-medium leading-none text-[var(--foreground)] sm:text-right"
            aria-hidden
          >
            GLOBAL
          </p>
        </div>
      </div>

      <ScrollArrow />
    </section>
  );
}
