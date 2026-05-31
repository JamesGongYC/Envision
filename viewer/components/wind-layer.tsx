'use client';

import 'leaflet-velocity/dist/leaflet-velocity.css';

import { useEffect, useState } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet-velocity';

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
      displayValues: true,
      displayOptions: {
        velocityType: 'Wind',
        position: 'bottomleft',
        emptyString: 'No wind data',
        speedUnit: 'm/s',
      },
      data,
      maxVelocity: 30,
      velocityScale: 0.01,
      particleAge: 90,
      lineWidth: 1.5,
      particleMultiplier: 1 / 200,
      colorScale: [
        'rgb(36,104,180)',
        'rgb(60,157,194)',
        'rgb(128,205,193)',
        'rgb(151,218,168)',
        'rgb(198,231,181)',
        'rgb(238,247,217)',
        'rgb(255,238,159)',
        'rgb(252,217,125)',
        'rgb(255,182,100)',
        'rgb(252,150,75)',
        'rgb(250,112,52)',
        'rgb(245,64,32)',
      ],
    });

    velocityLayer.addTo(map);
    return () => {
      map.removeLayer(velocityLayer);
    };
  }, [data, map]);

  return null;
}
