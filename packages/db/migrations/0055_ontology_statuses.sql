-- ============================================================================
-- 0055_ontology_statuses.sql
-- Ontology resource statuses (parity `docs/parity/ontology.md` §1.3; Foundry
-- `object-link-types` p.253-259).
--
-- > "Every object type, property, link type, action, or interface in the
-- > Ontology has a status that indicates developmental state… Status metadata
-- > helps Ontology-editing users to know what resources are being actively
-- > relied on by user applications." (p.253)
--
-- **A status is a promise about stability, and the refusals are what make it
-- one.** p.256 turns `active` into "cannot be deleted"; p.257 turns an
-- experimental object type into an experimental link type. A column with none
-- of that behind it would be a label somebody would believe, which is the
-- shape of gap `required` had before §154.
--
-- Why one enum across four tables
-- -------------------------------
-- p.253 gives one list for every kind of ontological resource, and p.257's
-- propagation table compares an object type's status directly against a link
-- type's. Two enums that had to be compared would be two orderings to keep in
-- step; `promoted` being object-types-only (p.255) is a *rule*, enforced in
-- `services/ontology_status.py` where the refusal can name the kind, rather
-- than a second type that would make the comparison need a cast.
--
-- Defaulting to `experimental`, including for rows that already exist
-- -----------------------------------------------------------------
-- p.256: "By default, any new ontological resource will be given the
-- `experimental` status." The backfill uses the same value, and that is the
-- conservative direction rather than the convenient one: marking every
-- existing object type `active` would make it undeletable, which is a
-- migration silently taking an operation away.
--
-- The deprecation details are jsonb for `value_format`'s reason (0049): p.254
-- names three fields (why, by when, what replaces it), all optional, and
-- three nullable columns per table across four tables would be twelve columns
-- that are almost always null.
-- ============================================================================

CREATE TYPE ontology_status AS ENUM (
    -- Ordered here as p.254 lists them; the *ranking* that p.257's table needs
    -- lives in Python, because "which of these two is less production-ready"
    -- is a rule about the ontology rather than a fact about the storage.
    'promoted', 'active', 'experimental', 'deprecated', 'example'
);

ALTER TABLE object_types
    ADD COLUMN status ontology_status NOT NULL DEFAULT 'experimental',
    ADD COLUMN deprecation jsonb;

ALTER TABLE object_type_properties
    ADD COLUMN status ontology_status NOT NULL DEFAULT 'experimental',
    ADD COLUMN deprecation jsonb;

ALTER TABLE link_types
    ADD COLUMN status ontology_status NOT NULL DEFAULT 'experimental',
    ADD COLUMN deprecation jsonb;

ALTER TABLE action_types
    ADD COLUMN status ontology_status NOT NULL DEFAULT 'experimental',
    ADD COLUMN deprecation jsonb;

COMMENT ON COLUMN object_types.status IS
    'Developmental state (Foundry object-link-types p.253-259). `active` and '
    '`promoted` resources cannot be deleted (p.256); an experimental object '
    'type drags its properties and link types down with it (p.256-257). '
    'Rules in services/ontology_status.py.';

COMMENT ON COLUMN object_types.deprecation IS
    'p.254: why it is being deprecated, when it is expected to be deleted, and '
    'what replaces it. NULL on anything not deprecated, and cleared when a '
    'resource stops being deprecated - a resource explaining why it was going '
    'to be deleted, after somebody decided not to, is worse than no note.';

-- Filtering an ontology to "what may I rely on" is the question p.253 says
-- statuses exist to answer, so it should not be a sequential scan once a
-- workspace has a few hundred types.
CREATE INDEX idx_object_types_status ON object_types (workspace_id, status);
