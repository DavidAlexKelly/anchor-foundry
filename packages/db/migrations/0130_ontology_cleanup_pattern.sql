-- p.74's two parameterised flags, per person (§630; `ontology-manager` p.72-74).
--
-- > "Display name regex matches string: The default value of
-- > \[test|deprecated\] would match object types that have [test] or
-- > [deprecated] in their display names … Supports ECMA (JavaScript) regex
-- > syntax." (p.74)
-- >
-- > "Datasource not updated in [x] days" (p.74)
--
-- db 0128 kept one person's flags and their order. These are the two flags
-- p.74 gives a value of their own, and p.72's rule covers them the same way:
-- "an individual customization that does not affect other Ontology editors".
--
-- **Each is independent of the others, so each is nullable**: NULL is the
-- default for that setting. `flags` becomes nullable for the same reason - a
-- person who sets a pattern has not thereby chosen a custom flag set, and
-- p.72's caveat about custom sets ("new flags that get added in the future
-- will not be automatically turned on") should not reach them for it. A row
-- whose three settings are all NULL is the default and is deleted rather than
-- kept, by the service.
ALTER TABLE ontology_cleanup_settings ALTER COLUMN flags DROP NOT NULL;

ALTER TABLE ontology_cleanup_settings
    -- Matched with Postgres's regular expressions, whose syntax is ECMA's for
    -- everything p.74's examples use, and whose engine does not backtrack its
    -- way into a runaway on a pattern somebody typed. Bounded so a pattern is
    -- a pattern and not a document.
    ADD COLUMN name_pattern text CHECK (length(name_pattern) BETWEEN 1 AND 200),
    ADD COLUMN stale_days   integer CHECK (stale_days BETWEEN 1 AND 3650);

COMMENT ON COLUMN ontology_cleanup_settings.name_pattern IS
    'p.74''s "Display name regex matches string" for this person (db 0130); '
    'NULL is the default [test] and [deprecated] markers.';
COMMENT ON COLUMN ontology_cleanup_settings.stale_days IS
    'p.74''s "Datasource not updated in [x] days" for this person (db 0130); '
    'NULL is the default.';
