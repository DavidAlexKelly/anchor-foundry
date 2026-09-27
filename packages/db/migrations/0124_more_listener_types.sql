-- ============================================================================
-- 0124_more_listener_types.sql
-- Parity `docs/parity/data-connection.md` ("Listeners"). `data-connection`
-- p.262, p.265.
--
-- Seven more of p.262's named listeners (§591) - Bitbucket, Meta, Azure Event
-- Grid, Jotform, PagerDuty, Zendesk and Airtable - and the three schemes the
-- last three sign with, which p.265 leaves to "the security protocols laid out
-- by those external systems": PagerDuty's `v1=` signatures, Zendesk's
-- timestamped base64 HMAC, and Airtable's content MAC. db 0107's lists, widened;
-- `services/listeners.py` holds the same ones and a test holds the two together.
-- ============================================================================

ALTER TABLE listeners
    DROP CONSTRAINT listeners_listener_type_check,
    DROP CONSTRAINT listeners_verification_check,
    DROP CONSTRAINT listeners_header_check;

ALTER TABLE listeners
    ADD CONSTRAINT listeners_listener_type_check
        CHECK (listener_type IN ('custom', 'slack', 'jira', 'github', 'gitlab', 'stripe',
                                 'shopify', 'pubsub', 'bitbucket', 'meta', 'azure_event_grid',
                                 'jotform', 'pagerduty', 'zendesk', 'airtable')),
    ADD CONSTRAINT listeners_verification_check
        CHECK (verification IN ('none', 'basic', 'header_secret', 'hmac_sha256',
                                'hmac_sha256_base64', 'slack_v0', 'stripe_v1', 'query_token',
                                'pagerduty_v1', 'zendesk', 'airtable')),
    ADD CONSTRAINT listeners_header_check
        CHECK ((verification IN ('header_secret', 'hmac_sha256', 'hmac_sha256_base64',
                                 'slack_v0', 'stripe_v1', 'pagerduty_v1', 'zendesk',
                                 'airtable')) = (verification_header IS NOT NULL));
