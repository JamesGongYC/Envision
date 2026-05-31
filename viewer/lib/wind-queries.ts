import { sql } from '@/lib/db';

export type WindFieldRow = {
  data_compressed: Buffer;
  size_bytes: number;
  valid_at: string;
};

export async function getLatestWindField(): Promise<WindFieldRow | null> {
  const rows = await sql`
    SELECT data_compressed, size_bytes, valid_at
    FROM wind_fields
    ORDER BY valid_at DESC
    LIMIT 1
  `;
  if (!rows.length) return null;
  const row = rows[0] as {
    data_compressed: Buffer | Uint8Array;
    size_bytes: number;
    valid_at: string | Date;
  };
  const buf =
    row.data_compressed instanceof Buffer
      ? row.data_compressed
      : Buffer.from(row.data_compressed);
  return {
    data_compressed: buf,
    size_bytes: row.size_bytes,
    valid_at:
      row.valid_at instanceof Date
        ? row.valid_at.toISOString()
        : String(row.valid_at),
  };
}
