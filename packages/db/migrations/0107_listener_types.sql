-- ============================================================================
-- 0107_listener_types.sql
-- Named listener types, and the verification schemes they need (§518;
-- `data-connection` p.262, p.274, p.279, p.285-287).
--
--     "You can either configure a custom, basic authentication listener, or
--      one of the following listeners" (p.262)
--
-- **A type is a preset, not a second mechanism.** Choosing Slack fixes the
-- scheme (Slack's signed timestamp) and the header it arrives in, and asks
-- only for the signing secret (p.285: "In the field for Message Signing
-- Secret, enter the Signing Secret value"). So the type is one column, and
-- what it does is the scheme columns 0106 already has.
--
-- Four schemes the generic ones could not express:
--
-- - `hmac_sha256_base64`: an HMAC of the body, base64 rather than hex
--   (Shopify);
-- - `slack_v0`: an HMAC over `v0:{timestamp}:{body}`, with the timestamp in
--   its own header and refused when stale (Slack);
-- - `stripe_v1`: an HMAC over `{t}.{body}`, both carried in one header
--   (Stripe);
-- - `query_token`: a shared secret in the endpoint's query string (p.274:
--   "enter your shared secret into the URL field as a query parameter after
--   the listener endpoint URL. Example: ?token=<YOUR_TOKEN>").
--
-- The header rule widens with them: every scheme that reads a named header
-- stores which one, so the header is redacted from the stored event.
-- ============================================================================

ALTER TABLE listeners
    DROP CONSTRAINT listeners_verification_check,
    DROP CONSTRAINT listeners_check;

ALTER TABLE listeners
    ADD COLUMN listener_type text NOT NULL DEFAULT 'custom'
        CHECK (listener_type IN ('custom', 'slack', 'jira', 'github', 'gitlab', 'stripe',
                                 'shopify', 'pubsub')),
    ADD CONSTRAINT listeners_verification_check
        CHECK (verification IN ('none', 'basic', 'header_secret', 'hmac_sha256',
                                'hmac_sha256_base64', 'slack_v0', 'stripe_v1', 'query_token')),
    ADD CONSTRAINT listeners_header_check
        CHECK ((verification IN ('header_secret', 'hmac_sha256', 'hmac_sha256_base64',
                                 'slack_v0', 'stripe_v1')) = (verification_header IS NOT NULL));
