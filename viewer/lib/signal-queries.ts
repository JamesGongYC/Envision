import { sql } from '@/lib/db';
import type { BBox } from '@/lib/layer-config';

export const DEFAULT_SIGNAL_LIMIT = 5000;
export const DEFAULT_SINCE_HOURS = 24;

export type SignalQueryParams = {
  sources: string[];
  signalType?: string;
  bbox?: BBox | null;
  sinceHours?: number;
  limit?: number;
};

export type GeoJSONFeatureCollection = GeoJSON.FeatureCollection & {
  properties?: {
    truncated?: boolean;
    totalCount?: number;
    returnedCount?: number;
  };
};

function buildSignalsQuery(
  params: SignalQueryParams,
  sampleRandom: boolean
): ReturnType<typeof sql> {
  const limit = params.limit ?? DEFAULT_SIGNAL_LIMIT;
  const sinceHours = params.sinceHours ?? DEFAULT_SINCE_HOURS;
  const sources = params.sources;
  const signalType = params.signalType;
  const bbox = params.bbox;

  if (bbox) {
    const { west, south, east, north } = bbox;
    if (signalType) {
      if (sampleRandom) {
        return sql`
          SELECT
            id::text,
            "timestamp",
            source,
            signal_type,
            ST_AsGeoJSON(geometry)::jsonb AS geometry,
            payload
          FROM signals
          WHERE source = ANY(${sources}::text[])
            AND signal_type = ${signalType}
            AND "timestamp" >= now() - (${sinceHours}::int * interval '1 hour')
            AND ST_Intersects(
              geometry,
              ST_MakeEnvelope(${west}, ${south}, ${east}, ${north}, 4326)
            )
          ORDER BY random()
          LIMIT ${limit}
        `;
      }
      return sql`
        SELECT
          id::text,
          "timestamp",
          source,
          signal_type,
          ST_AsGeoJSON(geometry)::jsonb AS geometry,
          payload
        FROM signals
        WHERE source = ANY(${sources}::text[])
          AND signal_type = ${signalType}
          AND "timestamp" >= now() - (${sinceHours}::int * interval '1 hour')
          AND ST_Intersects(
            geometry,
            ST_MakeEnvelope(${west}, ${south}, ${east}, ${north}, 4326)
          )
        ORDER BY "timestamp" DESC
        LIMIT ${limit}
      `;
    }
    if (sampleRandom) {
      return sql`
        SELECT
          id::text,
          "timestamp",
          source,
          signal_type,
          ST_AsGeoJSON(geometry)::jsonb AS geometry,
          payload
        FROM signals
        WHERE source = ANY(${sources}::text[])
          AND "timestamp" >= now() - (${sinceHours}::int * interval '1 hour')
          AND ST_Intersects(
            geometry,
            ST_MakeEnvelope(${west}, ${south}, ${east}, ${north}, 4326)
          )
        ORDER BY random()
        LIMIT ${limit}
      `;
    }
    return sql`
      SELECT
        id::text,
        "timestamp",
        source,
        signal_type,
        ST_AsGeoJSON(geometry)::jsonb AS geometry,
        payload
      FROM signals
      WHERE source = ANY(${sources}::text[])
        AND "timestamp" >= now() - (${sinceHours}::int * interval '1 hour')
        AND ST_Intersects(
          geometry,
          ST_MakeEnvelope(${west}, ${south}, ${east}, ${north}, 4326)
        )
      ORDER BY "timestamp" DESC
      LIMIT ${limit}
    `;
  }

  if (signalType) {
    if (sampleRandom) {
      return sql`
        SELECT
          id::text,
          "timestamp",
          source,
          signal_type,
          ST_AsGeoJSON(geometry)::jsonb AS geometry,
          payload
        FROM signals
        WHERE source = ANY(${sources}::text[])
          AND signal_type = ${signalType}
          AND "timestamp" >= now() - (${sinceHours}::int * interval '1 hour')
        ORDER BY random()
        LIMIT ${limit}
      `;
    }
    return sql`
      SELECT
        id::text,
        "timestamp",
        source,
        signal_type,
        ST_AsGeoJSON(geometry)::jsonb AS geometry,
        payload
      FROM signals
      WHERE source = ANY(${sources}::text[])
        AND signal_type = ${signalType}
        AND "timestamp" >= now() - (${sinceHours}::int * interval '1 hour')
      ORDER BY "timestamp" DESC
      LIMIT ${limit}
    `;
  }

  if (sampleRandom) {
    return sql`
      SELECT
        id::text,
        "timestamp",
        source,
        signal_type,
        ST_AsGeoJSON(geometry)::jsonb AS geometry,
        payload
      FROM signals
      WHERE source = ANY(${sources}::text[])
        AND "timestamp" >= now() - (${sinceHours}::int * interval '1 hour')
      ORDER BY random()
      LIMIT ${limit}
    `;
  }

  return sql`
    SELECT
      id::text,
      "timestamp",
      source,
      signal_type,
      ST_AsGeoJSON(geometry)::jsonb AS geometry,
      payload
    FROM signals
    WHERE source = ANY(${sources}::text[])
      AND "timestamp" >= now() - (${sinceHours}::int * interval '1 hour')
    ORDER BY "timestamp" DESC
    LIMIT ${limit}
  `;
}

