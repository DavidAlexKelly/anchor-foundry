-- A listener's events, forgotten once archived and old (§915).
--
-- `listener_events` kept every event a listener ever took, body and all, up
-- to 1 MB each (0106), after the archive had copied it into the backing
-- dataset (0108). A listener takes up to a hundred requests a second, so one
-- busy sender could fill the database's 500 GB ceiling in hours, and a quiet
-- one would in months; a full database stops every workspace on the stack,
-- not the listener's. The stream is where events wait to be archived and
-- what the listener's screen shows; the backing dataset is the record
-- (`data-connection` p.261: "Events are written to a stream ... the stream's
-- backing dataset").
--
-- So an event is deleted once it is archived - at or below its listener's
-- `archived_through`, with a dataset to have gone into - and older than the
-- caller's retention. An event not yet archived is kept however old it is.
-- 0108's "deleting the dataset starts the archive again from the first
-- event" now starts from the oldest event still held (ERRATA.md).
--
-- At most `p_limit` events a call, so the worker deletes in short
-- transactions; it calls again while a call fills its limit. Anything under a
-- day is refused, so a mistaken setting cannot empty the screen people use to
-- see what just arrived.
CREATE FUNCTION prune_archived_listener_events(p_older_than interval, p_limit integer)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    n integer;
BEGIN
    IF p_older_than < interval '1 day' THEN
        RAISE EXCEPTION 'listener events are kept at least a day, not %', p_older_than;
    END IF;
    DELETE FROM listener_events
     WHERE id IN (
         SELECT e.id
           FROM listener_events e
           JOIN listeners l ON l.id = e.listener_id
          WHERE l.archive_dataset_id IS NOT NULL
            AND e.id <= l.archived_through
            AND e.received_at < now() - p_older_than
          ORDER BY e.id
          LIMIT p_limit
     );
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END;
$$;

REVOKE EXECUTE ON FUNCTION prune_archived_listener_events(interval, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION prune_archived_listener_events(interval, integer) TO platform_app;
