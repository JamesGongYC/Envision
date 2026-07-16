import 'server-only';

/** Base URL of the Modal ASGI agent API (no trailing slash). */
export function agentApiBaseUrl(): string {
  const url = process.env.ENVISION_AGENT_API_URL?.replace(/\/$/, '');
  if (!url) {
    throw new Error('ENVISION_AGENT_API_URL is not set');
  }
  return url;
}

export function operatorToken(): string | null {
  return process.env.ENVISION_OPERATOR_TOKEN || null;
}

/** Proxy an upstream SSE response through to the Next.js client. */
export function proxySseResponse(upstream: Response): Response {
  if (!upstream.ok || !upstream.body) {
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { 'Content-Type': 'application/json' },
    });
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}
