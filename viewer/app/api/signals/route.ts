import { NextResponse } from 'next/server';
import {
  getLayerQueryConfig,
  parseBBoxParam,
} from '@/lib/layer-config';
import {
  fetchGroundTruthAsGeoJSON,
  fetchSignalsAsGeoJSON,
} from '@/lib/signal-queries';

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const layerId = searchParams.get('layer_id');
  if (!layerId) {
    return NextResponse.json({ error: 'layer_id required' }, { status: 400 });
  }

  const config = getLayerQueryConfig(layerId);
  if (!config) {
    return NextResponse.json({ error: 'unknown layer_id' }, { status: 400 });
  }

  const bbox = parseBBoxParam(searchParams.get('bbox'));
  const sinceHours = Number.parseInt(searchParams.get('since_hours') ?? '24', 10);
  const since =
    Number.isFinite(sinceHours) && sinceHours > 0 ? sinceHours : 24;

  try {
    const collection =
      config.target === 'ground_truth'
        ? await fetchGroundTruthAsGeoJSON({
            sources: config.sources,
            bbox,
            sinceHours: since,
          })
        : await fetchSignalsAsGeoJSON({
            sources: config.sources,
            signalType: config.signalType,
            bbox,
            sinceHours: since,
          });

    return NextResponse.json(collection, {
      headers: {
        'Cache-Control': 'public, max-age=30, stale-while-revalidate=60',
      },
    });
  } catch (err) {
    console.error('[api/signals]', err);
    return NextResponse.json({ error: 'query failed' }, { status: 500 });
  }
}
