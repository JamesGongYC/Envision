'use client';

import { useEffect } from 'react';
import { useMap } from 'react-leaflet';

/** Register Leaflet panes before any layer references them. */
export function MapPanes() {
  const map = useMap();

  useEffect(() => {
    if (!map.getPane('signalsPane')) {
      map.createPane('signalsPane');
      map.getPane('signalsPane')!.style.zIndex = '400';
    }
    if (!map.getPane('polygonsPane')) {
      map.createPane('polygonsPane');
      map.getPane('polygonsPane')!.style.zIndex = '500';
    }
    if (!map.getPane('forecastsPane')) {
      map.createPane('forecastsPane');
      map.getPane('forecastsPane')!.style.zIndex = '600';
    }
  }, [map]);

  return null;
}
