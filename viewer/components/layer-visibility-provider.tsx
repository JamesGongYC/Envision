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
  DEFAULT_UI_VISIBILITY,
  STORAGE_KEY,
  expandVisibility,
  mergeUiVisibility,
  type LayerVisibility,
  type MapLayerToggle,
  type MapLayerVisibility,
} from '@/lib/layer-state';

type LayerVisibilityContextValue = {
  uiVisibility: MapLayerVisibility;
  visibility: LayerVisibility;
  hydrated: boolean;
  toggle: (id: MapLayerToggle) => void;
  setAll: (state: Partial<MapLayerVisibility>) => void;
};

const LayerVisibilityContext = createContext<LayerVisibilityContextValue | null>(
  null
);

export function LayerVisibilityProvider({ children }: { children: ReactNode }) {
  const [uiVisibility, setUiVisibility] =
    useState<MapLayerVisibility>(DEFAULT_UI_VISIBILITY);
  const [hydrated, setHydrated] = useState(false);

  const normalizedUiVisibility = useMemo(
    () => mergeUiVisibility(uiVisibility),
    [uiVisibility]
  );

  const visibility = useMemo(
    () => expandVisibility(normalizedUiVisibility),
    [normalizedUiVisibility]
  );

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        setUiVisibility(
          mergeUiVisibility(JSON.parse(stored) as Partial<MapLayerVisibility>)
        );
      }
    } catch {
      // ignore corrupt localStorage
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(mergeUiVisibility(uiVisibility))
    );
  }, [uiVisibility, hydrated]);

  const toggle = useCallback((id: MapLayerToggle) => {
    setUiVisibility((prev) => {
      const current = mergeUiVisibility(prev);
      return { ...current, [id]: !current[id] };
    });
  }, []);

  const setAll = useCallback((state: Partial<MapLayerVisibility>) => {
    setUiVisibility((prev) => mergeUiVisibility({ ...prev, ...state }));
  }, []);

  const value = useMemo(
    () => ({
      uiVisibility: normalizedUiVisibility,
      visibility,
      hydrated,
      toggle,
      setAll,
    }),
    [normalizedUiVisibility, visibility, hydrated, toggle, setAll]
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
