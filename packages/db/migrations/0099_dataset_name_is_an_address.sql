-- ============================================================================
-- 0099_dataset_name_is_an_address.sql
-- A dataset's name is unique within its project (§435).
--
-- **This is a rule the platform already assumed and never wrote down.** A
-- transform declares what it reads by *name* — `-- input: raw = raw_orders` —
-- and `transform_publish.plan` resolves it through a dictionary keyed on
-- `datasets.name`. Two datasets with one name in a project means that
-- dictionary silently keeps whichever row the query returned last, and every
-- transform declaring that name reads a table nobody chose.
--
-- **It has been unreachable until now, which is why it was never a
-- constraint.** `UNIQUE (project_id, slug)` (0003) has done the work by
-- accident: a slug is derived from the name, so two names that differ produce
-- two slugs and two names that do not are refused at upload. §435 adds
-- renaming, and a rename changes the name without touching the slug — which
-- is the whole point of a stable slug, and is also the first way this platform
-- could have produced two datasets with one name.
--
-- So the constraint goes in rather than a check in the service: a rule that
-- lives in one service is a rule the next writer of an UPDATE does not meet,
-- and the failure it guards against is silent (§299's argument about tag
-- immutability, on a different table).
--
-- **The service still refuses first, with a sentence.** A constraint's message
-- names an index; a person renaming a dataset needs to be told which other
-- dataset has the name. Both, for the same reason `code_tags` has both.
-- ============================================================================

ALTER TABLE datasets
    ADD CONSTRAINT datasets_name_unique_in_project UNIQUE (project_id, name);

COMMENT ON CONSTRAINT datasets_name_unique_in_project ON datasets IS
    'A dataset''s name is how a transform declares it as an input '
    '(transform_declarations.py), so it has to address exactly one dataset. '
    'Enforced here rather than in a service because the failure is silent: a '
    'duplicate name makes the publish planner pick a table nobody chose.';
