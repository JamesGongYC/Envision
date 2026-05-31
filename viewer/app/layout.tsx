import type { Metadata } from 'next';
import Link from 'next/link';
import { DisclaimerBanner } from '@/components/disclaimer-banner';
import { ClientProviders } from '@/components/providers';
import { StatusHeader } from '@/components/status-header';
import './globals.css';

export const revalidate = 60;

export const metadata: Metadata = {
  title: {
    default: 'Envision | Continuous self-evolving agent for disaster prediction',
    template: "%s · Envision",
  },
  description:
    'Envision is an experimental research artifact exploring self-evolving agent architectures for disaster signal detection. Not an alerting service; do not use for safety-critical decisions.',
};


export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen flex flex-col bg-white text-neutral-900 antialiased">
        <StatusHeader />
        <DisclaimerBanner />
        <header className="border-b border-neutral-200 shrink-0">
          <nav className="container mx-auto px-4 py-3 flex items-center gap-6 text-sm">
            <Link href="/" className="font-semibold tracking-tight">
              Envision
            </Link>
            <Link
              href="/"
              className="text-neutral-600 hover:text-neutral-900"
            >
              Map
            </Link>
            <Link
              href="/agent"
              className="text-neutral-600 hover:text-neutral-900"
            >
              Agent log
            </Link>
            <Link
              href="/about"
              className="ml-auto text-neutral-600 hover:text-neutral-900"
            >
              About
            </Link>
          </nav>
        </header>
        <main className="flex-1 min-h-0">
          <ClientProviders>{children}</ClientProviders>
        </main>
      </body>
    </html>
  );
}
