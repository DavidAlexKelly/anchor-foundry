-- When a link type was last changed (§317; `ontology.md` §6;
-- `ontology-manager` p.30).
--
--     "Hovering over the Back home button will also bring up quick links to
--      recently edited object types, link types, and action types, as well as
--      all resources that are related to the one you are currently viewing."
--      (p.30)
--
-- **Two of the three kinds could already answer this and one could not.**
-- `object_types` (db 0003) and `action_types` (db 0013) each carry `updated_at`
-- with the `set_updated_at()` trigger on them. `link_types` was written in the
-- same migration as the first of those and did not get one — and then gained
-- six editable columns over the following fifty migrations, every one of them
-- a way to change a link type with no record that anything had changed:
--
--   * `from_property` and `to_property` (db 0027, link traversal)
--   * `from_side_name` and `to_side_name` (db 0043, what the relationship is
--     called from each end)
--   * `status` and `deprecation` (db 0055, the ontology statuses)
--
-- So "recently edited link types" had no column to read, and the nearest
-- available one — `created_at` — answers a different question. A list headed
-- *recently edited* that is silently sorted by *recently created* is §214's
-- control that looks like it works: the order is plausible, the heading is
-- wrong, and nothing on the screen says which.
--
-- **Backfilled from `created_at`, not from `now()`.** A column defaulting to
-- now() would tell every link type in every workspace that it was edited the
-- moment this migration ran, and p.30's list would open on a hundred rows that
-- are all equally and falsely recent. `created_at` is the last moment we can
-- actually vouch for: a row nobody has edited since it was made was, as far as
-- any record here goes, last written when it was created. Edits made before
-- this migration are lost either way — that data was never captured — and the
-- honest of the two guesses is the one that does not claim they happened
-- today.

ALTER TABLE link_types
    ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();

UPDATE link_types SET updated_at = created_at;

-- BEFORE UPDATE, like every other table's: the value is written on the way
-- through so no caller has to remember, and a caller that sets it by hand is
-- overruled rather than trusted. `enforce_link_type_workspace` is also a
-- BEFORE trigger on this table; the two are independent and Postgres fires
-- them in name order, which neither depends on.
CREATE TRIGGER trg_link_types_updated BEFORE UPDATE ON link_types
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
