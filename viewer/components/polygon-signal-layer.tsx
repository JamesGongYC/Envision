'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import { GeoJSON, useMap, useMapEvents } from 'react-leaflet';
import type { LayerQueryConfig } from '@/lib/layer-config';
import type { GeoJSONFeatureCollection } from '@/lib/signal-queries';
import { POLYGON_STYLES } from '@/lib/signal-styling';
import { useLayerTruncation } from '@/components/layer-truncation-provider';
import type { LayerId } from '@/lib/layer-state';

const DEBOUNCE_MS = 250;
const POLYGONS_PANE = 'polygonsPane';

function boundsToParam(bounds: L.LatLngBounds): string {
  const sw = bounds.getSouthWest();
  const ne = bounds.getNorthEast();
  return `${sw.lng},${sw.lat},${ne.lng},${ne.lat}`;
}

function dynamicOpacity(baseOpacity: number, zoom: number): number {
  return Math.max(0.05, baseOpacity - Math.max(0, 4 - zoom) * 0.05);
}

function polygonPopup(props: Record<string, unknown>): string {
  const source = String(props.source ?? '');
  const signalType = String(props.signal_type ?? '');
  const payload = props.payload as Record<string, unknown> | undefined;
  const lines = [`<strong>${source}</strong>`, signalType];
  if (payload?.region) lines.push(`Region: ${payload.region}`);
  if (payload?.event) lines.push(String(payload.event));
  return lines.join('<br/>');
}

export function PolygonSignalLayer({
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
  const [zoom, setZoom] = useState(map.getZoom());
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const baseStyle =
    POLYGON_STYLES[config.layerId] ?? POLYGON_STYLES.ecmwf_fire_weather_grid;
  const canvasRenderer = useMemo(() => L.canvas({ padding: 0.5 }), []);

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
        console.error(`[PolygonSignalLayer ${config.layerId}]`, e);
      }
    }
  }, [map, config.layerId, setTruncation]);

  const scheduleFetch = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => void fetchLayer(), DEBOUNCE_MS);
  }, [fetchLayer]);

  useMapEvents({
    moveend: () => {
      setZoom(map.getZoom());
      scheduleFetch();
    },
    zoomend: () => {
      setZoom(map.getZoom());
      scheduleFetch();
    },
  });

  useEffect(() => {
    scheduleFetch();
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      abortRef.current?.abort();
      setTruncation(config.layerId as LayerId, null);
    };
  }, [scheduleFetch, config.layerId, setTruncation]);

  if (!collection?.features.length) return null;

  const fillOpacity = dynamicOpacity(baseStyle.opacity, zoom);

  return (
    <GeoJSON
      key={`${config.layerId}-${collection.features.length}-${zoom}-${pulsing ? 'pulse' : 'idle'}`}
      data={collection as GeoJSON.GeoJsonObject}
      pane={POLYGONS_PANE}
      eventHandlers={{
        add: (e) => {
          const gj = e.target as L.GeoJSON;
          const opts = gj.options as L.PathOptions & { renderer?: L.Renderer };
          opts.renderer = canvasRenderer;
          gj.eachLayer((child) => {
            const path = child as L.Path;
            if (path.options) {
              path.options.renderer = canvasRenderer;
            }
          });
        },
      }}
      style={() => ({
        color: baseStyle.stroke,
        fillColor: baseStyle.fill,
        fillOpacity,
        weight: baseStyle.weight,
        opacity: Math.min(0.85, fillOpacity + 0.1),
        className: pulsing ? 'envision-layer-pulse' : undefined,
      })}
      onEachFeature={(feature, layer) => {
        const props = (feature.properties ?? {}) as Record<string, unknown>;
        layer.bindPopup(polygonPopup(props));
      }}
    />
  );
}
