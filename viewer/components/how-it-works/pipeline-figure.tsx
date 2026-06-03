'use client';

import { useState } from 'react';
import { PipelinePanel } from '@/components/how-it-works/pipeline-panel';

export type PipelinePanelData = {
  id: string;
  title: string;
  summary: string;
  telemetry: string;
  detail: React.ReactNode;
};

export function PipelineFigure({ panels }: { panels: PipelinePanelData[] }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <div className="flex flex-col md:flex-row gap-4 md:gap-0 items-stretch">
      {panels.map((panel, i) => (
        <PipelinePanel
          key={panel.id}
          id={panel.id}
          title={panel.title}
          summary={panel.summary}
          detail={panel.detail}
          telemetry={panel.telemetry}
          expanded={expandedId === panel.id}
          onToggle={() =>
            setExpandedId((prev) => (prev === panel.id ? null : panel.id))
          }
          showConnector={i < panels.length - 1}
        />
      ))}
    </div>
  );
}
