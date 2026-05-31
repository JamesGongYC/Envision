'use client';

import { useState } from 'react';
import { LAYER_TREE } from '@/lib/layer-state';
import { useLayerVisibility } from '@/components/layer-visibility-provider';

export function MapLayerPanel() {
  const { visibility, toggle } = useLayerVisibility();
  const [open, setOpen] = useState(true);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="absolute top-4 right-4 z-[500] bg-slate-100 border border-slate-300 rounded px-2 py-1.5 text-xs text-slate-700 shadow-sm hover:bg-slate-200"
        aria-label="Open map layers panel"
      >
        Layers
      </button>
    );
  }

  return (
    <aside
      className="absolute top-4 right-4 z-[500] w-[240px] max-h-[calc(100%-2rem)] overflow-y-auto bg-slate-100/95 backdrop-blur border border-slate-300 rounded shadow-sm text-xs"
      aria-label="Map layers"
    >
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-300">
        <span className="font-semibold text-slate-800">Layers</span>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="text-slate-500 hover:text-slate-800 px-1"
          aria-label="Collapse layers panel"
        >
          −
        </button>
      </div>
      <div className="p-2 space-y-3">
        {LAYER_TREE.map((group) => (
          <div key={group.category}>
            <div className="font-medium text-slate-600 uppercase tracking-wide text-[10px] px-1 mb-1">
              {group.label}
            </div>
            <ul className="space-y-1">
              {group.layers.map((layer) => {
                const checked = visibility[layer.id];
                if (!layer.enabled) {
                  return (
                    <li key={layer.id} className="flex items-start gap-2 px-1 py-0.5">
                      <input
                        type="checkbox"
                        disabled
                        checked={false}
                        className="mt-0.5 opacity-40 cursor-not-allowed"
                        aria-label={layer.label}
                      />
                      <span className="text-slate-400 leading-snug">{layer.label}</span>
                    </li>
                  );
                }
                return (
                  <li key={layer.id} className="flex items-start gap-2 px-1 py-0.5">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggle(layer.id)}
                      className="mt-0.5 cursor-pointer"
                      aria-label={layer.label}
                    />
                    <span className="text-slate-800 leading-snug">{layer.label}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </aside>
  );
}
