'use client';

import { useLayerVisibility } from '@/components/layer-visibility-provider';
import {
  SIGNAL_STYLES,
  type SignalStyle,
  type SignalStyleKey,
} from '@/lib/signal-styling';
import { WIND_COLOR_SCALE } from '@/lib/wind-legend';

export type MapLegendProps = {
  forecastCount: number;
  wildfireCount: number;
  typhoonCount: number;
};

const SIGNAL_LEGEND: { key: SignalStyleKey; label: string }[] = [
  { key: 'hotspot', label: 'Hotspot' },
  { key: 'fire_warning', label: 'Fire warning' },
  { key: 'fire_weather', label: 'Fire weather' },
  { key: 'cyclone_nhc', label: 'Cyclone (NHC)' },
  { key: 'cyclone_jtwc', label: 'Cyclone (JTWC)' },
  { key: 'cyclone_feature', label: 'Cyclone feature' },
  { key: 'gdacs', label: 'GDACS' },
];

function SignalSwatch({ style }: { style: SignalStyle }) {
  const base =
    'inline-block shrink-0 border border-[var(--border)]';
  if (style.shape === 'cross') {
    return (
      <span
        className={`${base} h-3 w-3 relative`}
        style={{ background: 'transparent' }}
        aria-hidden
      >
        <span
          className="absolute inset-0 m-auto h-px w-full"
          style={{ background: style.color, top: '50%' }}
        />
        <span
          className="absolute inset-0 m-auto w-px h-full"
          style={{ background: style.color, left: '50%' }}
        />
      </span>
    );
  }
  return (
    <span
      className={`${base} ${style.shape === 'square' ? 'rounded-sm' : 'rounded-full'}`}
      style={{
        width: 10,
        height: 10,
        background: style.fillColor,
        borderColor: style.color,
      }}
      aria-hidden
    />
  );
}

export function MapLegend({
  forecastCount,
  wildfireCount,
  typhoonCount,
}: MapLegendProps) {
  const { uiVisibility } = useLayerVisibility();

  return (
    <div
      className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1.5 text-[10px] font-[family-name:var(--font-mono)] text-[var(--muted)]"
      aria-label="Map legend"
    >
      <span className="text-[var(--foreground)] whitespace-nowrap">
        {forecastCount} forecast{forecastCount === 1 ? '' : 's'}
        {forecastCount > 0 && (
          <span className="text-[var(--muted)]">
            {' '}
            · {wildfireCount} wildfire · {typhoonCount} typhoon
          </span>
        )}
      </span>

      <span className="flex items-center gap-1.5 whitespace-nowrap" title="Forecast probability">
        <span
          className="inline-block h-3 w-16 rounded-sm border border-[var(--border)]"
          style={{
            background:
              'linear-gradient(to right, rgba(220,38,38,0.15), rgba(220,38,38,0.95))',
          }}
          aria-hidden
        />
        Probability
      </span>

      <span className="flex items-center gap-1.5 whitespace-nowrap">
        <span className="inline-block h-3 w-3 rounded-sm border-2 border-red-600 bg-red-300/70" />
        Wildfire
      </span>
      <span className="flex items-center gap-1.5 whitespace-nowrap">
        <span className="inline-block h-3 w-3 rounded-sm border-2 border-blue-600 bg-blue-300/70" />
        Typhoon
      </span>

      {uiVisibility.signals &&
        SIGNAL_LEGEND.map(({ key, label }) => (
          <span key={key} className="flex items-center gap-1 whitespace-nowrap">
            <SignalSwatch style={SIGNAL_STYLES[key]} />
            {label}
          </span>
        ))}

      {uiVisibility.model_signals && (
        <span className="flex items-center gap-1.5 whitespace-nowrap">
          <span className="text-[var(--foreground)]">Wind m/s</span>
          <span
            className="inline-block h-2 w-20 rounded-sm border border-[var(--border)]"
            style={{
              background: `linear-gradient(to right, ${WIND_COLOR_SCALE.join(', ')})`,
            }}
            aria-hidden
          />
          <span>low → high</span>
        </span>
      )}
    </div>
  );
}
