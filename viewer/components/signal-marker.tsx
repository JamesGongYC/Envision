'use client';

import { CircleMarker, Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import {
  applyRecencyFade,
  styleKeyForLayer,
  SIGNAL_STYLES,
  type SignalStyle,
} from '@/lib/signal-styling';
import { signalSourceUrl } from '@/lib/signal-sources';
import type { Signal } from '@/lib/types';

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function divIcon(
  style: SignalStyle,
  opacity: number,
  pulsing: boolean
): L.DivIcon {
  const size = style.radius * 2;
  let inner = '';
  if (style.shape === 'circle') {
    inner = `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${style.fillColor};border:2px solid ${style.color};opacity:${opacity}"></div>`;
  } else if (style.shape === 'square') {
    inner = `<div style="width:${size}px;height:${size}px;background:${style.fillColor};border:2px solid ${style.color};opacity:${opacity}"></div>`;
  } else if (style.shape === 'diamond') {
    inner = `<div style="width:${size}px;height:${size}px;background:${style.fillColor};border:2px solid ${style.color};opacity:${opacity};transform:rotate(45deg)"></div>`;
  } else {
    inner = `<div style="color:${style.color};font-size:${size}px;line-height:1;opacity:${opacity};font-weight:bold">+</div>`;
  }
  return L.divIcon({
    className: `envision-signal-icon${pulsing ? ' envision-layer-pulse' : ''}`,
    html: inner,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function popupBody(
  props: Record<string, unknown>,
  layerId: string
): React.ReactNode {
  const source = String(props.source ?? '');
  const timestamp = String(props.timestamp ?? '');
  const signalType = String(props.signal_type ?? '');
  const payload = (props.payload ?? {}) as Record<string, unknown>;
  const disasterClass = props.disaster_class
    ? String(props.disaster_class)
    : null;
  const severity = props.severity ? String(props.severity) : null;

  const pseudoSignal = {
    id: String(props.id ?? ''),
    timestamp,
    source,
    signal_type: signalType,
    geometry: null,
    payload,
    ingested_at: timestamp,
  } as Signal;

  const link = signalSourceUrl(pseudoSignal);

  return (
    <div className="text-xs space-y-1 min-w-[180px]">
      <div className="font-medium text-neutral-900">{source}</div>
      <div className="text-neutral-600">{signalType}</div>
      {disasterClass && (
        <div className="text-neutral-600">Class: {disasterClass}</div>
      )}
      {severity && <div className="text-neutral-600">Severity: {severity}</div>}
      <div className="text-neutral-500">{formatTime(timestamp)}</div>
      {payload.region != null && (
        <div className="text-neutral-600">Region: {String(payload.region)}</div>
      )}
      {payload.name != null && (
        <div className="text-neutral-600">{String(payload.name)}</div>
      )}
      {payload.event != null && (
        <div className="text-neutral-600">{String(payload.event)}</div>
      )}
      {link && (
        <a
          href={link}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-600 hover:underline block pt-1"
        >
          Source
        </a>
      )}
    </div>
  );
}

export function SignalFeatureMarker({
  feature,
  layerId,
  pane,
  renderer,
  pulsing = false,
}: {
  feature: GeoJSON.Feature;
  layerId: string;
  pane?: string;
  renderer?: L.Renderer;
  pulsing?: boolean;
}) {
  const props = (feature.properties ?? {}) as Record<string, unknown>;
  const source = String(props.source ?? '');
  const styleKey = styleKeyForLayer(layerId, source);
  const style = SIGNAL_STYLES[styleKey];
  const timestamp = String(props.timestamp ?? new Date().toISOString());
  const opacity = applyRecencyFade(style.opacity, timestamp);

  const position = geometryToLatLngFromFeature(feature);
  if (!position) return null;

  if (style.shape === 'circle') {
    return (
      <CircleMarker
        center={position}
        radius={style.radius}
        pane={pane}
        renderer={renderer}
        pathOptions={{
          color: style.color,
          fillColor: style.fillColor,
          fillOpacity: opacity,
          weight: style.weight,
          opacity,
          className: pulsing ? 'envision-layer-pulse' : undefined,
        }}
      >
        <Popup>{popupBody(props, layerId)}</Popup>
      </CircleMarker>
    );
  }

  return (
    <Marker
      position={position}
      icon={divIcon(style, opacity, pulsing)}
      pane={pane}
    >
      <Popup>{popupBody(props, layerId)}</Popup>
    </Marker>
  );
}

function geometryToLatLngFromFeature(
  feature: GeoJSON.Feature
): [number, number] | null {
  if (!feature.geometry) return null;
  const g = feature.geometry;
  if (g.type === 'Point') {
    const [lon, lat] = g.coordinates;
    return [lat, lon];
  }
  if (g.type === 'Polygon' && g.coordinates[0]?.length) {
    const ring = g.coordinates[0];
    let sumLon = 0;
    let sumLat = 0;
    for (const [lon, lat] of ring) {
      sumLon += lon;
      sumLat += lat;
    }
    return [sumLat / ring.length, sumLon / ring.length];
  }
  return null;
}
