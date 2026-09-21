-- ============================================================================
-- 0097_geotemporal_series_mapping.sql
-- Where a geotemporal series' points live (§427; db 0047, db 0096).
--
-- Separate from 0096 because `ALTER TYPE ... ADD VALUE` and a use of the new
-- label cannot share a transaction: Postgres refuses to use an enum value
-- added in the same transaction that added it. Nothing here uses the label,
-- but the split is the habit that keeps the next one from being a puzzle.
--
-- See 0096 for why this is one table and one more column rather than a second
-- mapping table.
-- ============================================================================

ALTER TABLE object_type_series
    ADD COLUMN IF NOT EXISTS point_column text;

ALTER TABLE object_type_series
    ALTER COLUMN value_column DROP NOT NULL;

-- Exactly one of the two, which is what makes a mapping answerable: neither is
-- a chart with no points, and both is two answers to what a point is.
ALTER TABLE object_type_series
    DROP CONSTRAINT IF EXISTS object_type_series_one_kind;
ALTER TABLE object_type_series
    ADD CONSTRAINT object_type_series_one_kind
    CHECK ((value_column IS NULL) <> (point_column IS NULL));

COMMENT ON COLUMN object_type_series.value_column IS
    'The numeric column behind a `time_series` property. Null when this row '
    'maps a `geotemporal_series` instead, which carries `point_column`.';

COMMENT ON COLUMN object_type_series.point_column IS
    'The position column behind a `geotemporal_series` property (§427; '
    'object-link-types p.127). One column rather than a lat/lon pair, because '
    'services/property_values.py::_coerce_geopoint already reads every '
    'spelling a real column holds - "lat,lon" text, a {lat, lon} mapping, a '
    'two-element list - and a second coordinate convention would be a third '
    'place for the axis order to be got wrong.';
