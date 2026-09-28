-- ============================================================================
-- 0131_series_analyses.sql
-- Saved time series analyses (§662; `workshop` p.397).
--
-- > "Enable analysis saving: Save and share analyses for future reference.
-- >  Analyses can be saved as either Private or Public. Configure default save
-- >  location: Select a folder or use a string variable to provide the default
-- >  save location." (p.397)
--
-- **This follows db 0089's saved graphs**, the §191 check again: a saved
-- analysis is the Time Series Analysis widget's view - its plots, canvases,
-- event sets and axes - and never its readings, which are a live question.
--
-- **A project is the save location.** p.397's "folder" is where a resource
-- lives; a project is where every resource here lives, and what its access
-- follows.
--
-- **Private or Public, and RLS says which.** A private analysis is its
-- author's alone; a public one anyone who can read the project may open. Only
-- the author saves over or deletes one: another reader saves their own copy,
-- which is what "share" means for something a reader then changes. Four
-- policies rather than one, for db 0067's reason: the read rule is wider than
-- the write rule.
--
-- **One name per author per project.** Two of one person's analyses called
-- "Pump 3 in March" is the confusion a name exists to prevent; two people each
-- having one is not, and a unique name across authors would tell one of them
-- that a private analysis they cannot see exists.
-- ============================================================================

CREATE TABLE series_analyses (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        text NOT NULL CHECK (btrim(name) <> '' AND length(name) <= 200),
    visibility  text NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'public')),
    -- The widget's view: {plots, canvases, eventSets, axes}. jsonb for db
    -- 0040's reason - the widget's view grew fourteen times in §647-§661.
    state       jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by  uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, created_by, name)
);

CREATE INDEX idx_series_analyses_project ON series_analyses (project_id, name);

CREATE TRIGGER trg_series_analyses_updated BEFORE UPDATE ON series_analyses
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON COLUMN series_analyses.state IS
    'The Time Series Analysis view this reopens (db 0131): plots, canvases, '
    'event sets, axes. Never readings - they are read again when it opens.';

ALTER TABLE series_analyses ENABLE ROW LEVEL SECURITY;

CREATE POLICY series_analyses_read ON series_analyses FOR SELECT
    USING (rls_can_access_project(project_id)
           AND (visibility = 'public' OR created_by = rls_current_user_id()));

CREATE POLICY series_analyses_create ON series_analyses FOR INSERT
    WITH CHECK (rls_can_access_project(project_id) AND created_by = rls_current_user_id());

CREATE POLICY series_analyses_change ON series_analyses FOR UPDATE
    USING (rls_can_access_project(project_id) AND created_by = rls_current_user_id())
    WITH CHECK (rls_can_access_project(project_id) AND created_by = rls_current_user_id());

CREATE POLICY series_analyses_remove ON series_analyses FOR DELETE
    USING (rls_can_access_project(project_id) AND created_by = rls_current_user_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON series_analyses TO platform_app;
