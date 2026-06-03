'use client';

import {
  autoUpdate,
  flip,
  offset,
  shift,
  size,
  useFloating,
  type VirtualElement,
} from '@floating-ui/react';
import type { LatLng, Map as LeafletMap } from 'leaflet';
import { useEffect, useLayoutEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMap } from 'react-leaflet';
import { ForecastDropdown } from '@/components/forecast-dropdown';
import type { Forecast } from '@/lib/types';

const MAP_PADDING = 8;

function buildVirtualReference(
  map: LeafletMap,
  latLng: LatLng
): VirtualElement {
  return {
    getBoundingClientRect() {
      const point = map.latLngToContainerPoint(latLng);
      const mapRect = map.getContainer().getBoundingClientRect();
      const x = mapRect.left + point.x;
      const y = mapRect.top + point.y;
      return {
        width: 0,
        height: 0,
        x,
        y,
        top: y,
        left: x,
        right: x,
        bottom: y,
      } as DOMRect;
    },
  };
}

export function ForecastMapPopover({
  forecast,
  latLng,
}: {
  forecast: Forecast;
  latLng: LatLng;
}) {
  const map = useMap();
  const [portalRoot, setPortalRoot] = useState<HTMLElement | null>(null);

  useEffect(() => {
    setPortalRoot(map.getContainer());
  }, [map]);

  const boundary = portalRoot;

  const virtualReference = useMemo(
    () => buildVirtualReference(map, latLng),
    [map, latLng]
  );

  const { refs, floatingStyles, placement, update } = useFloating({
    open: true,
    placement: 'right',
    strategy: 'fixed',
    middleware: [
      offset(12),
      flip({ fallbackPlacements: ['left', 'right'] }),
      shift({
        boundary: boundary ?? undefined,
        padding: MAP_PADDING,
      }),
      size({
        boundary: boundary ?? undefined,
        padding: MAP_PADDING,
        apply({ availableHeight, availableWidth, elements }) {
          Object.assign(elements.floating.style, {
            maxHeight: `${Math.max(120, availableHeight)}px`,
            maxWidth: `${Math.max(240, availableWidth)}px`,
          });
        },
      }),
    ],
    whileElementsMounted: (reference, floating, updateFn) =>
      autoUpdate(reference, floating, updateFn, {
        animationFrame: true,
        elementResize: true,
      }),
  });

  useLayoutEffect(() => {
    refs.setReference(virtualReference);
    update();
  }, [refs, virtualReference, update]);

  useEffect(() => {
    const refresh = () => update();
    map.on('move zoom resize moveend zoomend', refresh);
    return () => {
      map.off('move zoom resize moveend zoomend', refresh);
    };
  }, [map, update]);

  if (!portalRoot) return null;

  const side = placement.startsWith('left') ? 'left' : 'right';

  return createPortal(
    <div
      ref={refs.setFloating}
      style={{ ...floatingStyles, zIndex: 1000 }}
      className={`forecast-map-popover forecast-map-popover--${side}`}
      role="dialog"
      aria-label="Forecast details"
    >
      <ForecastDropdown forecast={forecast} />
    </div>,
    portalRoot
  );
}
