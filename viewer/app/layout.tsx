import type { Metadata } from 'next';
import Link from 'next/link';
import { Space_Grotesk, IBM_Plex_Mono } from 'next/font/google';
import { ChromeHeight } from '@/components/chrome-height';
import { DisclaimerBanner } from '@/components/disclaimer-banner';
import { ClientProviders } from '@/components/providers';
import './globals.css';

const displayFont = Space_Grotesk({
  subsets: ['latin'],
  weight: ['700'],
  variable: '--font-display',
});

const monoFont = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-mono',
});

export const revalidate = 60;

export const metadata: Metadata = {
  title: {
    default: 'Envision | Continuous self-evolving agent for disaster prediction',
    template: '%s · Envision',
  },
  description:
    'Envision is an experimental research artifact exploring self-evolving agent architectures for disaster signal detection. Not an alerting service; do not use for safety-critical decisions.',
};

const navLink =
  'text-[var(--muted)] hover:text-[var(--foreground)] transition-colors font-[family-name:var(--font-mono)] text-xs uppercase tracking-wider';

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${displayFont.variable} ${monoFont.variable}`}>
      <body className="min-h-screen flex flex-col bg-[var(--background)] text-[var(--foreground)] antialiased">
        <ChromeHeight />
        <div
          id="site-chrome"
          className="sticky top-0 z-50 shrink-0 bg-[var(--background)]"
        >
          <DisclaimerBanner />
          <header className="border-b border-[var(--border)]">
            <nav className="container mx-auto px-4 py-3 flex items-center gap-8">
            <Link
              href="/"
              className="font-[family-name:var(--font-display)] font-bold tracking-tight text-sm"
            >
              ENVISION
            </Link>
            <Link href="/" className={navLink}>
              Forecasts
            </Link>
            <Link href="/how-it-works" className={navLink}>
              How it works
            </Link>
            <Link href="/agent" className={navLink}>
              Agent
            </Link>
            <Link href="/evolution" className={navLink}>
              Evolution
            </Link>
            </nav>
          </header>
        </div>
        <main className="flex-1 min-h-0 flex flex-col">
          <ClientProviders>{children}</ClientProviders>
        </main>
        <footer className="border-t border-[var(--border)] shrink-0 py-3">
          <div className="container mx-auto px-4 text-xs font-[family-name:var(--font-mono)] text-[var(--muted)]">
            <Link
              href="/disclaimer"
              className="underline hover:text-[var(--foreground)]"
            >
              Disclaimer
            </Link>
          </div>
        </footer>
      </body>
    </html>
  );
}
