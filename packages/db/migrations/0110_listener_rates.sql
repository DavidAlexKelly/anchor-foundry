-- ============================================================================
-- 0110_listener_rates.sql
-- A listener's rate limit (§521; `data-connection` p.261).
--
--     "Only low-throughput event streams should be pushed to HTTPS
--      listeners. HTTPS listeners are rate-limited at approximately 100
--      requests per second, so integrations requiring substantially higher
--      throughput should use streaming syncs or the public streaming API
--      endpoints when possible." (p.261)
--
-- **Counted in the database, not in each API process**, so the limit is one
-- listener's across however many API tasks are running. The count is one
-- row per listener: the second it is counting and how many requests that
-- second has taken. A request in a new second starts the count again, so
-- nothing needs sweeping away. p.261's "approximately" is this fixed
-- window: a burst straddling two seconds can take up to twice the limit.
--
-- **Every request that reaches a running listener counts**, including one
-- that then fails verification or is too big. The requests being limited
-- are the ones the platform has to read and check, and a sender that cannot
-- sign could otherwise send without limit. A request refused earlier (an
-- unknown address, a sender outside the allowlist, a stopped listener) is
-- not counted: it costs nothing to refuse, and counting it would let a
-- sender outside the allowlist use up the budget of those inside it.
--
-- The listener's screen says when a request was last refused for rate and
-- how many have been, since p.261's remedy is a conversation about the
-- limit, which starts with knowing it has been reached.
-- ============================================================================

CREATE TABLE listener_rates (
    listener_id   uuid PRIMARY KEY REFERENCES listeners(id) ON DELETE CASCADE,
    -- Unix seconds.
    second        bigint NOT NULL,
    taken         integer NOT NULL CHECK (taken > 0),
    throttled     bigint NOT NULL DEFAULT 0 CHECK (throttled >= 0),
    throttled_at  timestamptz
);

ALTER TABLE listener_rates ENABLE ROW LEVEL SECURITY;
CREATE POLICY listener_rate_isolation ON listener_rates
    USING (EXISTS (SELECT 1 FROM listeners l WHERE l.id = listener_id));

-- Read by the listener's screen; written only by the request path's function.
GRANT SELECT ON listener_rates TO platform_app;

-- Counts one request against the listener's second, and returns how many
-- that second has now taken. Over `p_limit`, the request is also recorded as
-- throttled: the caller refuses it, but in a transaction of its own after
-- this one commits, so the record stays.
CREATE FUNCTION take_listener_request(p_listener uuid, p_second bigint, p_limit integer)
RETURNS integer
LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path = public
AS $$
    INSERT INTO listener_rates AS r (listener_id, second, taken)
    VALUES (p_listener, p_second, 1)
    ON CONFLICT (listener_id) DO UPDATE
       SET second = EXCLUDED.second,
           taken = CASE WHEN r.second = EXCLUDED.second THEN r.taken + 1 ELSE 1 END,
           throttled = r.throttled
               + CASE WHEN r.second = EXCLUDED.second AND r.taken + 1 > p_limit THEN 1 ELSE 0 END,
           throttled_at = CASE WHEN r.second = EXCLUDED.second AND r.taken + 1 > p_limit
                               THEN now() ELSE r.throttled_at END
    RETURNING taken
$$;

REVOKE EXECUTE ON FUNCTION take_listener_request(uuid, bigint, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION take_listener_request(uuid, bigint, integer) TO platform_app;
