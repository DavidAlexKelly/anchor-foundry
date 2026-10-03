-- ============================================================================
-- 0140_render_hints.sql
-- A property's render hints (§724; `object-link-types` p.91, p.181-182,
-- p.188, p.248-252).
--
--     "Foundry uses render hints to communicate information about the use of
--      Ontology properties to Object Storage v1 (Phonograph) and user
--      applications in the platform. For example, the sortable render hint on
--      a string property tells applications to allow users to sort on that
--      property, as in a timeline or a chart." (p.248)
--
-- **A checklist, stored as the names checked** (`services/render_hints.py`
-- owns the list and its rules). Searchable, Selectable and Sortable are on
-- unless somebody turns them off: p.182 tells a builder they "can deselect
-- the searchable and sortable render hints", and p.250's Selectable is
-- described by what disabling it saves. So every property that exists today
-- keeps doing what it did - searched, aggregated and sorted - which is also
-- what every application here assumed before the hints existed.
--
-- A shared property carries its own, and they **override** an attached
-- property's (p.188: "using the shared property will override the
-- configuration values of the selected property") - the opposite of type
-- classes, which db 0139 joins.
--
-- Phonograph's half - "Adds raw index?", "Requires reindex?" (p.249) - has no
-- counterpart: this instance store builds no per-property index to add or
-- drop, so a hint here takes effect in applications as soon as it is saved.
-- ============================================================================

ALTER TABLE object_type_properties
    ADD COLUMN render_hints text[] NOT NULL
        DEFAULT '{selectable,sortable,searchable}';

ALTER TABLE shared_properties
    ADD COLUMN render_hints text[] NOT NULL
        DEFAULT '{selectable,sortable,searchable}';

COMMENT ON COLUMN object_type_properties.render_hints IS
    'Render hints (object-link-types p.248-252), checked in '
    'services/render_hints.py. Overridden by a shared property''s (p.188).';
COMMENT ON COLUMN shared_properties.render_hints IS
    'Render hints (object-link-types p.182), overriding an attached '
    'property''s own (p.188).';
