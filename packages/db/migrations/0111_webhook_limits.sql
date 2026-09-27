-- ============================================================================
-- 0111_webhook_limits.sql
-- A webhook's concurrency and rate limits (§522; `data-connection` p.240).
--
--     "For each Webhook, you can set three types of limits that constrain how
--      the Webhook can be executed: time limits, concurrency limits, and rate
--      limits." (p.240)
--
-- The time limit is db 0067's `timeout_seconds`. p.240's default of 20 is
-- kept; its ceiling of 180 is not, for 0067's reason: a webhook runs inside
-- a request somebody is waiting on, which the load balancer closes after 60
-- idle seconds.
--
--     "A concurrency limit specifies the maximum number of Webhook
--      executions that run at a single time."
--     "A rate limit restricts how many times a Webhook can be executed within
--      a time window that you specify … every second, minute, hour, or day"
--
-- **Both are counted in the database**, by one function every execution
-- asks first, so they hold across API tasks. The function locks the
-- webhook's row, so two executions asking at once are answered one after
-- the other.
--
-- - A running execution holds a **slot** until it finishes. A slot also
--   expires 30 seconds after the webhook's timeout, so an API task that
--   dies mid-call cannot hold one for ever.
-- - The rate is a **calendar window**: this second, minute, hour or day
--   (UTC). It counts executions that were let through, so a refused one
--   does not use up the window.
--
-- NULL is no limit, the default for both, as p.240 sets neither by default.
-- ============================================================================

ALTER TABLE webhooks
    ADD COLUMN max_concurrent integer CHECK (max_concurrent BETWEEN 1 AND 100),
    ADD COLUMN rate_limit     integer CHECK (rate_limit BETWEEN 1 AND 1000000),
    ADD COLUMN rate_window    text CHECK (rate_window IN ('second', 'minute', 'hour', 'day')),
    ADD CONSTRAINT webhooks_rate_pair_check CHECK ((rate_limit IS NULL) = (rate_window IS NULL));

CREATE TABLE webhook_slots (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    webhook_id  uuid NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
    expires_at  timestamptz NOT NULL
);
CREATE INDEX idx_webhook_slots_webhook ON webhook_slots (webhook_id);

CREATE TABLE webhook_rates (
    webhook_id    uuid PRIMARY KEY REFERENCES webhooks(id) ON DELETE CASCADE,
    window_start  timestamptz NOT NULL,
    taken         integer NOT NULL CHECK (taken > 0)
);

-- Only the two functions below touch these: no grants, and RLS with no
-- policy, so nothing else can.
ALTER TABLE webhook_slots ENABLE ROW LEVEL SECURITY;
ALTER TABLE webhook_rates ENABLE ROW LEVEL SECURITY;

-- Whether an execution may start. `refused` is 'concurrency' or 'rate' when
-- it may not; otherwise `slot` is the slot to release afterwards (NULL when
-- the webhook has no concurrency limit, so there is nothing to hold).
-- The concurrency check comes first, so an execution refused for it does
-- not also use up the rate window.
CREATE FUNCTION admit_webhook_call(p_webhook uuid)
RETURNS TABLE(slot uuid, refused text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public
SET TimeZone = 'UTC'
AS $$
DECLARE
    w record;
    win timestamptz;
    held uuid;
BEGIN
    SELECT max_concurrent, rate_limit, rate_window, timeout_seconds INTO w
      FROM webhooks WHERE id = p_webhook FOR UPDATE;
    IF NOT FOUND THEN
        RETURN QUERY SELECT NULL::uuid, NULL::text;
        RETURN;
    END IF;
    IF w.max_concurrent IS NOT NULL THEN
        DELETE FROM webhook_slots WHERE webhook_id = p_webhook AND expires_at <= now();
        IF (SELECT count(*) FROM webhook_slots WHERE webhook_id = p_webhook) >= w.max_concurrent THEN
            RETURN QUERY SELECT NULL::uuid, 'concurrency'::text;
            RETURN;
        END IF;
    END IF;
    IF w.rate_limit IS NOT NULL THEN
        win := date_trunc(w.rate_window, now());
        IF EXISTS (SELECT 1 FROM webhook_rates
                    WHERE webhook_id = p_webhook AND window_start = win AND taken >= w.rate_limit) THEN
            RETURN QUERY SELECT NULL::uuid, 'rate'::text;
            RETURN;
        END IF;
        INSERT INTO webhook_rates AS r (webhook_id, window_start, taken) VALUES (p_webhook, win, 1)
        ON CONFLICT (webhook_id) DO UPDATE
           SET taken = CASE WHEN r.window_start = EXCLUDED.window_start THEN r.taken + 1 ELSE 1 END,
               window_start = EXCLUDED.window_start;
    END IF;
    IF w.max_concurrent IS NOT NULL THEN
        INSERT INTO webhook_slots (webhook_id, expires_at)
        VALUES (p_webhook, now() + make_interval(secs => w.timeout_seconds + 30))
        RETURNING id INTO held;
    END IF;
    RETURN QUERY SELECT held, NULL::text;
END
$$;

CREATE FUNCTION release_webhook_slot(p_slot uuid) RETURNS void
LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path = public
AS $$
    DELETE FROM webhook_slots WHERE id = p_slot
$$;

REVOKE EXECUTE ON FUNCTION admit_webhook_call(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admit_webhook_call(uuid) TO platform_app;
REVOKE EXECUTE ON FUNCTION release_webhook_slot(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION release_webhook_slot(uuid) TO platform_app;
