-- §827: every foreign key to a resource has an index that leads with it.
--
-- Postgres indexes the referenced side of a foreign key and never the
-- referencing side. Forty-seven references were left without a usable one, and each
-- costs a scan of the whole referencing table twice over:
--
--   * **on delete** of the referenced row. Deleting a dataset sets
--     `models.output_dataset_id`, `sync_runs.dataset_id` and a dozen more to
--     NULL or cascades into them, and finds each row to change by reading the
--     table. Deleting an app, a model or an object type does the same.
--   * **on the reads that follow the reference backwards**, which is most of
--     what lineage is. The pipeline graph found the runs behind a project's
--     datasets through `sync_runs.dataset_id` and, with no index there,
--     Postgres checked the connections row policy on all 8,084 connections in
--     the database to keep 491: 665 ms on a copy of the development
--     database, 3.7 ms with the index. Its datasets statement scanned
--     `model_runs` for `output_version` once per dataset.
--
-- References to `users`, `workspaces` and `organisations` are left alone:
-- those rows are almost never deleted, every read of them goes the other
-- way, and `created_by` is on nearly every table. `tests/test_foreign_key_indexes.py`
-- refuses a new reference without an index, so the list stays empty.
--
-- **Partial where the column is mostly NULL** on tables that grow with use
-- (`action_runs`, `notifications`): a reference check asks `col = $1`, which
-- an `IS NOT NULL` index answers, and the NULLs cost nothing to insert. Any
-- other predicate does not: `resources.project_id` had only the Recent list's
-- index, `WHERE trashed_at IS NULL`, so deleting a project read every
-- tenant's resources to find its own.

CREATE INDEX idx_action_runs_dataset_id ON action_runs (dataset_id) WHERE dataset_id IS NOT NULL;
CREATE INDEX idx_action_runs_reverted_by_run_id ON action_runs (reverted_by_run_id) WHERE reverted_by_run_id IS NOT NULL;
CREATE INDEX idx_action_runs_reverts_run_id ON action_runs (reverts_run_id) WHERE reverts_run_id IS NOT NULL;
CREATE INDEX idx_action_types_log_link_type_id ON action_types (log_link_type_id);
CREATE INDEX idx_action_types_log_object_type_id ON action_types (log_object_type_id);
CREATE INDEX idx_canvas_app_shares_group_id ON canvas_app_shares (group_id);
CREATE INDEX idx_code_branches_head_commit_id ON code_branches (head_commit_id);
CREATE INDEX idx_code_proposal_checks_model_id ON code_proposal_checks (model_id);
CREATE INDEX idx_code_proposal_comments_model_id ON code_proposal_comments (model_id);
CREATE INDEX idx_code_proposal_file_marks_model_id ON code_proposal_file_marks (model_id);
CREATE INDEX idx_code_proposal_files_model_id ON code_proposal_files (model_id);
CREATE INDEX idx_code_proposals_change_set_id ON code_proposals (change_set_id);
CREATE INDEX idx_code_proposals_source_commit_id ON code_proposals (source_commit_id);
CREATE INDEX idx_connections_sync_dataset_id ON connections (sync_dataset_id);
CREATE INDEX idx_datasets_connection_id ON datasets (connection_id);
CREATE INDEX idx_favourites_object_type_id ON favourites (object_type_id);
CREATE INDEX idx_favourites_resource_id ON favourites (resource_id);
CREATE INDEX idx_kiosk_modules_app_id ON kiosk_modules (app_id);
CREATE INDEX idx_kiosk_sessions_app_id ON kiosk_sessions (app_id);
CREATE INDEX idx_kiosk_sessions_project_id ON kiosk_sessions (project_id);
CREATE INDEX idx_link_types_backing_from_link_id ON link_types (backing_from_link_id);
CREATE INDEX idx_link_types_backing_to_link_id ON link_types (backing_to_link_id);
CREATE INDEX idx_link_types_backing_type_id ON link_types (backing_type_id);
CREATE INDEX idx_link_types_from_object_type_id ON link_types (from_object_type_id);
CREATE INDEX idx_link_types_join_dataset_id ON link_types (join_dataset_id);
CREATE INDEX idx_link_types_to_object_type_id ON link_types (to_object_type_id);
CREATE INDEX idx_listener_events_endpoint_id ON listener_events (endpoint_id);
CREATE INDEX idx_listeners_archive_dataset_id ON listeners (archive_dataset_id);
CREATE INDEX idx_model_runs_model_version ON model_runs (model_version);
CREATE INDEX idx_model_runs_output_version ON model_runs (output_version);
CREATE INDEX idx_model_versions_source_commit_id ON model_versions (source_commit_id);
CREATE INDEX idx_models_output_dataset_id ON models (output_dataset_id);
CREATE INDEX idx_notifications_action_run_id ON notifications (action_run_id) WHERE action_run_id IS NOT NULL;
CREATE INDEX idx_oauth_states_connection_id ON oauth_states (connection_id);
CREATE INDEX idx_object_edits_action_run_id ON object_edits (action_run_id);
CREATE INDEX idx_object_type_group_members_group_id_workspace_id ON object_type_group_members (group_id, workspace_id);
CREATE INDEX idx_object_type_group_members_object_type_id_workspace_id ON object_type_group_members (object_type_id, workspace_id);
CREATE INDEX idx_object_type_series_dataset_id ON object_type_series (dataset_id);
CREATE INDEX idx_object_type_sources_dataset_id ON object_type_sources (dataset_id);
CREATE INDEX idx_object_type_views_canvas_app_id ON object_type_views (canvas_app_id);
CREATE INDEX idx_object_types_title_property_id ON object_types (title_property_id);
CREATE INDEX idx_object_view_tabs_canvas_app_id ON object_view_tabs (canvas_app_id);
CREATE INDEX idx_sync_runs_dataset_id ON sync_runs (dataset_id, started_at);
CREATE INDEX idx_listener_endpoints_listener_id ON listener_endpoints (listener_id);
CREATE INDEX idx_project_members_project_id ON project_members (project_id);
CREATE INDEX idx_promotion_requests_object_type_id ON promotion_requests (object_type_id);
CREATE INDEX idx_resources_project_id ON resources (project_id);
