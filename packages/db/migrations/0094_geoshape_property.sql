-- ============================================================================
-- 0094_geoshape_property.sql
-- Geoshape as a property base type (§425; `object-link-types` p.127, p.273;
-- `functions` p.40).
--
-- > "Geoshape: A type for defining properties that represent geographic
-- >  shapes." (`object-link-types` p.127)
--
-- > "GeoShape represents any valid GeoJSON geometry, including Points,
-- >  Polygons, LineStrings, and other shapes. These types follow the GeoJSON
-- >  specification... Note that positional arguments follow **longitude,
-- >  latitude** order as per the GeoJSON spec." (`functions` p.40)
--
-- **The two geo types disagree about coordinate order, and that is Foundry's
-- own arrangement rather than a mistake to iron out.** A Geopoint is stored
-- "latitude,longitude" (`object-link-types` p.273, and db 0029 here); a
-- Geoshape is GeoJSON, whose every coordinate pair is [longitude, latitude].
-- Normalising one to the other would make every value this platform exports
-- unreadable by anything that speaks GeoJSON, and would make a Geopoint
-- disagree with the format p.273 documents. So both orders are kept, both are
-- validated, and the difference is written down everywhere a reader could
-- assume otherwise - which is what `services/property_values.py` does and
-- what its tests are mostly about.
--
-- **No PostGIS, and no geometry column.** Instance values live in a jsonb
-- blob and, since migration 0026, may not live in Postgres at all. A
-- geoshape is validated as GeoJSON and stored as the object it is; spatial
-- *operations* - contains, intersects, distance - are a different feature
-- with a different store behind it, and p.127 does not ask for them here.
--
-- ADD VALUE IF NOT EXISTS: an enum label cannot be dropped, so a migration
-- that adds one must be re-appliable after an edit (STATUS rough edges).
-- ============================================================================

ALTER TYPE property_data_type ADD VALUE IF NOT EXISTS 'geoshape';

COMMENT ON TYPE property_data_type IS
    'Object property types. geopoint values are {"lat": float, "lon": float} '
    'and are written "latitude,longitude" when flattened to a column; '
    'geoshape values are GeoJSON geometry objects, whose coordinates are '
    '[longitude, latitude] - the two orders differ, deliberately, because '
    'Foundry documents each that way (object-link-types p.273, functions '
    'p.40). attachment values are {"key", "filename", "content_type", "size"} '
    'referencing the storage gateway; date/timestamp are ISO-8601 text, with '
    'an offset preserved when the source has one. Validated in '
    'services/property_values.py::coerce_property_value, not by the database '
    '- the values live inside a jsonb blob and may not live in Postgres at '
    'all (migration 0026 moved instances to OpenSearch).';
