'use client';

import { ControlBarHeight } from '@/components/control-bar-height';
import { MapLegend, type MapLegendProps } from '@/components/map-legend';
import {
  DETECTION_LAYER_IDS,
  LAYER_TREE,
  type LayerId,
} from '@/lib/layer-state';
import { LAYER_QUERY_CONFIG } from '@/lib/layer-config';
import { useLayerTruncation } from '@/components/layer-truncation-provider';
import { useLayerVisibility } from '@/components/layer-visibility-provider';

export function MapControlsBar(props: MapLegendProps) {
  const { uiVisibility, toggle } = useLayerVisibility();
  const { truncation } = useLayerTruncation();

  const detectionTruncations = DETECTION_LAYER_IDS.filter(
    (id) => uiVisibility.signals && truncation[id]?.truncated
  );

  return (
    <>
      <ControlBarHeight />
      <div
        id="map-controls-bar"
        className="shrink-0 w-full flex flex-col gap-1.5 border border-[var(--border)] rounded bg-[var(--surface)] px-3 py-2"
        aria-label="Map controls"
      >
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3 lg:gap-4">
          <div className="flex flex-col gap-1.5 min-w-0">
            <span className="text-[10px] font-[family-name:var(--font-mono)] uppercase tracking-wide text-[var(--muted)]">
              Layers
            </span>
            <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs font-[family-name:var(--font-mono)]">
              {LAYER_TREE.map((layer) => {
                const checked = uiVisibility[layer.id] === true;
                return (
                  <li key={layer.id}>
                    <label className="flex items-center gap-2 cursor-pointer whitespace-nowrap text-[var(--foreground)]">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(layer.id)}
                        className="cursor-pointer accent-white"
                      />
                      {layer.label}
                    </label>
                  </li>
                );
              })}
            </ul>
          </div>

          <div className="min-w-0 lg:border-l lg:border-[var(--border)] lg:pl-4 flex flex-col gap-1">
            <span className="text-[10px] font-[family-name:var(--font-mono)] uppercase tracking-wide text-[var(--muted)] lg:text-right">
              Legend
            </span>
            <MapLegend {...props} />
          </div>
        </div>

        {detectionTruncations.length > 0 && (
          <div className="text-[10px] text-[var(--muted)] font-[family-name:var(--font-mono)] border-t border-[var(--border)] pt-1.5 flex flex-wrap gap-x-3 gap-y-0.5">
            {detectionTruncations.map((layerId) => {
              const cap = truncation[layerId as LayerId];
              const config = LAYER_QUERY_CONFIG[layerId as LayerId];
              if (!cap?.truncated || !config) return null;
              return (
                <span key={layerId}>
                  {config.label}: {cap.returnedCount.toLocaleString()} of{' '}
                  {cap.totalCount.toLocaleString()}
                </span>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}
