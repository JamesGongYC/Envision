import { gunzipSync } from 'node:zlib';
import { NextResponse } from 'next/server';
import { getLatestWindField } from '@/lib/wind-queries';

const CACHE =
  'public, max-age=21600, stale-while-revalidate=43200';

export async function GET() {
  try {
    const row = await getLatestWindField();
    if (!row) {
      return NextResponse.json(
        { error: 'no wind field available' },
        { status: 404 }
      );
    }

    const json = gunzipSync(row.data_compressed);
    return new NextResponse(json, {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': CACHE,
        'X-Wind-Valid-At': row.valid_at,
        'X-Wind-Size-Bytes': String(row.size_bytes),
      },
    });
  } catch (e) {
    console.error('[api/wind]', e);
    return NextResponse.json(
      { error: 'failed to load wind field' },
      { status: 500 }
    );
  }
}
