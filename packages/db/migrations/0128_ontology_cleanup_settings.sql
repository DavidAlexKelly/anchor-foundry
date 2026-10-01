-- p.72's "Configure Ontology cleanup" (§619; `ontology-manager` p.72-73).
--
-- > "The cleanup page contains a subpage that allows you to customize the flags
-- > used and their respective priority… with a choice of using either the
-- > default set or custom flags. Like snoozing object types from the queue,
-- > this is an individual customization that does not affect other Ontology
-- > editors." (p.72)
--
-- One row per person per workspace, and **no row is the default set**: a
-- person who never opened the settings has nothing stored, and so follows the
-- default as it changes. p.72's own caveat is what a stored custom list does:
-- "if using a custom flag setup, new flags that get added in the future will
-- not be automatically turned on".
CREATE TABLE ontology_cleanup_settings (
    workspace_id uuid        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id      uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- The flags turned on, most urgent first: p.72's "flags used and their
    -- respective priority" as one ordered list, so an order can never name a
    -- flag that is off. Which names are flags is the service's to say
    -- (`ontology_cleanup.FLAG_PRIORITY`), as it is for every flag computed.
    flags        text[]      NOT NULL,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, user_id),
    CHECK (cardinality(flags) <= 32)
);

ALTER TABLE ontology_cleanup_settings ENABLE ROW LEVEL SECURITY;

-- **Your own row and nobody else's**, db 0080's rule for p.71's snooze and for
-- p.72's reason: "an individual customization that does not affect other
-- Ontology editors". The workspace is checked here rather than left to a
-- caller, as there.
CREATE POLICY ontology_cleanup_settings_own ON ontology_cleanup_settings
    USING (user_id = rls_current_user_id()
           AND workspace_id = ANY (rls_workspace_ids()))
    WITH CHECK (user_id = rls_current_user_id()
           AND workspace_id = ANY (rls_workspace_ids()));

GRANT SELECT, INSERT, UPDATE, DELETE ON ontology_cleanup_settings TO platform_app;

COMMENT ON TABLE ontology_cleanup_settings IS
    'p.72''s custom cleanup flags (db 0128): the flags one person uses, in '
    'their order. No row is the default set.';
