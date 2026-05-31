-- v2.6: gzipped leaflet-velocity wind fields from AIFS 10m u/v (+24h)
CREATE TABLE wind_fields (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_time TIMESTAMPTZ NOT NULL,
  valid_at TIMESTAMPTZ NOT NULL,
  source TEXT NOT NULL DEFAULT 'aifs',
  data_compressed BYTEA NOT NULL,
  size_bytes INT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_wind_fields_valid_at ON wind_fields (valid_at DESC);
CREATE INDEX idx_wind_fields_source ON wind_fields (source, valid_at DESC);
