'use client';

import type { ReactNode } from 'react';
import { LayerTruncationProvider } from '@/components/layer-truncation-provider';
import { LayerVisibilityProvider } from '@/components/layer-visibility-provider';

export function ClientProviders({ children }: { children: ReactNode }) {
  return (
    <LayerVisibilityProvider>
      <LayerTruncationProvider>{children}</LayerTruncationProvider>
    </LayerVisibilityProvider>
  );
}
