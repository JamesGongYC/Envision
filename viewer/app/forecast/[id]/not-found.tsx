import Link from 'next/link';

export default function ForecastNotFound() {
  return (
    <div className="container mx-auto px-4 py-16 max-w-2xl">
      <h1 className="text-2xl font-semibold tracking-tight">
        Forecast not found
      </h1>
      <p className="mt-3 text-neutral-600">
        That forecast ID doesn&rsquo;t exist or has expired and been purged by
        retention. Forecasts are short-lived by design.
      </p>
      <p className="mt-6">
        <Link href="/" className="text-blue-600 hover:underline">
          ← Back to map
        </Link>
      </p>
    </div>
  );
}
