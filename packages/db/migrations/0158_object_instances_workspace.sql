-- §817: an object knows its workspace, so its policy need not ask its type.
--
-- Roadmap phase 3, E.4 named this as the Postgres store's floor: "A count or a
-- sum reads every row. The count pays about 0.3 µs a row for the policy
-- checks (39 ms without RLS) ... without a structural change, such as putting
-- `workspace_id` on `object_instances` so the policy needs no join." At a
-- million objects that is most of a 292 ms count: `oi_isolation` checks each
-- row's type with `EXISTS (SELECT 1 FROM object_types ...)`, a join per row,
-- where the type's workspace never changes and could have been read once.
--
-- So the row carries it, and the policy compares a column with the
-- statement's workspaces (computed once, migration 0155).
--
-- **Set by the database, never by a caller.** A trigger copies the type's
-- workspace on insert and on any change of type, and a value a caller passes
-- is overwritten. Together with the policy's WITH CHECK this refuses exactly
-- what the join refused: an object written into a type the writer can see
-- gets that type's workspace, and one written into a type the writer cannot
-- see gets none - both refused by the policy, which runs before NOT NULL.
-- So the trigger needs no privilege of its own, and has none.
--
-- **A type cannot change workspace**, now enforced rather than merely true of
-- the code: the copied value is only as good as that, so a second trigger
-- refuses the update that would make the two disagree.
--
-- The backfill rewrites every row once. On the development database (114,000
-- objects) it takes about a second; a deployment with millions of objects
-- should expect tens of seconds, inside the migration Lambda's five minutes.

ALTER TABLE object_instances ADD COLUMN workspace_id uuid;

UPDATE object_instances i
   SET workspace_id = t.workspace_id
  FROM object_types t
 WHERE t.id = i.object_type_id;

ALTER TABLE object_instances ALTER COLUMN workspace_id SET NOT NULL;

CREATE FUNCTION object_instances_set_workspace() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    SELECT t.workspace_id INTO NEW.workspace_id
      FROM object_types t
     WHERE t.id = NEW.object_type_id;
    RETURN NEW;
END
$$;

CREATE TRIGGER trg_object_instances_workspace
    BEFORE INSERT OR UPDATE OF object_type_id, workspace_id ON object_instances
    FOR EACH ROW EXECUTE FUNCTION object_instances_set_workspace();

CREATE FUNCTION object_types_keep_workspace() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id THEN
        RAISE EXCEPTION 'an object type cannot move to another workspace'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER trg_object_types_keep_workspace
    BEFORE UPDATE OF workspace_id ON object_types
    FOR EACH ROW EXECUTE FUNCTION object_types_keep_workspace();

DROP POLICY oi_isolation ON object_instances;
CREATE POLICY oi_isolation ON object_instances
    USING (workspace_id = ANY ((SELECT rls_workspace_ids())::uuid[]));

-- **And an index that holds it**, which is most of the gain. Both policies
-- now read only `workspace_id` and `object_type_id` (the kiosk one reads the
-- type), so with the two in one narrow index a count is answered from the
-- index alone. Without it, the new column would make every count read every
-- row from the heap, while the join it replaced had at least kept the policy
-- inside the type index. Measured at a million objects once autovacuum has
-- been: a count took 217 ms with the join and takes 56 ms with this. Adding the column to
-- 0156's ordering index as INCLUDE was tried: the planner judged that wider
-- index dearer than the table and scanned the table.
CREATE INDEX idx_object_instances_type_workspace
    ON object_instances (object_type_id, workspace_id);

-- **Statistics as soon as a big sync lands.** With two indexes on the type, a
-- stale plan is no longer a harmless one. Straight after a million rows
-- arrived, the planner still believed the table small, chose this index plus
-- a sort of every row over the ordering index's walk to the first fifty, and
-- the first page took half a second until autovacuum's next ANALYZE. The
-- application role cannot ANALYZE a table it does not own, so this is the
-- owner's, callable by it. A sync calls it after writing ten thousand rows or
-- more; smaller ones leave the statistics to autovacuum.
CREATE FUNCTION analyze_object_instances() RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    ANALYZE object_instances;
END
$$;
