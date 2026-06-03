'use client';

import 'leaflet-velocity/dist/leaflet-velocity.css';

import { useEffect, useState } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet-velocity';
import { WIND_COLOR_SCALE } from '@/lib/wind-legend';

type VelocityLayer = L.Layer & {
  addTo: (map: L.Map) => VelocityLayer;
};

export function WindLayer() {
  const map = useMap();
  const [data, setData] = useState<unknown[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/wind')
      .then((r) => {
        if (!r.ok) return null;
        return r.json();
      })
      .then((json) => {
        if (!cancelled && Array.isArray(json)) setData(json);
      })
      .catch((e) => console.error('[WindLayer]', e));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!data?.length) return;

    const velocityLayer = (
      L as typeof L & {
        velocityLayer: (opts: Record<string, unknown>) => VelocityLayer;
      }
    ).velocityLayer({
      displayValues: false,
      displayOptions: {
        velocityType: 'Wind',
        emptyString: 'No wind data',
        speedUnit: 'm/s',
      },
      data,
      maxVelocity: 30,
      velocityScale: 0.01,
      particleAge: 90,
      lineWidth: 1.5,
      particleMultiplier: 1 / 200,
      colorScale: [...WIND_COLOR_SCALE],
    });

    velocityLayer.addTo(map);
    return () => {
      map.removeLayer(velocityLayer);
    };
  }, [data, map]);

  return null;
}
