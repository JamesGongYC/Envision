'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import {
  DEFAULT_VISIBILITY,
  STORAGE_KEY,
  mergeVisibility,
  type LayerId,
  type LayerVisibility,
} from '@/lib/layer-state';

type LayerVisibilityContextValue = {
  visibility: LayerVisibility;
  hydrated: boolean;
  toggle: (id: LayerId) => void;
  setAll: (state: Partial<LayerVisibility>) => void;
};

const LayerVisibilityContext = createContext<LayerVisibilityContextValue | null>(
  null
);

export function LayerVisibilityProvider({ children }: { children: ReactNode }) {
  const [visibility, setVisibility] = useState<LayerVisibility>(DEFAULT_VISIBILITY);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        setVisibility(mergeVisibility(JSON.parse(stored) as Partial<LayerVisibility>));
      }
    } catch {
      // ignore corrupt localStorage
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(visibility));
  }, [visibility, hydrated]);

  const toggle = useCallback((id: LayerId) => {
    setVisibility((prev) => ({ ...prev, [id]: !prev[id] }));
  }, []);

  const setAll = useCallback((state: Partial<LayerVisibility>) => {
    setVisibility((prev) => ({ ...prev, ...state }));
  }, []);

  const value = useMemo(
    () => ({ visibility, hydrated, toggle, setAll }),
    [visibility, hydrated, toggle, setAll]
  );

  return (
    <LayerVisibilityContext.Provider value={value}>
      {children}
    </LayerVisibilityContext.Provider>
  );
}

export function useLayerVisibility(): LayerVisibilityContextValue {
  const ctx = useContext(LayerVisibilityContext);
  if (!ctx) {
    throw new Error('useLayerVisibility must be used within LayerVisibilityProvider');
  }
  return ctx;
}
