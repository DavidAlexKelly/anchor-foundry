-- ============================================================================
-- 0153_functions.sql
-- Decision 0018 (option B, §768); parity README's "Functions" and every
-- `[fn]` row; Foundry `functions` p.49-50, p.79-81.
--
-- A function is a named, versioned SQL query over the ontology, called by
-- widgets and actions. A version is immutable and named by the author with a
-- semantic version (p.49: "Versions for function releases are chosen by their
-- publishers and are immutable after creation"), so a consumer that names one
-- keeps getting the same logic.
-- ============================================================================

CREATE TABLE functions (
    id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id  uuid        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    api_name      text        NOT NULL,
    display_name  text        NOT NULL,
    description   text        NOT NULL DEFAULT '',
    created_by    uuid        REFERENCES users(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, api_name)
);

CREATE TRIGGER trg_functions_updated_at BEFORE UPDATE ON functions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE function_versions (
    id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    function_id   uuid        NOT NULL REFERENCES functions(id) ON DELETE CASCADE,
    version       text        NOT NULL,
    -- [{api_name, display_name, data_type, object_type_id?, required}]
    parameters    jsonb       NOT NULL DEFAULT '[]',
    -- The object types the SQL reads, each a table named by its api_name.
    inputs        uuid[]      NOT NULL DEFAULT '{}',
    -- {kind, data_type?, object_type_id?}
    output        jsonb       NOT NULL,
    sql           text        NOT NULL,
    created_by    uuid        REFERENCES users(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (function_id, version)
);

ALTER TABLE functions ENABLE ROW LEVEL SECURITY;
CREATE POLICY functions_isolation ON functions
    USING (workspace_id = ANY (rls_workspace_ids()))
    WITH CHECK (workspace_id = ANY (rls_workspace_ids()));

ALTER TABLE function_versions ENABLE ROW LEVEL SECURITY;
CREATE POLICY function_versions_isolation ON function_versions
    USING (EXISTS (SELECT 1 FROM functions f WHERE f.id = function_id));

GRANT SELECT, INSERT, UPDATE, DELETE ON functions TO platform_app;
GRANT SELECT, INSERT, DELETE ON function_versions TO platform_app;
