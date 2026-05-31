'use client';

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import type { LayerId } from '@/lib/layer-state';

export type LayerTruncationInfo = {
  truncated: boolean;
  totalCount: number;
  returnedCount: number;
};

type LayerTruncationContextValue = {
  truncation: Partial<Record<LayerId, LayerTruncationInfo>>;
  setTruncation: (layerId: LayerId, info: LayerTruncationInfo | null) => void;
};

const LayerTruncationContext = createContext<LayerTruncationContextValue | null>(
  null
);

export function LayerTruncationProvider({ children }: { children: ReactNode }) {
  const [truncation, setTruncationState] = useState<
    Partial<Record<LayerId, LayerTruncationInfo>>
  >({});

  const setTruncation = useCallback(
    (layerId: LayerId, info: LayerTruncationInfo | null) => {
      setTruncationState((prev) => {
        const next = { ...prev };
        if (info === null) {
          delete next[layerId];
        } else {
          next[layerId] = info;
        }
        return next;
      });
    },
    []
  );

  const value = useMemo(
    () => ({ truncation, setTruncation }),
    [truncation, setTruncation]
  );

  return (
    <LayerTruncationContext.Provider value={value}>
      {children}
    </LayerTruncationContext.Provider>
  );
}

export function useLayerTruncation(): LayerTruncationContextValue {
  const ctx = useContext(LayerTruncationContext);
  if (!ctx) {
    throw new Error('useLayerTruncation must be used within LayerTruncationProvider');
  }
  return ctx;
}
