-- ============================================================================
-- 0023_dataset_schema_policy.sql
-- Let a dataset refuse a version that breaks its schema.
--
-- 0018 made schema drift *visible* one sync after it happened. 0022 made a
-- model refuse to run on bad *values*. This is the missing half: bad
-- *shape*. A column disappearing or changing type breaks every downstream
-- model, object mapping, and canvas widget reading it, and today it lands
-- silently and is discovered three layers away at runtime.
--
--   permissive  today's behaviour, and the default
--   strict      a new version may not remove or retype an existing column
--
-- **Adding a column is not a breaking change, and strict allows it.** Taking
-- "must match the previous version's schema" literally would reject the most
-- common and most harmless drift there is - a source gaining a field - and a
-- policy people have to keep switching off is a policy nobody leaves on.
-- What breaks a downstream reader is a column going away or changing type
-- underneath it; those are what strict refuses.
--
-- **Any retype is breaking, including widening ones.** int -> bigint is
-- safe in practice and text -> int is not, but deciding which is which means
-- encoding a type lattice per source dialect, and being subtly wrong there
-- is worse than being bluntly right: a false negative silently breaks the
-- thing this exists to protect. The escape hatch is deliberate and
-- auditable - switch the dataset to permissive, let the version land, switch
-- back.
--
-- **Enforced by a trigger, which is a reversal worth explaining.** Migration
-- 0021 argued *against* putting logic in a database trigger, and that
-- argument still holds for what it was about: enqueueing model runs is
-- scheduling policy, which needs to be retried, rate-limited and reasoned
-- about in application code. This is a different kind of thing entirely - an
-- integrity constraint on a table, which is what a database is for, and the
-- same tool 0003's enforce_dataset_workspace() already uses to keep a
-- denormalised column honest.
--
-- The deciding factor is the alternative. There are seven places across two
-- independently deployed codebases that insert into dataset_versions
-- (upload, two sync paths, two model paths, action write-back, and the
-- worker's mirrors). Enforcing in all seven means the guarantee holds only
-- as long as nobody forgets, and the eighth writer inherits nothing. In the
-- trigger it holds for every writer that exists and every one that doesn't
-- yet. The cost is that a refusal surfaces as a database error the callers
-- have to translate - but a caller that forgets to translate it fails
-- loudly, which is the right direction to fail in.
--
-- SQLSTATE 'AF001' rather than a generic check_violation, so a caller can
-- tell "this dataset's schema policy refused the write" apart from every
-- other constraint on the table.
-- ============================================================================

CREATE TYPE dataset_schema_policy AS ENUM ('permissive', 'strict');

ALTER TABLE datasets
    ADD COLUMN schema_policy dataset_schema_policy NOT NULL DEFAULT 'permissive';

COMMENT ON COLUMN datasets.schema_policy IS
    'strict refuses a new version that removes or retypes an existing '
    'column; permissive (default) is unconstrained. Adding columns is '
    'allowed under both.';

CREATE FUNCTION enforce_dataset_schema_policy() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_policy    dataset_schema_policy;
    v_previous  jsonb;
    v_removed   text;
    v_retyped   text;
BEGIN
    SELECT schema_policy INTO v_policy FROM datasets WHERE id = NEW.dataset_id;
    IF v_policy IS DISTINCT FROM 'strict' THEN
        RETURN NEW;
    END IF;

    -- The version immediately before this one. Read by version_number rather
    -- than datasets.current_version because the writers disagree about
    -- ordering: some roll current_version before inserting the version row,
    -- some after.
    SELECT table_schema INTO v_previous
      FROM dataset_versions
     WHERE dataset_id = NEW.dataset_id
       AND version_number < NEW.version_number
     ORDER BY version_number DESC
     LIMIT 1;

    IF v_previous IS NULL THEN
        RETURN NEW;   -- a first version has nothing to break
    END IF;

    SELECT string_agg(p->>'name', ', ' ORDER BY p->>'name') INTO v_removed
      FROM jsonb_array_elements(v_previous) p
     WHERE NOT EXISTS (
         SELECT 1 FROM jsonb_array_elements(NEW.table_schema) c
          WHERE c->>'name' = p->>'name'
     );

    SELECT string_agg(
               format('%s (%s -> %s)', p->>'name', p->>'data_type', c->>'data_type'),
               ', ' ORDER BY p->>'name')
      INTO v_retyped
      FROM jsonb_array_elements(v_previous) p
      JOIN jsonb_array_elements(NEW.table_schema) c ON c->>'name' = p->>'name'
     WHERE p->>'data_type' IS DISTINCT FROM c->>'data_type';

    IF v_removed IS NOT NULL OR v_retyped IS NOT NULL THEN
        RAISE EXCEPTION 'schema policy: %',
            concat_ws('; ',
                CASE WHEN v_removed IS NOT NULL
                     THEN 'columns removed: ' || v_removed END,
                CASE WHEN v_retyped IS NOT NULL
                     THEN 'columns retyped: ' || v_retyped END)
            USING ERRCODE = 'AF001',
                  HINT = 'set this dataset''s schema policy to permissive to allow it';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_dataset_versions_schema_policy
    BEFORE INSERT ON dataset_versions
    FOR EACH ROW EXECUTE FUNCTION enforce_dataset_schema_policy();
