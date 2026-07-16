import type { AgentStepEvent } from './types';

export type StreamSseOptions = {
  url: string;
  method?: 'GET' | 'POST';
  headers?: Record<string, string>;
  body?: BodyInit | null;
  signal?: AbortSignal;
  onStep: (event: AgentStepEvent) => void;
  onDone?: () => void;
  onError?: (err: Error) => void;
};

/**
 * Consume a text/event-stream response and invoke onStep for each
 * `event: step` + `data: {...}` block.
 */
export async function streamAgentSse(opts: StreamSseOptions): Promise<void> {
  const {
    url,
    method = 'GET',
    headers,
    body,
    signal,
    onStep,
    onDone,
    onError,
  } = opts;

  try {
    const res = await fetch(url, { method, headers, body, signal });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`SSE ${res.status}: ${text || res.statusText}`);
    }
    if (!res.body) {
      throw new Error('SSE response has no body');
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sep: number;
      while ((sep = buffer.indexOf('\n\n')) !== -1) {
        const raw = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const event = parseSseBlock(raw);
        if (event) onStep(event);
      }
    }

    if (buffer.trim()) {
      const event = parseSseBlock(buffer);
      if (event) onStep(event);
    }
    onDone?.();
  } catch (err) {
    if (signal?.aborted) {
      onDone?.();
      return;
    }
    onError?.(err instanceof Error ? err : new Error(String(err)));
  }
}

function parseSseBlock(raw: string): AgentStepEvent | null {
  let eventName = 'message';
  const dataLines: string[] = [];
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim());
    }
  }
  if (eventName !== 'step' || dataLines.length === 0) return null;
  try {
    return JSON.parse(dataLines.join('\n')) as AgentStepEvent;
  } catch {
    return null;
  }
}
