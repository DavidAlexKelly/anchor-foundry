-- ============================================================================
-- 0112_webhook_steps.sql
-- Chained calls in one webhook (§523; `data-connection` p.234-237).
--
--     "A single webhook may contain multiple requests. Requests may be
--      chained together, with response values from a previous call
--      referenced in subsequent calls." (p.234)
--
-- **The calls before the webhook's own request**, in order. The webhook's
-- row keeps being its last call, the one whose response p.229's outputs
-- read, so a webhook with no steps is exactly what it was before this
-- column. Each step is {method, path, body, safe, extract: [{api_name,
-- path}]}. What a step extracts, later calls may reference as
-- `{{{api_name}}}`, the same way they reference an input.
--
-- p.237's rule, that "only one call is allowed to use an unsafe HTTP
-- method" unless a call is marked `isHttpMethodSafe`, is checked by
-- `webhooks.parse` on every save. A document that broke it could only have
-- been written around the API.
-- ============================================================================

ALTER TABLE webhooks
    ADD COLUMN steps jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(steps) = 'array' AND jsonb_array_length(steps) <= 9);
