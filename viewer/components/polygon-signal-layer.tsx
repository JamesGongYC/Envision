'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import { GeoJSON, useMap, useMapEvents } from 'react-leaflet';
import type { LayerQueryConfig } from '@/lib/layer-config';
import type { GeoJSONFeatureCollection } from '@/lib/signal-queries';
import { POLYGON_STYLES } from '@/lib/signal-styling';
import { useLayerTruncation } from '@/components/layer-truncation-provider';
import type { LayerId } from '@/lib/layer-state';

const DEBOUNCE_MS = 250;
const MIN_ZOOM = 4;

function boundsToParam(bounds: L.LatLngBounds): string {
  const sw = bounds.getSouthWest();
  const ne = bounds.getNorthEast();
  return `${sw.lng},${sw.lat},${ne.lng},${ne.lat}`;
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

export function PolygonSignalLayer({ config }: { config: LayerQueryConfig }) {
  const map = useMap();
  const { setTruncation } = useLayerTruncation();
  const [collection, setCollection] = useState<GeoJSONFeatureCollection | null>(
    null
  );
  const [zoom, setZoom] = useState(map.getZoom());
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const style = POLYGON_STYLES[config.layerId] ?? POLYGON_STYLES.ecmwf_fire_weather_grid;

  const fetchLayer = useCallback(async () => {
    if (map.getZoom() < MIN_ZOOM) {
      setCollection(null);
      setTruncation(config.layerId, null);
      return;
    }
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

  if (zoom < MIN_ZOOM || !collection?.features.length) return null;

  return (
    <GeoJSON
      key={`${config.layerId}-${collection.features.length}`}
      data={collection as GeoJSON.GeoJsonObject}
      style={() => ({
        color: style.stroke,
        fillColor: style.fill,
        fillOpacity: style.opacity,
        weight: style.weight,
        opacity: 0.85,
      })}
      onEachFeature={(feature, layer) => {
        const props = (feature.properties ?? {}) as Record<string, unknown>;
        layer.bindPopup(polygonPopup(props));
      }}
    />
  );
}
