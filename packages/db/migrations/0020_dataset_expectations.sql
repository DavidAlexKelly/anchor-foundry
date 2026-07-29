-- ============================================================================
-- 0020_dataset_expectations.sql
-- Data quality expectations per dataset (roadmap Datasets item 2) - this
-- platform's analog of Foundry's Data Health checks, and the foundation the
-- Models pillar's build-gating item depends on.
--
-- A rule is one assertion about one column: it is never null, its values are
-- unique, it stays inside a range, it matches a pattern, or it simply exists.
-- Severity decides what a failure means: 'error' fails the dataset's health,
-- 'warn' surfaces without condemning it - the distinction matters because
-- "this column has some nulls" and "this join key has duplicates" are not the
-- same kind of news.
--
-- WHEN RULES ARE EVALUATED - the one place this deviates from the roadmap,
-- which said "evaluated against every new version at creation time ... one
-- evaluation point, called from wherever dataset_versions rows are currently
-- created". There are seven such places across two independently deployed
-- codebases (upload, two sync paths, two model paths, action write-back, and
-- the worker's mirrors of the sync/model ones), and wiring each of them is
-- both a large blast radius and, more importantly, wrong in a way that only
-- shows up later: a result computed at creation time is stale the moment
-- somebody edits the rules, which is exactly when a health badge most needs
-- to be right.
--
-- So results are computed on demand and cached on the version, and *any*
-- change to a dataset's rules clears the cache for that dataset. Consumers -
-- the health badge, and model gating later - read through one function that
-- computes-if-absent, so every one of the seven creation paths is covered
-- without touching any of them. A version nobody ever asks about is never
-- evaluated, which costs nothing because the result only exists to be read.
--
-- The one thing this does *not* support, flagged so it is a decision rather
-- than an omission: alerting on failure at the moment a bad version lands
-- (notify-on-failure) would need genuine eager evaluation, because there is
-- no reader to trigger the computation. Add that here if alerting is built.
-- ============================================================================

CREATE TABLE dataset_expectations (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id   uuid NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    rule_type    text NOT NULL CHECK (rule_type IN (
                     'not_null', 'unique', 'value_in_range',
                     'regex_match', 'column_exists')),
    column_name  text NOT NULL CHECK (length(column_name) BETWEEN 1 AND 200),
    -- Rule-specific parameters: {min,max} for value_in_range, {pattern} for
    -- regex_match, empty for the rest. Kept opaque here for the same reason
    -- canvas definitions and action submitted_values are: the shape belongs to
    -- the layer that understands the rule, not to the schema.
    config       jsonb NOT NULL DEFAULT '{}'::jsonb,
    severity     text NOT NULL DEFAULT 'error' CHECK (severity IN ('error', 'warn')),
    created_by   uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    -- One rule of a given kind per column per dataset: two identical not-null
    -- checks on the same column are a mistake, not a configuration.
    UNIQUE (dataset_id, rule_type, column_name)
);

CREATE INDEX idx_dataset_expectations_dataset ON dataset_expectations (dataset_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON dataset_expectations TO platform_app;

-- Visibility follows the dataset, same one-hop shape as dsv_isolation above:
-- the subselect triggers datasets' own policy, whose helper is SECURITY
-- DEFINER, so there is no cycle back into this table.
ALTER TABLE dataset_expectations ENABLE ROW LEVEL SECURITY;
CREATE POLICY dsx_isolation ON dataset_expectations
    USING (EXISTS (SELECT 1 FROM datasets d
                   WHERE d.id = dataset_id
                     AND rls_can_access_project(d.project_id)));

-- Cached evaluation for a version. NULL means "not evaluated against the
-- current rules" - either never asked for, or invalidated by a rule change -
-- which is the signal the read path uses to recompute.
ALTER TABLE dataset_versions ADD COLUMN expectation_results jsonb;

COMMENT ON COLUMN dataset_versions.expectation_results IS
    'Cached expectation evaluation for this version: '
    '{"status","evaluated_at","results":[...]}. NULL means not evaluated '
    'against the current rules - cleared whenever the dataset''s rules change.';
