-- §804: the kiosk check asked once per statement, not once per row.
--
-- Six restrictive policies call `rls_kiosk_allows(kind, id)`, which inlines
-- to a CASE reading `current_setting('app.kiosk')` - per row, so counting a
-- million objects evaluated it a million times. Almost every request is not a
-- kiosk, and for those the answer never depends on the row.
--
-- `(SELECT coalesce(current_setting('app.kiosk', true), '') = '')` is an
-- InitPlan: computed once, and when it is true the OR is decided without the
-- per-row half. When it is false the original call decides, unchanged - and
-- that call begins by asking the same question, so the policy's truth table
-- is exactly what it was. Measured on a million-object type: a count under
-- RLS from 474 ms to 361 ms.

DO $$
DECLARE
    r record;
    off text := '(SELECT coalesce(current_setting(''app.kiosk'', true), '''') = '''')';
BEGIN
    FOR r IN
        SELECT schemaname, tablename, policyname, qual
          FROM pg_policies
         WHERE qual ~ 'rls_kiosk_allows\('
    LOOP
        EXECUTE format('ALTER POLICY %I ON %I.%I USING (%s)',
                       r.policyname, r.schemaname, r.tablename,
                       regexp_replace(r.qual, 'rls_kiosk_allows\(([^()]*)\)',
                                      '(' || off || ' OR rls_kiosk_allows(\1))', 'g'));
    END LOOP;
END
$$;
