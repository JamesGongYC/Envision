import 'server-only';

import { neon } from '@neondatabase/serverless';

if (!process.env.DATABASE_URL) {
  throw new Error('DATABASE_URL is not set in the environment');
}

// `sql` is a tagged template literal. Use as:
//   const rows = await sql`SELECT * FROM forecasts WHERE id = ${id}`;
// Parameters are bound safely; no string interpolation needed.
export const sql = neon(process.env.DATABASE_URL);