async function countSignals(params: SignalQueryParams): Promise<number> {
  const sinceHours = params.sinceHours ?? DEFAULT_SINCE_HOURS;
  const sources = params.sources;
  const signalType = params.signalType;
  const bbox = params.bbox;

  if (bbox) {
    const { west, south, east, north } = bbox;
    if (signalType) {
      const rows = await sql`
        SELECT count(*)::int AS n
        FROM signals
        WHERE source = ANY(${sources}::text[])
          AND signal_type = ${signalType}
          AND "timestamp" >= now() - (${sinceHours}::int * interval '1 hour')
          AND ST_Intersects(
            geometry,
            ST_MakeEnvelope(${west}, ${south}, ${east}, ${north}, 4326)
          )
      `;
      return (rows[0] as { n: number }).n;
    }
    const rows = await sql`
      SELECT count(*)::int AS n
      FROM signals
      WHERE source = ANY(${sources}::text[])
        AND "timestamp" >= now() - (${sinceHours}::int * interval '1 hour')
        AND ST_Intersects(
          geometry,
          ST_MakeEnvelope(${west}, ${south}, ${east}, ${north}, 4326)
        )
    `;
    return (rows[0] as { n: number }).n;
  }

  if (signalType) {
    const rows = await sql`
      SELECT count(*)::int AS n
      FROM signals
      WHERE source = ANY(${sources}::text[])
        AND signal_type = ${signalType}
        AND "timestamp" >= now() - (${sinceHours}::int * interval '1 hour')
    `;
    return (rows[0] as { n: number }).n;
  }

  const rows = await sql`
    SELECT count(*)::int AS n
    FROM signals
    WHERE source = ANY(${sources}::text[])
      AND "timestamp" >= now() - (${sinceHours}::int * interval '1 hour')
  `;
  return (rows[0] as { n: number }).n;
}

type SignalRow = {
  id: string;
  timestamp: string;
  source: string;
  signal_type: string;
  geometry: GeoJSON.Geometry;
  payload: Record<string, unknown>;
};

export async function fetchSignalsAsGeoJSON(
  params: SignalQueryParams
): Promise<GeoJSONFeatureCollection> {
  const limit = params.limit ?? DEFAULT_SIGNAL_LIMIT;
  const totalCount = await countSignals(params);
  const truncated = totalCount > limit;
  const rows = (await buildSignalsQuery(params, truncated)) as unknown as SignalRow[];

  const features: GeoJSON.Feature[] = rows.map((row) => ({
    type: 'Feature',
    id: row.id,
    geometry: row.geometry,
    properties: {
      id: row.id,
      timestamp: row.timestamp,
      source: row.source,
      signal_type: row.signal_type,
      payload: row.payload,
    },
  }));

  return {
    type: 'FeatureCollection',
    features,
    properties: {
      truncated,
      totalCount,
      returnedCount: features.length,
    },
  };
}

export type GroundTruthQueryParams = {
  sources?: string[];
  bbox?: BBox | null;
  sinceHours?: number;
  limit?: number;
};

type GroundTruthRow = {
  id: string;
  occurred_at: string;
  source: string;
  disaster_class: string;
  geometry: GeoJSON.Geometry;
  severity: string | null;
  payload: Record<string, unknown>;
};

