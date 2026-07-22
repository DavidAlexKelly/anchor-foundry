/** Shared API contract types.
 *
 * These mirror the Pydantic response models in apps/api/src/routes — the API
 * is the source of truth; when a route model changes, change this file in the
 * same commit. Field names are the wire names (snake_case) on purpose: no
 * mapping layer to drift.
 */

export type OrgRole = "owner" | "admin" | "member";
export type WorkspaceRole = "admin" | "editor" | "viewer";
export type ProjectRole = "owner" | "editor" | "viewer" | "none";
export type PermissionMode = "inherited" | "custom";

export interface Me {
  user_id: string;
  organisation_id: string;
  email: string;
  display_name: string;
  org_role: OrgRole;
}

export interface WorkspaceSummary {
  id: string;
  name: string;
  slug: string;
  description: string;
  effective_role: WorkspaceRole;
  project_count: number;
  created_at: string;
}

export interface WorkspaceDetail {
  id: string;
  name: string;
  slug: string;
  description: string;
  effective_role: WorkspaceRole;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceMember {
  id: string;
  role: WorkspaceRole;
  user_id: string | null;
  email: string | null;
  display_name: string | null;
  group_id: string | null;
  group_name: string | null;
  created_at: string;
}

export interface ProjectSummary {
  id: string;
  name: string;
  slug: string;
  description: string;
  permission_mode: PermissionMode;
  effective_role: Exclude<ProjectRole, "none">;
  created_at: string;
  updated_at: string;
}

export interface ResourceCounts {
  connections: number;
  datasets: number;
  models: number;
  objects: number;
  canvas: number;
  code: number;
}

export interface ProjectDetail extends ProjectSummary {
  resource_counts: ResourceCounts;
}

export interface ProjectMember {
  id: string;
  role: ProjectRole;
  user_id: string | null;
  email: string | null;
  display_name: string | null;
  group_id: string | null;
  group_name: string | null;
  created_at: string;
}

export interface OrgUser {
  id: string;
  email: string;
  display_name: string;
  org_role: OrgRole;
  status: string;
  identity_linked: boolean | null;
  created_at: string;
}

export interface Org {
  id: string;
  name: string;
  slug: string;
  plan: string;
  aws_region: string | null;
  stack_status: string;
  created_at: string;
}

export interface Group {
  id: string;
  name: string;
  description: string;
  member_count: number | null;
  created_at: string;
}

export interface AuditEntry {
  id: number;
  action: string;
  resource_type: string;
  resource_id: string | null;
  workspace_id: string | null;
  project_id: string | null;
  metadata: Record<string, unknown>;
  actor_email: string | null;
  actor_name: string | null;
  created_at: string;
}

// ---- connections (Layer 1) --------------------------------------------------
export type ConnectionScope = "project" | "workspace";
export type ConnectionStatus = "unconfigured" | "ok" | "error" | "testing";
export type SyncMode = "federated" | "full" | "incremental";

export interface Connection {
  id: string;
  workspace_id: string;
  project_id: string | null;
  scope: ConnectionScope;
  name: string;
  source_type: string;
  config: Record<string, unknown>;
  sync_mode: SyncMode;
  status: ConnectionStatus;
  last_tested_at: string | null;
  last_synced_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface SourceTypeInfo {
  type: string;
  display_name: string;
  config_schema: {
    properties: Record<string, { type?: string; default?: unknown; title?: string }>;
    required?: string[];
  };
  secret_fields: string[];
}

export interface ConnectionTestResult {
  ok: boolean;
  error: string | null;
  connection: Connection;
}

export interface DiscoveredColumn {
  name: string;
  data_type: string;
  nullable: boolean;
  is_primary_key: boolean;
}

export interface DiscoveredTable {
  schema_name: string;
  name: string;
  kind: "table" | "view";
  columns: DiscoveredColumn[];
}

// ---- datasets (Layer 1.5) ---------------------------------------------------
export type DatasetOrigin = "upload" | "sync" | "model_output";

export interface Dataset {
  id: string;
  project_id: string;
  workspace_id: string;
  name: string;
  slug: string;
  description: string;
  origin: DatasetOrigin;
  connection_id: string | null;
  table_schema: { name: string; data_type: string }[];
  row_count: number;
  current_version: number;
  created_at: string;
  updated_at: string;
}

export interface TabularResult {
  columns: { name: string; data_type: string }[];
  rows: unknown[][];
  total_rows: number;
  truncated: boolean;
}

// ---- connection sync --------------------------------------------------------
export interface SyncResult {
  run_id: string;
  ok: boolean;
  error: string | null;
  rows_synced: number;
  created_dataset: boolean;
  dataset: {
    id: string;
    name: string;
    slug: string;
    row_count: number;
    current_version: number;
  } | null;
}

export interface SyncRun {
  id: string;
  mode: SyncMode;
  source_table: string;
  status: "running" | "succeeded" | "failed";
  rows_synced: number;
  error: string | null;
  started_at: string;
  finished_at: string | null;
  dataset_id: string | null;
  dataset_name: string | null;
}

// ---- models -----------------------------------------------------------------
export interface ModelInput {
  dataset_id: string;
  input_alias: string;
  dataset_name: string;
}

export interface Model {
  id: string;
  project_id: string;
  name: string;
  description: string;
  language: "sql" | "python";
  code: string;
  output_dataset_id: string | null;
  trigger_mode: "manual" | "cron" | "upstream";
  last_run_status: string | null;
  last_run_at: string | null;
  inputs: ModelInput[];
  created_at: string;
  updated_at: string;
}

export interface ModelRun {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  trigger_kind: string;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  rows_produced: number | null;
  error_message: string | null;
  output_version: string | null;
}

export interface ModelRunResult {
  run_id: string;
  ok: boolean;
  error: string | null;
  rows_produced: number;
  output_dataset: { id: string; name: string; slug: string; current_version: number } | null;
}

// ---- objects (ontology) -----------------------------------------------------
export type PropertyDataType =
  | "string" | "integer" | "float" | "boolean" | "date" | "timestamp" | "geopoint" | "json";
export type LinkCardinality = "one_to_one" | "one_to_many" | "many_to_many";
export type SourceSyncStatus = "never_synced" | "syncing" | "ok" | "error";

export interface ObjectTypeProperty {
  id: string;
  api_name: string;
  display_name: string;
  data_type: PropertyDataType;
  required: boolean;
  description: string;
  sort_order: number;
}

export interface ObjectTypeSummary {
  id: string;
  api_name: string;
  display_name: string;
  description: string;
  icon: string;
  colour: string;
  title_property_id: string | null;
  source_count: number;
  created_at: string;
  updated_at: string;
}

export interface ObjectTypeDetail {
  id: string;
  api_name: string;
  display_name: string;
  description: string;
  icon: string;
  colour: string;
  title_property_id: string | null;
  properties: ObjectTypeProperty[];
  created_at: string;
  updated_at: string;
}

export interface LinkType {
  id: string;
  api_name: string;
  display_name: string;
  cardinality: LinkCardinality;
  from_object_type_id: string;
  from_display_name: string;
  to_object_type_id: string;
  to_display_name: string;
  created_at: string;
}

export interface ObjectTypeSource {
  id: string;
  object_type_id: string;
  object_type_name: string;
  dataset_id: string;
  dataset_name: string;
  primary_key_column: string;
  column_mappings: Record<string, string>;
  sync_status: SourceSyncStatus;
  last_synced_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface SuggestedProperty {
  api_name: string;
  display_name: string;
  data_type: PropertyDataType;
  required: boolean;
  source_column: string;
}

export interface ObjectTypeSuggestion {
  dataset_name: string;
  suggested_api_name: string;
  suggested_display_name: string;
  suggested_primary_key: string | null;
  suggested_title_property: string | null;
  properties: SuggestedProperty[];
}

export interface SourceSyncResult {
  ok: boolean;
  error: string | null;
  upserted: number;
  removed: number;
  source: ObjectTypeSource;
}

export interface ObjectInstance {
  id: string;
  primary_key: string;
  properties: Record<string, unknown>;
  updated_at: string;
}

export interface ObjectInstancePage {
  items: ObjectInstance[];
  total: number;
  limit: number;
  offset: number;
}

// ---- actions (write-back) ----------------------------------------------------
export interface ActionType {
  id: string;
  object_type_id: string;
  object_type_name: string;
  api_name: string;
  display_name: string;
  description: string;
  editable_properties: string[];
  created_at: string;
  updated_at: string;
}

export interface ActionRun {
  id: string;
  instance_id: string | null;
  dataset_id: string | null;
  dataset_version: number | null;
  submitted_values: Record<string, unknown>;
  status: "running" | "succeeded" | "failed";
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface ActionExecuteResult {
  ok: boolean;
  error: string | null;
  dataset_version: number | null;
  instance: ObjectInstance;
}
