-- 0093 — how often each layout of a module is viewed (§397; `workshop`
-- p.186-188)
--
--     "Layout view metrics track how many times each page, tab, and overlay in
--      the module has been viewed by users. The overview card displays total
--      views across all layouts, and the list view breaks down views by
--      individual layout item." (p.186)
--
-- **Opt-in, which p.187 requires and this column is.** "Layout view metrics
-- require builders to opt in… Toggle on Usage Metrics Tracking." Action
-- metrics needed no such thing (§396, p.186) because they are counted from
-- rows this platform already had; a view is not recorded anywhere until
-- somebody asks for it to be, so the asking has to be stored.
--
-- **Aggregated on write, not on read, and not daily.** p.187 describes
-- Foundry's pipeline: "Layout view data is processed in a daily aggregation, so
-- new views are reflected once per day rather than in real time." That latency
-- is a consequence of scale rather than a feature — nobody wants to wait a day
-- to see whether their new page is being used — so this counts into a row per
-- (module, layout, day) as the view happens and reports in real time.
--
-- The shape matters as much as the timing. A row per *view* would be unbounded
-- and would need a retention sweep this schema does not have (db 0092's header
-- says so about its own table); a row per layout per day is bounded by the
-- module's size and the window, and answers p.188's three periods with a sum.
-- What is lost is the time of day a view happened, which nothing on p.186-188
-- asks for.
--
-- **No user, ever.** p.185: "All metrics are aggregate counts and are not
-- attributable to any specific user." There is no `viewed_by` column to
-- forget to leave out later, which is the only way to keep that promise
-- against a future reader who thinks one would be useful.

ALTER TABLE canvas_apps
    ADD COLUMN track_usage boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN canvas_apps.track_usage IS
    'p.187''s Usage Metrics Tracking: whether layout views are recorded for '
    'this module. Off by default, because a view is a record of what somebody '
    'did and collecting one nobody asked for is a decision, not a default.';

CREATE TABLE canvas_layout_views (
    canvas_app_id uuid NOT NULL REFERENCES canvas_apps(id) ON DELETE CASCADE,

    -- The page, tab or overlay node. Not a foreign key to anything: a layout
    -- lives inside a jsonb document, and a node deleted from it leaves a count
    -- that was true when it was recorded. The panel resolves names from the
    -- *current* document and shows what it cannot name as the id, which is
    -- honest about a page that has since been removed.
    node_id       text NOT NULL CHECK (length(node_id) BETWEEN 1 AND 200),

    -- The day, in UTC. `date` rather than a timestamp, because that is the
    -- grain: two views a minute apart on the same day are one row, and a row
    -- that carried a time would invite somebody to read an hourly trend out of
    -- a daily counter.
    day           date NOT NULL,

    views         bigint NOT NULL DEFAULT 0 CHECK (views >= 0),

    PRIMARY KEY (canvas_app_id, node_id, day)
);

-- The read is always "this module, this window", so the key's leading column
-- does the work and this index carries the range.
CREATE INDEX idx_canvas_layout_views_window
    ON canvas_layout_views (canvas_app_id, day DESC);

ALTER TABLE canvas_layout_views ENABLE ROW LEVEL SECURITY;
CREATE POLICY clv_isolation ON canvas_layout_views
    USING (EXISTS (SELECT 1 FROM canvas_apps a
                   WHERE a.id = canvas_app_id
                     AND rls_can_access_project(a.project_id)));

GRANT SELECT, INSERT, UPDATE ON canvas_layout_views TO platform_app;

COMMENT ON TABLE canvas_layout_views IS
    'Daily view counts per layout node of a Workshop module (db 0093; '
    'workshop p.186-188). Aggregated on write so the panel is real time, '
    'which is a deliberate divergence from p.187''s daily pipeline - that '
    'latency is a consequence of scale rather than something anybody wants.';
