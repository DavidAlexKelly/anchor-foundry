-- ============================================================================
-- 0123_section_position.sql
-- Parity `docs/parity/ontology.md` §4 ("Configure sections in the action
-- form"). `action-types` p.124.
--
--     "The Form tab lists the sections with their parameters in a single
--      overview... Parameters and sections display in the form based on their
--      order in this Form Content section." (p.124)
--
-- One order over both, which db 0081 could not say: a section had its place
-- among sections and a parameter its place among parameters, so the form drew
-- every parameter no section claimed and then every section. `loose_before`
-- is how many of those unsectioned parameters, in their own order, come before
-- the section. NULL is db 0081's layout - after all of them - which is where
-- every section written before this unit stays.
--
-- Sections keep `sort_order` among themselves, and `replace_sections` refuses
-- a section placed above one before it: Form Content is one list, and two
-- orders that disagreed would have no answer.
-- ============================================================================

ALTER TABLE action_sections
    ADD COLUMN loose_before integer CHECK (loose_before >= 0);

COMMENT ON COLUMN action_sections.loose_before IS
    'action-types p.124: how many unsectioned parameters come before this '
    'section in the one Form Content order. NULL: after all of them.';
