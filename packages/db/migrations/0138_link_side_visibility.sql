-- ============================================================================
-- 0138_link_side_visibility.sql
-- Per-side visibility on a link type (§714; Foundry `object-link-types` p.214,
-- p.217).
--
-- > "Visibility: An indication to user applications for how prominently to
-- > display the side of the link type (referring to links to the object type
-- > on that side). A prominent side of a link type will lead applications to
-- > show this side of the link type first to users. A hidden side of a link
-- > type will not appear in user applications. By default, the Employee and
-- > Company sides of the link type will have visibilities normal." (p.217)
--
-- **Per side, as the names are** (db 0043): `to_visibility` is the side you
-- arrive at by traversing from -> to, `from_visibility` the side reached going
-- the other way, so "the Company side is prominent" reads off the same column
-- pair as "the Company side is called Employer".
--
-- **NOT NULL DEFAULT 'normal'**, unlike the names: p.217 gives `normal` as
-- the default rather than "unset", and every existing link keeps drawing
-- exactly where it did.
-- ============================================================================

ALTER TABLE link_types
    ADD COLUMN from_visibility text NOT NULL DEFAULT 'normal',
    ADD COLUMN to_visibility   text NOT NULL DEFAULT 'normal';

ALTER TABLE link_types
    ADD CONSTRAINT link_types_from_visibility_valid
        CHECK (from_visibility IN ('normal', 'prominent', 'hidden')),
    ADD CONSTRAINT link_types_to_visibility_valid
        CHECK (to_visibility IN ('normal', 'prominent', 'hidden'));

COMMENT ON COLUMN link_types.from_visibility IS
    'Visibility of the side reached by traversing to -> from (Foundry p.217): '
    'prominent shows first, hidden does not appear in user applications.';
COMMENT ON COLUMN link_types.to_visibility IS
    'Visibility of the side reached by traversing from -> to (Foundry p.217).';
