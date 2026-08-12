-- ============================================================================
-- 0047_time_series_properties.sql
-- Decision `docs/decisions/0009-time-series-and-media-storage.md`, part 1;
-- parity `docs/parity/ontology.md` §1.1 and §4.1.
--
-- > "Stores a history of timestamped values." (`object-link-types` p.127)
--
-- **The property does not hold the points, and that is the whole decision.**
-- A time series property is not a value, it is a table: one instance carries
-- thousands of `(timestamp, value)` pairs. Everything this platform stores
-- about an instance is *one document* - `object_instances.properties` as
-- jsonb, or one OpenSearch document - so points there would mean every list
-- read pays for every point, and every full-snapshot sync rewrites the whole
-- history of an instance that did not change.
--
-- So an instance's `time_series` property value is a small scalar: the
-- **series id**, which is usually the instance's own primary key. This table
-- says where the points behind it live.
--
-- **Points stay in the dataset they arrived in.** Decision 0009 rejects a
-- `time_series_points` table in Postgres, and not for performance: it would be
-- a second copy of data the dataset subsystem already versions (0005's
-- retention, dataset time travel, lineage), with its own backfill path and its
-- own answer to "what did this look like last Tuesday". A series is tabular
-- data over time, which is what Parquet and DuckDB are already here for.
--
-- **Declared on the *source*, not on the object type.** An object type is
-- workspace-scoped; a dataset lives in a project. "Where are this type's rows
-- in this project" is exactly what `object_type_sources` answers, and where a
-- type's series live is the same question about the same project - so it is
-- the same row's business. A type mapped in two projects can point its series
-- at two different datasets, which is the existing behaviour for its
-- properties and would be surprising to lose here.
--
-- **The cost, named rather than discovered:** points are as fresh as the
-- dataset. A live sensor feed is a sync away from the chart, not a stream.
-- This platform has no streaming ingestion, and a design implying one would
-- be describing a different product.
-- ============================================================================

ALTER TYPE property_data_type ADD VALUE IF NOT EXISTS 'time_series';

-- **And the parameter enum, in the same breath.** `action_parameter_type`
-- (0044) overlaps `property_data_type`, and a property type no parameter can
-- hold is a property no action could ever write. A time series property's
-- *value* is a series id - a small scalar like any other - so re-pointing an
-- instance at a different series is an ordinary edit, and refusing it would be
-- arbitrary. `test_every_property_type_can_be_an_action_parameter` is the
-- drift guard that caught this one being forgotten.
ALTER TYPE action_parameter_type ADD VALUE IF NOT EXISTS 'time_series';

CREATE TABLE object_type_series (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    object_type_source_id  uuid NOT NULL
                               REFERENCES object_type_sources(id) ON DELETE CASCADE,
    -- The `time_series` property this feeds. Text rather than a foreign key to
    -- object_type_properties for the same reason column_mappings is text: a
    -- property is identified by its api_name everywhere else in this schema,
    -- and a second identity for it would be a second thing to keep in step.
    property_api_name      text NOT NULL CHECK (property_api_name ~ '^[a-z][a-z0-9_]{0,99}$'),
    -- Where the points are. A different dataset from the one the source maps:
    -- readings and the things being read are not the same table.
    dataset_id             uuid NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    -- Matched against the value of the instance's `time_series` property.
    key_column             text NOT NULL,
    timestamp_column       text NOT NULL,
    value_column           text NOT NULL,
    created_by             uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    -- One series per property per mapping. Two would be two answers to "where
    -- are this property's points", and nothing could choose between them.
    UNIQUE (object_type_source_id, property_api_name)
);

CREATE TRIGGER trg_object_type_series_updated BEFORE UPDATE ON object_type_series
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON COLUMN object_type_series.key_column IS
    'Matched against the instance''s time_series property value - the series '
    'id, usually the instance''s own primary key. Column names are validated '
    'against the dataset schema in Python at save time; a column that '
    'disappears later is a refusal at read time, not a silent empty chart.';

-- Same workspace-consistency shape as object_type_sources (0003): the points
-- dataset must live in the same workspace as the type it feeds. A series
-- pointing across a workspace boundary would be a read path through it.
CREATE FUNCTION enforce_object_type_series_workspace() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_type_ws uuid;
    v_ds_ws uuid;
BEGIN
    SELECT ot.workspace_id INTO v_type_ws
      FROM object_type_sources s
      JOIN object_types ot ON ot.id = s.object_type_id
     WHERE s.id = NEW.object_type_source_id;
    SELECT rls_project_workspace_id(project_id) INTO v_ds_ws
      FROM datasets WHERE id = NEW.dataset_id;
    IF v_type_ws IS DISTINCT FROM v_ds_ws THEN
        RAISE EXCEPTION 'a time series cannot cross workspace boundaries (hard isolation, spec §4)';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_object_type_series_workspace BEFORE INSERT OR UPDATE ON object_type_series
    FOR EACH ROW EXECUTE FUNCTION enforce_object_type_series_workspace();

-- Visible when its source is, which is the shape object_type_sources' own
-- policy already establishes for everything hanging off a mapping.
ALTER TABLE object_type_series ENABLE ROW LEVEL SECURITY;
CREATE POLICY object_type_series_isolation ON object_type_series
    USING (EXISTS (SELECT 1 FROM object_type_sources s
                   WHERE s.id = object_type_source_id));
