import { NextResponse } from 'next/server';
import { agentApiBaseUrl, proxySseResponse } from '@/lib/agent-api';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ id: string }> }
) {
  const { id } = await ctx.params;
  if (!/^[0-9a-fA-F-]{20,}$/.test(id)) {
    return NextResponse.json({ error: 'invalid run id' }, { status: 404 });
  }

  let base: string;
  try {
    base = agentApiBaseUrl();
  } catch {
    return NextResponse.json(
      { error: 'ENVISION_AGENT_API_URL not set' },
      { status: 500 }
    );
  }

  const upstream = await fetch(`${base}/agent/run/${id}/replay`, {
    method: 'GET',
    headers: { Accept: 'text/event-stream' },
  });

  if (upstream.status === 404) {
    return NextResponse.json({ error: 'agent_run not found' }, { status: 404 });
  }

  return proxySseResponse(upstream);
}
