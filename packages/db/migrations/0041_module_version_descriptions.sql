-- ============================================================================
-- 0041_module_version_descriptions.sql
-- The Versions dialog (parity `docs/parity/workshop.md` §6; Foundry p.191-192).
--
-- Publishing already means the right thing (`STATUS.md` §88): saving does not
-- move viewers, publishing does, and `canvas_apps.published_version` records
-- which version they are on. What is missing is the dialog Foundry puts around
-- it, and two of the things that dialog shows do not exist yet.
--
-- **A description per version.** p.191: "Each saved version displays a
-- timestamp, editor, and description if available." The first two are already
-- columns; the third is not. It is nullable and stays nullable - a save with
-- nothing to say should not be blocked, and a mandatory description is how you
-- get a history of the word "update".
--
-- p.192 also makes descriptions editable after the fact ("Descriptions can be
-- viewed, added, and edited in the module's Versions dialog"), which is why
-- this is a column on the version rather than a field of the save request that
-- happens to be stored. A save is an event; a description is an annotation, and
-- annotations get corrected.
--
-- **Two settings, on the app rather than on a user.** p.192's "Automatically
-- publish when saving" and "Always prompt to add a version description when
-- saving" both live in the Versions dialog, which is per-module. Per-module is
-- also the only reading that makes sense: whether a module's viewers should see
-- every save is a fact about that module's audience, not about whoever happens
-- to be editing it.
--
-- Both default to the current behaviour, so no existing module changes: today
-- saving does not publish, and nothing prompts.
--
-- **`auto_publish_on_save` is deliberately a foot-gun with a safety on.** It
-- makes every save visible to viewers immediately, which is exactly what §88
-- was written to prevent by default. Foundry offers it because a module with
-- one builder and no audience yet is tedious to publish twice per change. It is
-- off unless somebody turns it on, and the UI says what it does.
-- ============================================================================

ALTER TABLE canvas_app_versions
    ADD COLUMN description text NOT NULL DEFAULT '';

ALTER TABLE canvas_apps
    ADD COLUMN auto_publish_on_save boolean NOT NULL DEFAULT false,
    ADD COLUMN prompt_for_description boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN canvas_app_versions.description IS
    'Optional note on what changed (Foundry p.191). Editable after the fact.';
COMMENT ON COLUMN canvas_apps.auto_publish_on_save IS
    'When true, saving also publishes - so viewers see every save (p.192).';
COMMENT ON COLUMN canvas_apps.prompt_for_description IS
    'When true, the builder is asked for a description on each save (p.192).';
