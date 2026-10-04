-- The trigger that stamps an object's workspace reads its type as the table's
-- owner (§899).
--
-- 0158 (§817) put the type's workspace on every object so the row policy
-- need not join. Its trigger read the type with no privilege of its own, so
-- the lookup ran under `object_types`' row policies, evaluated afresh for
-- every row: each trigger call is its own query. Measured on a scheduled sync
-- of a thousand objects, the trigger was 371 ms of a 427 ms statement. E.4
-- had measured the worker's sync at 42 s for a million rows before 0158; it
-- took 39 s for a hundred thousand after.
--
-- As SECURITY DEFINER it is a primary-key read: 8 ms for the same thousand,
-- 41 ms for the statement. **Nothing is admitted that was refused.** 0158
-- reasoned that a type the writer cannot see yields no workspace, which the
-- policy then refuses. Read as the owner, that type yields its own
-- workspace, which is not one of the writer's, and `oi_isolation` refuses
-- the row on the same check. `test_object_instance_workspace` asserts both
-- refusals.
ALTER FUNCTION object_instances_set_workspace() SECURITY DEFINER;
ALTER FUNCTION object_instances_set_workspace() SET search_path = public;
