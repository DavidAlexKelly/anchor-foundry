-- Publishing pins a version (ROADMAP phase 2, item 1.7).
--
-- Today a published app shows viewers the *live* definition: every save an
-- author makes is immediately what everyone else sees, half-finished layouts
-- included. The publish dialog says so in its own copy, which is honest and
-- also an admission that publishing does not mean anything. This gives it a
-- meaning: viewers see the version that was published, and only a publish
-- moves them.
--
-- The snapshots already exist - `canvas_app_versions` has held one row per
-- save since migration 0003 - so this is a pointer, not a new store.
ALTER TABLE canvas_apps
    ADD COLUMN published_version integer
        CHECK (published_version IS NULL OR published_version > 0);

-- Backfill: every already-published app pins the version its viewers are
-- looking at *right now*. Nobody's view changes at the moment of migration,
-- and from here on it changes only when somebody publishes - which is the
-- whole point, and would be undermined by a migration that moved everyone's
-- app to something they had not seen.
--
-- `current_version = 0` means an app that has never been saved; its viewers
-- see an empty layout either way, and there is no version row to point at, so
-- it stays NULL and reads as "nothing published yet".
UPDATE canvas_apps
   SET published_version = current_version
 WHERE publish_scope <> 'private' AND current_version > 0;

COMMENT ON COLUMN canvas_apps.published_version IS
    'The canvas_app_versions.version_number viewers of a published app see. '
    'NULL means nothing has been published; saving never changes it.';
