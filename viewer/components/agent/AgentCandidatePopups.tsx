'use client';

import { useEffect, useRef } from 'react';
import { CircleMarker, Popup } from 'react-leaflet';
import type { CircleMarker as LeafletCircleMarker } from 'leaflet';
import { ProducerBadge } from '@/components/producer-badge';
import type { AgentEmitCandidate } from '@/lib/types';

function locationToLatLng(
  geom: GeoJSON.Geometry | null
): [number, number] | null {
  if (!geom) return null;
  if (geom.type === 'Point') {
    const [lon, lat] = geom.coordinates;
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    return [lat, lon];
  }
  if (geom.type === 'Polygon' && geom.coordinates[0]?.length) {
    const ring = geom.coordinates[0];
    let sumLon = 0;
    let sumLat = 0;
    for (const [lon, lat] of ring) {
      sumLon += lon;
      sumLat += lat;
    }
    return [sumLat / ring.length, sumLon / ring.length];
  }
  if (geom.type === 'MultiPolygon' && geom.coordinates[0]?.[0]?.length) {
    const ring = geom.coordinates[0][0];
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

function CandidateMarker({ candidate }: { candidate: AgentEmitCandidate }) {
  const position = locationToLatLng(candidate.location);
  const markerRef = useRef<LeafletCircleMarker | null>(null);

  useEffect(() => {
    const marker = markerRef.current;
    if (!marker) return;
    marker.openPopup();
  }, [candidate.id]);

  if (!position) return null;

  const prob =
    candidate.probability != null && Number.isFinite(candidate.probability)
      ? `${Math.round(candidate.probability * 100)}%`
      : '—';

  return (
    <CircleMarker
      ref={markerRef}
      center={position}
      radius={8}
      pane="forecastsPane"
      pathOptions={{
        color: '#e8e8ea',
        fillColor: '#e8e8ea',
        fillOpacity: 0.85,
        weight: 2,
        opacity: 1,
      }}
    >
      <Popup autoClose={false} closeOnClick={false} autoPan={false}>
        <div className="text-xs space-y-1.5 min-w-[160px] rounded bg-[var(--surface)] p-2 text-[var(--foreground)]">
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium capitalize">
              {candidate.hazard || 'forecast'}
            </span>
            <ProducerBadge producer="agent" />
          </div>
          <div className="text-[var(--muted)]">p ≈ {prob}</div>
          {candidate.skill && (
            <div className="font-[family-name:var(--font-mono)] text-[10px] text-[var(--muted)]">
              {candidate.skill}
            </div>
          )}
          {candidate.label && (
            <div className="leading-snug text-[var(--foreground)]">
              {candidate.label}
            </div>
          )}
        </div>
      </Popup>
    </CircleMarker>
  );
}

/** Anchored emit popups; persist until parent clears candidates. */
export function AgentCandidatePopups({
  candidates,
}: {
  candidates: AgentEmitCandidate[];
}) {
  if (candidates.length === 0) return null;
  return (
    <>
      {candidates.map((c) => (
        <CandidateMarker key={c.id} candidate={c} />
      ))}
    </>
  );
}
