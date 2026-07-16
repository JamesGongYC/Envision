import { NextResponse } from 'next/server';
import {
  agentApiBaseUrl,
  operatorToken,
  proxySseResponse,
} from '@/lib/agent-api';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function POST() {
  const token = operatorToken();
  if (!token) {
    return NextResponse.json(
      { error: 'operator fire not configured' },
      { status: 403 }
    );
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

  const upstream = await fetch(`${base}/agent/critic/fire`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'text/event-stream',
    },
  });

  return proxySseResponse(upstream);
}
