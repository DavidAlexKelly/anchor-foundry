-- ============================================================================
-- 0012_object_instances.sql
-- Object instance materialisation (spec: "object instances are stored and
-- indexed in OpenSearch"). One row per source row synced from a mapped
-- dataset into the ontology (services/instances.py).
--
-- Flagged for review — architecturally significant: this table is a
-- Postgres-backed instance store, not OpenSearch. Unlike StorageGateway
-- (S3 vs local disk) or SecretsGateway (Secrets Manager vs in-memory), this
-- is not a drop-in swap behind one interface: Postgres RLS gives free,
-- per-row workspace isolation that a search index does not enforce for you.
-- A production OpenSearch-backed store needs its own access-control design
-- (workspace/type filters baked into every query) and is out of scope here.
-- This table exists so materialisation, sync, and browsing are fully
-- runnable and tested without provisioning a search cluster in this build.
-- ============================================================================

CREATE TABLE object_instances (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    object_type_id  uuid NOT NULL REFERENCES object_types(id) ON DELETE CASCADE,
    source_id       uuid NOT NULL REFERENCES object_type_sources(id) ON DELETE CASCADE,
    -- The mapped dataset's primary key value, always stored as text — the
    -- underlying column can be integer, uuid, etc.; instances are identified
    -- by (source_id, primary_key), never by assuming a type.
    primary_key     text NOT NULL CHECK (length(primary_key) BETWEEN 1 AND 500),
    properties      jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id, primary_key)
);

CREATE INDEX idx_object_instances_type ON object_instances (object_type_id, updated_at DESC);
CREATE INDEX idx_object_instances_properties ON object_instances USING gin (properties);

CREATE TRIGGER trg_object_instances_updated BEFORE UPDATE ON object_instances
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Same non-recursive shape as otp_isolation (0006): one hop to object_types,
-- which is not itself subselected further.
ALTER TABLE object_instances ENABLE ROW LEVEL SECURITY;
CREATE POLICY oi_isolation ON object_instances
    USING (EXISTS (SELECT 1 FROM object_types ot
                   WHERE ot.id = object_type_id
                     AND rls_can_access_workspace(ot.workspace_id)));
