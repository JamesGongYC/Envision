'use client';

import { useCallback, useRef, useState } from 'react';
import ForecastMap from '@/components/forecast-map';
import { AgentTranscript } from '@/components/agent/AgentTranscript';
import { FireControl } from '@/components/agent/FireControl';
import { useRunPlayer } from '@/components/agent/RunPlayer';
import {
  pickInitialVariant,
  pickNextVariant,
} from '@/fixtures/agent-demo';
import { variantToEvents } from '@/lib/demo-fixtures';
import type { AgentStepEvent, Forecast } from '@/lib/types';

type ForecasterDemoProps = {
  forecasts: Forecast[];
};

export function ForecasterDemo({ forecasts }: ForecasterDemoProps) {
  const [buffer, setBuffer] = useState<AgentStepEvent[]>([]);
  const [sessionId, setSessionId] = useState(0);
  const prevVariantId = useRef<string | null>(null);

  const player = useRunPlayer(buffer, { resetKey: sessionId });

  const startDemo = useCallback(() => {
    const variant =
      prevVariantId.current == null
        ? pickInitialVariant()
        : pickNextVariant(prevVariantId.current);
    prevVariantId.current = variant.id;
    setBuffer(variantToEvents(variant));
    setSessionId((n) => n + 1);
  }, []);

  const agentForecasts = forecasts.filter((f) => f.producer === 'agent');
  const busy = player.playing;

  return (
    <section className="space-y-4">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h2 className="font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight">
            Forecaster
          </h2>
          <p className="mt-1 text-sm font-[family-name:var(--font-mono)] text-[var(--muted)] max-w-xl">
            A walkthrough of a detection pass — reasoning over signals, running
            detectors, and the forecasts that result.
          </p>
        </div>
        <FireControl
          busy={busy}
          onFire={startDemo}
          label="Fire forecaster"
          busyLabel="Playing…"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <AgentTranscript
          steps={player.visibleSteps}
          streaming={busy}
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
