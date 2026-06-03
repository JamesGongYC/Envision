import { NextResponse } from 'next/server';
import { groupContributingSignals } from '@/lib/group-contributing-signals';
import { getContributingSignals, getForecast } from '@/lib/queries';

function isUuidLike(v: string): boolean {
  return /^[0-9a-fA-F-]{20,}$/.test(v);
}

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> }
) {
  const { id } = await context.params;
  if (!isUuidLike(id)) {
    return NextResponse.json({ error: 'invalid id' }, { status: 400 });
  }

  try {
    const forecast = await getForecast(id);
    if (!forecast) {
      return NextResponse.json({ error: 'not found' }, { status: 404 });
    }

    const signals = await getContributingSignals(
      forecast.contributing_signal_ids ?? []
    );
    const groups = groupContributingSignals(signals);

    return NextResponse.json({
      groups,
      total: forecast.contributing_signal_ids?.length ?? 0,
      loaded: signals.length,
    });
  } catch (e) {
    console.error('[api/forecast/contributing-signals]', e);
    return NextResponse.json({ error: 'query failed' }, { status: 500 });
  }
}
