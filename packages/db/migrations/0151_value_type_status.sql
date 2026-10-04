-- ============================================================================
-- 0151_value_type_status.sql
-- Parity `docs/parity/ontology.md` §1.3 (Value types: "Missing: … deprecation
-- (p.229), which is §1.3's Status row rather than a second flag"); Foundry
-- `object-link-types` p.229, p.253-256 (§764).
--
-- > "if you make breaking changes to the constraints and your value type has
-- > consumers, we recommend deprecating the current value type and creating a
-- > new one instead." (p.229)
--
-- The same `ontology_status` every other ontology resource carries (db 0055),
-- with p.254's deprecation note beside it. The rules are p.256's and live in
-- `services/ontology_status.py`: an `active` value type cannot be deleted. A
-- deprecated one keeps the properties it already constrains and takes no new
-- ones, which is what "deprecating … and creating a new one" asks of it.
-- ============================================================================

ALTER TABLE value_types
    ADD COLUMN status ontology_status NOT NULL DEFAULT 'experimental',
    ADD COLUMN deprecation jsonb;
