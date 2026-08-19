-- ============================================================================
-- 0054_value_types.sql
-- Value types (parity `docs/parity/ontology.md` §1.2; Foundry
-- `object-link-types` p.222-234).
--
-- > "Value types are semantic wrappers around a field type that include
-- > metadata and constraints that can enhance type safety, improve
-- > expressiveness, and provide additional context… For example, a user can
-- > define an 'email' value type that has a regular expression constraint to
-- > ensure any property that uses the value type represents a valid email
-- > address." (p.222)
--
-- **The sibling of `shared_properties` (0053), and the difference is the
-- point.** A shared property shares *metadata* - what a property is called and
-- how it is shown. A value type shares a *constraint* - what a value is allowed
-- to be. They are attached independently and compose: an `email` value type on
-- a `contact_email` shared property is an ordinary arrangement, and p.227 says
-- so explicitly ("Assigning a value type to a shared property").
--
-- Two tables, because half of a value type is immutable
-- ----------------------------------------------------
-- p.229 draws the line and this schema follows it exactly:
--
-- > "The metadata values for name, description, and apiName can be changed
-- > whenever necessary. The base type metadata and the constraints that define
-- > the validation rules for the type are immutable. If you choose to update
-- > the constraints of a value type, a new version of the value type is
-- > created."
--
-- So `value_types` holds the identity and the editable metadata, and
-- `value_type_versions` holds `base_type` + `constraint`, append-only. Storing
-- the constraint on the value type with an `updated_at` would make "what was
-- this checking last March" unanswerable, and a constraint is exactly the sort
-- of thing somebody has to answer that about after data has been rejected.
--
-- **The current version is the highest-numbered one**, not a pointer column.
-- p.230: a new version "will automatically propagate to the Ontology, ensuring
-- that all uses of the value type across the Ontology are updated to the latest
-- version" - so a property references the *value type*, and which version
-- applies is a question with one answer at any moment. A pointer would be a
-- second place for that answer to live, and a chance for it to disagree.
--
-- Workspace-scoped, like everything else in this ontology
-- -----------------------------------------------------
-- Foundry scopes a value type to a *space* (p.222: "Value types can only be
-- used within the space in which they were defined"), and a space "can hold a
-- single ontology". A workspace is this platform's ontology (0003), so that is
-- the boundary here, exactly as for `shared_properties`.
--
-- What is deliberately not built
-- ------------------------------
--   * Foundry's separate **Value Types Manager** application and its
--     cross-project import (p.232). There is one ontology per workspace here
--     and no space-level sharing to import across.
--   * **Deprecation** (p.229 recommends deprecating a value type rather than
--     making a breaking constraint change). That is object-type Status (p.253),
--     which is its own ○ row; a deprecation flag on this table alone would be
--     the same idea implemented twice.
-- ============================================================================

CREATE TABLE value_types (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    -- p.224 step 4: "a clear name, description, and unique API name".
    api_name        text NOT NULL
                        CHECK (api_name ~ '^[a-z][a-z0-9_]{0,99}$'),
    display_name    text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
    description     text NOT NULL DEFAULT '',
    -- p.225 step 7: "(Optional but recommended) Provide an example preview
    -- value". Stored as text whatever the base type, because it is shown to a
    -- person rather than validated against anything - its job is to say what
    -- an `iso_country_code` looks like without making somebody read a regex.
    example_value   text NOT NULL DEFAULT '',
    created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, api_name)
);

CREATE INDEX idx_value_types_workspace ON value_types (workspace_id);

CREATE TRIGGER trg_value_types_updated BEFORE UPDATE ON value_types
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE value_types IS
    'A reusable constraint on what a value may be (Foundry object-link-types '
    'p.222-234). Identity and editable metadata only: the base type and the '
    'constraint live in value_type_versions and are immutable (p.229).';

-- The immutable half. One row per version; the current one is the highest
-- `version_number`, which is also what every property using the value type is
-- validated against (p.230's automatic propagation).
CREATE TABLE value_type_versions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    value_type_id   uuid NOT NULL REFERENCES value_types(id) ON DELETE CASCADE,
    version_number  integer NOT NULL CHECK (version_number >= 1),
    base_type       property_data_type NOT NULL,
    -- One jsonb column for `value_format`'s reason (0049): the fields are
    -- per-kind - a regex means nothing to a range - so typed columns would
    -- encode "does not apply" as an absence rather than as a shape. NULL is a
    -- legitimate value type with no constraint at all: p.224 step 6 marks the
    -- constraint "(Optional)", and a value type that only says "this string is
    -- an email address" is still worth having for the meaning it carries.
    constraint_json jsonb,
    created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (value_type_id, version_number)
);

CREATE INDEX idx_value_type_versions_type
    ON value_type_versions (value_type_id, version_number DESC);

COMMENT ON COLUMN value_type_versions.constraint_json IS
    'The validation rule (Foundry p.233), or NULL for a value type that '
    'carries meaning without a constraint. Immutable: changing it appends a '
    'new version (p.229). Shape validated in services/value_types.py.';

-- Attachment, in the two places p.227 names.
ALTER TABLE object_type_properties
    ADD COLUMN value_type_id uuid REFERENCES value_types(id) ON DELETE SET NULL;

ALTER TABLE shared_properties
    ADD COLUMN value_type_id uuid REFERENCES value_types(id) ON DELETE SET NULL;

CREATE INDEX idx_otp_value_type
    ON object_type_properties (value_type_id) WHERE value_type_id IS NOT NULL;
CREATE INDEX idx_shared_properties_value_type
    ON shared_properties (value_type_id) WHERE value_type_id IS NOT NULL;

COMMENT ON COLUMN object_type_properties.value_type_id IS
    'The value type constraining this property (Foundry p.227), or NULL. '
    'ON DELETE SET NULL for shared_property_id''s reason (0053): deleting a '
    'reusable definition must not delete the properties that referenced it.';

-- Same shape as `shared_properties_isolation` (0053): visible to whoever can
-- see the workspace. The versions inherit through their parent, the way
-- `module_states` inherits through `canvas_apps` (0048) - RLS applies inside
-- subqueries, so "a row exists in value_types with this id" *is* the question
-- "may you see this value type", and writing the rule out again here would be
-- a second copy to keep in step.
ALTER TABLE value_types ENABLE ROW LEVEL SECURITY;
CREATE POLICY value_types_isolation ON value_types
    USING (rls_can_access_workspace(workspace_id));

ALTER TABLE value_type_versions ENABLE ROW LEVEL SECURITY;
CREATE POLICY value_type_versions_isolation ON value_type_versions
    USING (EXISTS (SELECT 1 FROM value_types vt WHERE vt.id = value_type_id));
