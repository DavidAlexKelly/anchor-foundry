-- ============================================================================
-- 0125_listener_types_signed_bodies.sql
-- Parity `docs/parity/data-connection.md` ("Listeners"). `data-connection`
-- p.262, p.265.
--
-- Five more of p.262's named listeners (§593) - Cisco Meraki, PandaDoc,
-- Dialpad, Twilio and Twilio SendGrid - each with the scheme its sender
-- documents (p.265: "the security protocols laid out by those external
-- systems"): a shared secret inside Meraki's payload, PandaDoc's HMAC in the
-- query string, Dialpad's body sent as an HS256 token, Twilio's HMAC-SHA1 of
-- the address and its parameters, and SendGrid's ECDSA signature checked with
-- the public key it gives. db 0124's lists, widened; `services/listeners.py`
-- holds the same ones and a test holds the two together.
-- ============================================================================

ALTER TABLE listeners
    DROP CONSTRAINT listeners_listener_type_check,
    DROP CONSTRAINT listeners_verification_check,
    DROP CONSTRAINT listeners_header_check;

ALTER TABLE listeners
    ADD CONSTRAINT listeners_listener_type_check
        CHECK (listener_type IN ('custom', 'slack', 'jira', 'github', 'gitlab', 'stripe',
                                 'shopify', 'pubsub', 'bitbucket', 'meta', 'azure_event_grid',
                                 'jotform', 'pagerduty', 'zendesk', 'airtable',
                                 'cisco_meraki', 'pandadoc', 'dialpad', 'twilio', 'sendgrid')),
    ADD CONSTRAINT listeners_verification_check
        CHECK (verification IN ('none', 'basic', 'header_secret', 'hmac_sha256',
                                'hmac_sha256_base64', 'slack_v0', 'stripe_v1', 'query_token',
                                'pagerduty_v1', 'zendesk', 'airtable',
                                'meraki', 'pandadoc', 'dialpad_jwt', 'twilio', 'sendgrid')),
    ADD CONSTRAINT listeners_header_check
        CHECK ((verification IN ('header_secret', 'hmac_sha256', 'hmac_sha256_base64',
                                 'slack_v0', 'stripe_v1', 'pagerduty_v1', 'zendesk',
                                 'airtable', 'twilio', 'sendgrid'))
               = (verification_header IS NOT NULL));
