'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import { useMap, useMapEvents } from 'react-leaflet';
import type { LayerId } from '@/lib/layer-state';
import type { LayerQueryConfig } from '@/lib/layer-config';
import type { GeoJSONFeatureCollection } from '@/lib/signal-queries';
import { useLayerTruncation } from '@/components/layer-truncation-provider';
import { SignalFeatureMarker } from '@/components/signal-marker';

const DEBOUNCE_MS = 250;
const SIGNALS_PANE = 'signalsPane';

function boundsToParam(bounds: L.LatLngBounds): string {
  const sw = bounds.getSouthWest();
  const ne = bounds.getNorthEast();
  return `${sw.lng},${sw.lat},${ne.lng},${ne.lat}`;
}

export function SignalLayer({
  config,
  pulsing = false,
}: {
  config: LayerQueryConfig;
  pulsing?: boolean;
}) {
  const map = useMap();
  const { setTruncation } = useLayerTruncation();
  const [collection, setCollection] = useState<GeoJSONFeatureCollection | null>(
    null
  );
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const canvasRenderer = useMemo(
    () => (config.useCanvas ? L.canvas({ padding: 0.5 }) : undefined),
    [config.useCanvas]
  );

  const fetchLayer = useCallback(async () => {
    const bounds = map.getBounds();
    const bbox = boundsToParam(bounds);
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    try {
      const url = `/api/signals?layer_id=${encodeURIComponent(config.layerId)}&bbox=${encodeURIComponent(bbox)}`;
      const res = await fetch(url, { signal: ac.signal });
      if (!res.ok) return;
      const data = (await res.json()) as GeoJSONFeatureCollection;
      setCollection(data);
      const meta = data.properties;
      if (meta?.truncated && meta.totalCount != null && meta.returnedCount != null) {
        setTruncation(config.layerId, {
          truncated: true,
          totalCount: meta.totalCount,
          returnedCount: meta.returnedCount,
        });
      } else {
        setTruncation(config.layerId, null);
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        console.error(`[SignalLayer ${config.layerId}]`, e);
      }
    }
  }, [map, config.layerId, setTruncation]);

  const scheduleFetch = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => void fetchLayer(), DEBOUNCE_MS);
  }, [fetchLayer]);

  useMapEvents({
    moveend: scheduleFetch,
    zoomend: scheduleFetch,
  });

  useEffect(() => {
    scheduleFetch();
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      abortRef.current?.abort();
      setTruncation(config.layerId as LayerId, null);
    };
  }, [scheduleFetch, config.layerId, setTruncation]);

  const features = collection?.features ?? [];
  if (features.length === 0) return null;

  return (
    <>
      {features.map((f) => (
        <SignalFeatureMarker
          key={String(f.id ?? `${f.properties?.id}`)}
          feature={f}
          layerId={config.layerId}
          pane={SIGNALS_PANE}
          renderer={canvasRenderer}
          pulsing={pulsing}
        />
      ))}
    </>
  );
}
