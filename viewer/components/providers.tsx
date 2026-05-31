'use client';

import type { ReactNode } from 'react';
import { LayerVisibilityProvider } from '@/components/layer-visibility-provider';

export function ClientProviders({ children }: { children: ReactNode }) {
  return <LayerVisibilityProvider>{children}</LayerVisibilityProvider>;
}