export async function fetchGroundTruthAsGeoJSON(
  params: GroundTruthQueryParams
): Promise<GeoJSONFeatureCollection> {
  const limit = params.limit ?? DEFAULT_SIGNAL_LIMIT;
  const sinceHours = params.sinceHours ?? DEFAULT_SINCE_HOURS;
  const sources = params.sources ?? ['gdacs'];
  const bbox = params.bbox;

  let totalCount: number;
  let rows: GroundTruthRow[];

  if (bbox) {
    const { west, south, east, north } = bbox;
    const countRows = await sql`
      SELECT count(*)::int AS n
      FROM ground_truth
      WHERE source = ANY(${sources}::text[])
        AND occurred_at >= now() - (${sinceHours}::int * interval '1 hour')
        AND ST_Intersects(
          geometry,
          ST_MakeEnvelope(${west}, ${south}, ${east}, ${north}, 4326)
        )
    `;
    totalCount = (countRows[0] as { n: number }).n;
    const truncated = totalCount > limit;
    rows = truncated
      ? ((await sql`
          SELECT
            id::text,
            occurred_at,
            source,
            disaster_class,
            ST_AsGeoJSON(geometry)::jsonb AS geometry,
            severity,
            payload
          FROM ground_truth
          WHERE source = ANY(${sources}::text[])
            AND occurred_at >= now() - (${sinceHours}::int * interval '1 hour')
            AND ST_Intersects(
              geometry,
              ST_MakeEnvelope(${west}, ${south}, ${east}, ${north}, 4326)
            )
          ORDER BY random()
          LIMIT ${limit}
        `) as unknown as GroundTruthRow[])
      : ((await sql`
          SELECT
            id::text,
            occurred_at,
            source,
            disaster_class,
            ST_AsGeoJSON(geometry)::jsonb AS geometry,
            severity,
            payload
          FROM ground_truth
          WHERE source = ANY(${sources}::text[])
            AND occurred_at >= now() - (${sinceHours}::int * interval '1 hour')
            AND ST_Intersects(
              geometry,
              ST_MakeEnvelope(${west}, ${south}, ${east}, ${north}, 4326)
            )
          ORDER BY occurred_at DESC
          LIMIT ${limit}
        `) as unknown as GroundTruthRow[]);
  } else {
    const countRows = await sql`
      SELECT count(*)::int AS n
      FROM ground_truth
      WHERE source = ANY(${sources}::text[])
        AND occurred_at >= now() - (${sinceHours}::int * interval '1 hour')
    `;
    totalCount = (countRows[0] as { n: number }).n;
    const truncated = totalCount > limit;
    rows = truncated
      ? ((await sql`
          SELECT
            id::text,
            occurred_at,
            source,
            disaster_class,
            ST_AsGeoJSON(geometry)::jsonb AS geometry,
            severity,
            payload
          FROM ground_truth
          WHERE source = ANY(${sources}::text[])
            AND occurred_at >= now() - (${sinceHours}::int * interval '1 hour')
          ORDER BY random()
          LIMIT ${limit}
        `) as unknown as GroundTruthRow[])
      : ((await sql`
          SELECT
            id::text,
            occurred_at,
            source,
            disaster_class,
            ST_AsGeoJSON(geometry)::jsonb AS geometry,
            severity,
            payload
          FROM ground_truth
          WHERE source = ANY(${sources}::text[])
            AND occurred_at >= now() - (${sinceHours}::int * interval '1 hour')
          ORDER BY occurred_at DESC
          LIMIT ${limit}
        `) as unknown as GroundTruthRow[]);
  }

  const truncated = totalCount > limit;
  const features: GeoJSON.Feature[] = rows.map((row) => ({
    type: 'Feature',
    id: row.id,
    geometry: row.geometry,
    properties: {
      id: row.id,
      timestamp: row.occurred_at,
      source: row.source,
      signal_type: 'ground_truth',
      disaster_class: row.disaster_class,
      severity: row.severity,
      payload: row.payload,
    },
  }));

  return {
    type: 'FeatureCollection',
    features,
    properties: {
      truncated,
      totalCount,
      returnedCount: features.length,
    },
  };
}
