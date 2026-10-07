// CARTO raster basemaps require an API key since Aug 2026. Without one, tiles
// still load but carry an "API KEY REQUIRED" watermark. Get a free key at
// https://carto.com/basemaps/apikey and set NEXT_PUBLIC_CARTO_KEY.
//
// The key is shipped to the browser by design (every tile request carries it).
// If it is unset, we fall back to the bare URL so the map degrades to the
// watermark instead of breaking.

const CARTO_KEY = process.env.NEXT_PUBLIC_CARTO_KEY;

export type CartoStyle = 'dark_all' | 'light_all';

export function cartoTileUrl(style: CartoStyle): string {
  const base = `https://{s}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}{r}.png`;
  return CARTO_KEY ? `${base}?key=${encodeURIComponent(CARTO_KEY)}` : base;
}

export const CARTO_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener">CARTO</a>';
