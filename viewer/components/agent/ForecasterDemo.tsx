'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import ForecastMap from '@/components/forecast-map';
import { AgentTranscript } from '@/components/agent/AgentTranscript';
import { FireControl } from '@/components/agent/FireControl';
import { useRunPlayer } from '@/components/agent/RunPlayer';
import { streamAgentSse } from '@/lib/sse';
import type { AgentStepEvent, Forecast } from '@/lib/types';

type ForecasterDemoProps = {
  canFire: boolean;
  lastRunId: string | null;
  forecasts: Forecast[];
};

export function ForecasterDemo({
  canFire,
  lastRunId,
  forecasts,
}: ForecasterDemoProps) {
  const [buffer, setBuffer] = useState<AgentStepEvent[]>([]);
  const [sessionId, setSessionId] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<'idle' | 'live' | 'replay'>('idle');
  const abortRef = useRef<AbortController | null>(null);

  const player = useRunPlayer(buffer, { resetKey: sessionId });

  const handleStep = useCallback((event: AgentStepEvent) => {
    setBuffer((prev) => [...prev, event]);
  }, []);

  const startStream = useCallback(
    async (url: string, method: 'GET' | 'POST', nextMode: 'live' | 'replay') => {
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;
      setBuffer([]);
      setSessionId((n) => n + 1);
      setError(null);
      setBusy(true);
      setMode(nextMode);
      await streamAgentSse({
        url,
        method,
        signal: ac.signal,
        onStep: handleStep,
        onDone: () => {
          setBusy(false);
        },
        onError: (err) => {
          setError(err.message);
          setBusy(false);
        },
      });
    },
    [handleStep]
  );

  useEffect(() => {
    if (!canFire && lastRunId) {
      void startStream(
        `/api/agent/run/${lastRunId}/replay`,
        'GET',
        'replay'
      );
    }
    return () => {
      abortRef.current?.abort();
    };
    // Auto-replay once on mount for public surface.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canFire, lastRunId]);

  const agentForecasts = forecasts.filter((f) => f.producer === 'agent');
  const streaming = busy || player.playing;

  return (
    <section className="space-y-4">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h2 className="font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight">
            Forecaster
          </h2>
          <p className="mt-1 text-sm font-[family-name:var(--font-mono)] text-[var(--muted)] max-w-xl">
            Live ReAct transcript with map spotlight. Public surface replays the
            last real run; operators can fire a new production cycle.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {mode !== 'idle' && (
            <span className="text-[10px] uppercase tracking-wider font-[family-name:var(--font-mono)] text-[var(--muted)]">
              {mode}
              {busy
                ? ' · streaming'
                : player.playing
                  ? ' · playing'
                  : ' · done'}
            </span>
          )}
          {canFire && (
            <FireControl
              busy={busy || player.playing}
              onFire={() =>
                void startStream('/api/agent/forecaster/fire', 'POST', 'live')
              }
            />
          )}
          {!canFire && lastRunId && (
            <button
              type="button"
              disabled={busy || player.playing}
              onClick={() =>
                void startStream(
                  `/api/agent/run/${lastRunId}/replay`,
                  'GET',
                  'replay'
                )
              }
              className="font-[family-name:var(--font-mono)] text-xs uppercase tracking-wider px-3 py-2 border border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40"
            >
              Replay last run
            </button>
          )}
        </div>
      </div>

      {error && (
        <p className="text-xs font-[family-name:var(--font-mono)] text-red-400">
          {error}
        </p>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <AgentTranscript
          steps={player.visibleSteps}
          streaming={streaming}
          variant="forecaster"
        />
        <div className="border border-[var(--border)] overflow-hidden min-h-[20rem]">
          <ForecastMap
            forecasts={
              agentForecasts.length > 0 ? agentForecasts : forecasts.slice(0, 40)
            }
            height="20rem"
            geoFocus={player.geoFocus}
            pulsingLayers={player.pulsingLayers}
            candidates={player.candidates}
          />
        </div>
      </div>
    </section>
  );
}
