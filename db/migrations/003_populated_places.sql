-- Envision migration 003 — populated_places
-- Used by typhoon-landfall-imminent to find population centers
-- inside an approximated NHC forecast cone.

CREATE TABLE IF NOT EXISTS populated_places (
  geonameid    bigint PRIMARY KEY,
  name         text   NOT NULL,
  country_code text,
  population   integer NOT NULL,
  geometry     geometry(Point, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS populated_places_geom_idx
  ON populated_places USING GIST (geometry);

CREATE INDEX IF NOT EXISTS populated_places_pop_idx
  ON populated_places (population);
