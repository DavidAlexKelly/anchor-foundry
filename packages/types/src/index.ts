/** Shared API contract types.
 *
 * These mirror the Pydantic response models in apps/api/src/routes - the API
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

export interface Group {
  id: string;
  name: string;
  description: string;
  member_count: number | null;
  created_at: string;
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

// ---- first-owner bootstrap (unauthenticated, one-time only) ----------------
export interface BootstrapStatus {
  needs_setup: boolean;
}

export interface BootstrapFirstOwnerInput {
  organisation_name: string;
  organisation_slug: string;
  owner_email: string;
  owner_display_name: string;
}

export interface BootstrapFirstOwnerResult {
  organisation_id: string;
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
    // `enum` is present for constrained choices (a connector's TLS mode, say),
    // which the wizard renders as a picker rather than a free-text box;
    // `type` is JSON Schema's, so "boolean" and "integer" both occur and each
    // needs its own input.
    properties: Record<
      string,
      { type?: string; default?: unknown; title?: string; enum?: string[] }
    >;
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
  /** For object storage this is the folder under the connection's configured
   * prefix, empty for a file at the root - not a database schema. */
  schema_name: string;
  name: string;
  kind: "table" | "view" | "file" | "endpoint";
  columns: DiscoveredColumn[];
}

// ---- datasets (Layer 1.5) ---------------------------------------------------
export type DatasetOrigin = "upload" | "sync" | "model_output" | "fork";

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
  /** Whether a new version may remove or retype an existing column
   *  (migration 0023). Adding columns is allowed under both. */
  schema_policy: "permissive" | "strict";
  /** Where a forked dataset came from (migration 0025). Provenance only —
   *  a fork never recomputes, so it is not a pipeline-graph edge, and the
   *  id is a historical record that survives the source being deleted. */
  forked_from_dataset_id: string | null;
  forked_from_version: number | null;
  created_at: string;
  updated_at: string;
}

/** Per-column statistics for a dataset version (migration 0019). Computed on
 * first request and cached - a version's data is immutable. min/max are text
 * because one array holds every column's type; null for types with no
 * meaningful ordering (lists, structs). */
export interface ColumnProfile {
  name: string;
  data_type: string;
  null_count: number;
  null_rate: number;
  distinct_count: number;
  min: string | null;
  max: string | null;
}

export interface DatasetProfile {
  dataset_id: string;
  version_number: number;
  row_count: number;
  columns: ColumnProfile[];
}

// ---- data health (roadmap Datasets item 2, migration 0020) ------------------
export type ExpectationRuleType =
  | "not_null"
  | "unique"
  | "value_in_range"
  | "regex_match"
  | "column_exists";

export interface Expectation {
  id: string;
  dataset_id: string;
  rule_type: ExpectationRuleType;
  column_name: string;
  config: Record<string, unknown>;
  severity: "error" | "warn";
  created_at: string;
}

export interface ExpectationResult {
  expectation_id: string | null;
  rule_type: ExpectationRuleType;
  column_name: string;
  severity: "error" | "warn";
  /** `error` means the rule could not be evaluated - which is not the same as
   * the data being bad, and must not be shown as though it were. */
  status: "pass" | "fail" | "error";
  failing_rows: number;
  rows_checked: number;
  message: string | null;
}

export interface DatasetHealth {
  dataset_id: string;
  version_number: number;
  /** "none" when the dataset has no rules - distinct from passing. */
  status: "pass" | "warn" | "fail" | "none";
  evaluated_at: string | null;
  results: ExpectationResult[];
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

/** Schema drift between a synced dataset version and the one it replaced
 * (migration 0018). Only the non-empty keys are present, so the object itself
 * is truthy exactly when something changed. */
export interface SchemaChanges {
  added?: { name: string; data_type: string }[];
  removed?: { name: string; data_type: string }[];
  retyped?: { name: string; from: string; to: string }[];
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
  schema_changes: SchemaChanges | null;
}

/** Per-connection sync health for the connections list. Rates are over the
 * most recent runs, not all time. */
export interface SyncHealth {
  connection_id: string;
  sync_schedule: string | null;
  next_run_at: string | null;
  total_runs: number;
  succeeded: number;
  failed: number;
  /** Runs neither succeeded nor failed - in flight, or orphaned by a restart.
   * Excluded from success_rate rather than counted against it. */
  running: number;
  drifted: number;
  success_rate: number | null;
  last_status: "running" | "succeeded" | "failed" | null;
  last_started_at: string | null;
  last_finished_at: string | null;
  last_duration_seconds: number | null;
  last_rows_synced: number | null;
  last_error: string | null;
  last_schema_changes: SchemaChanges | null;
}

// A connection carries at most one managed scheduled/incremental sync
// target (migration 0014) - not several independently scheduled tables.
export interface ScheduledSync {
  id: string;
  sync_mode: SyncMode;
  sync_schedule: string | null;
  sync_source_schema: string | null;
  sync_source_table: string | null;
  sync_dataset_name: string | null;
  sync_dataset_id: string | null;
  sync_primary_key_column: string | null;
  sync_cursor_column: string | null;
  sync_last_cursor_value: string | null;
  sync_next_run_at: string | null;
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
  cron_schedule: string | null;
  next_run_at: string | null;
  /** Newest input dataset version an upstream-triggered model has reacted to. */
  upstream_watermark: string | null;
  /** What a run does when an input dataset's health is 'fail' (migration 0022). */
  input_health_policy: "ignore" | "warn" | "block";
  last_run_status: string | null;
  last_run_at: string | null;
  inputs: ModelInput[];
  created_at: string;
  updated_at: string;
}

/** One node in a project's pipeline graph. Dataset-only and model-only
 *  fields are both nullable rather than split into a union, so the view can
 *  map over `nodes` without narrowing on every access. */
export interface PipelineNode {
  id: string;                 // "dataset:<uuid>" | "model:<uuid>"
  kind: "dataset" | "model";
  resource_id: string;
  name: string;
  /** Distance downstream; every edge points from a lower layer to a higher one. */
  layer: number;
  /** Index within the layer, name-ordered and stable across requests. */
  position: number;
  in_cycle: boolean;
  /** True on the node a lineage view was centred on; always false for the
   *  whole-project graph. */
  is_focus: boolean;
  slug: string | null;
  origin: string | null;
  row_count: number | null;
  current_version: number | null;
  health_status: string | null;
  language: string | null;
  trigger_mode: string | null;
  last_run_status: string | null;
  last_run_at: string | null;
  updated_at: string | null;
}

export interface PipelineEdge {
  from: string;
  to: string;
  /** The model's input alias, on dataset → model edges only. */
  label: string | null;
}

export interface PipelineGraph {
  nodes: PipelineNode[];
  edges: PipelineEdge[];
  /** Node ids grouped per cycle; empty when the graph is a clean DAG. */
  cycles: string[][];
  layer_count: number;
}

/** Per-input dataset health as a gated run saw it, captured at run time. */
export interface RunInputHealth {
  dataset_id: string;
  name: string;
  version: number;
  status: string;
  failing: string[];
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
  /** Null when the run was not gated (the model's policy was 'ignore'). */
  input_health: RunInputHealth[] | null;
  /** The definition this run executed (migration 0024). Null for runs that
   *  predate it — unknown, not v1. */
  model_version: string | null;
}

/** One entry in a model's definition history. Append-only: restoring an
 *  earlier version writes a new one rather than rewinding. */
export interface ModelVersion {
  id: string;
  model_id: string;
  version_number: number;
  code: string;
  inputs: { dataset_id: string; input_alias: string }[];
  /** Set when this version was created by restoring an earlier one. */
  restored_from: number | null;
  created_by_email: string | null;
  created_at: string;
}

export interface ModelRunResult {
  run_id: string;
  status: "queued" | "succeeded" | "failed";
  ok: boolean;
  error: string | null;
  rows_produced: number;
  output_dataset: { id: string; name: string; slug: string; current_version: number } | null;
}

/** One row of the workspace-wide Object Explorer: an instance plus the type
 *  it belongs to, since a cross-type result set is meaningless without
 *  saying what each row is. */
export interface ExplorerInstance {
  id: string;
  primary_key: string;
  properties: Record<string, unknown>;
  updated_at: string;
  object_type_id: string;
  object_type_api_name: string;
  object_type_display_name: string;
}

export interface ExplorerPage {
  items: ExplorerInstance[];
  total: number;
  limit: number;
  offset: number;
}

// ---- objects (ontology) -----------------------------------------------------
export type PropertyDataType =
  | "string" | "integer" | "float" | "boolean" | "date" | "timestamp" | "geopoint"
  | "json" | "attachment";

/** A geopoint property's stored value (db 0029). Always lat,lon - see
 * property_values.py for why that order and not GeoJSON's lon,lat. */
export interface GeoPoint {
  lat: number;
  lon: number;
}

/** An attachment property's stored value: a reference into the storage
 * gateway, exchanged for bytes by the download route, which checks the
 * caller's access first. Never a URL - see migration 0029. */
export interface AttachmentRef {
  key: string;
  filename: string;
  content_type: string;
  size: number;
}
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

/**
 * One consumer a proposed object-type change would disturb (db 0028).
 * `blocking` changes are refused unless explicitly acknowledged; the rest are
 * advisory (a retyped link join still traverses, since the join compares the
 * text form of both values).
 */
export interface ObjectTypeImpact {
  property: string;
  change: "removed" | "retyped";
  consumer_kind: "dataset_mapping" | "action" | "link";
  consumer_id: string;
  consumer_name: string;
  detail: string;
  blocking: boolean;
}

/** An append-only snapshot of an object type's definition (db 0028). */
export interface ObjectTypeVersion {
  id: string;
  version_number: number;
  display_name: string;
  description: string;
  icon: string;
  colour: string;
  /** The properties as declared at the time — a snapshot, not live rows. */
  properties: {
    api_name: string;
    display_name: string;
    data_type: PropertyDataType;
    required: boolean;
    description: string;
    sort_order: number;
  }[];
  /** The title property's api_name; property ids do not survive an edit. */
  title_property: string | null;
  /** Set when this version was created by restoring an earlier one. */
  restored_from: number | null;
  created_at: string;
  created_by_email: string | null;
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
  /**
   * The properties whose values are compared to derive instance-level links
   * (db 0027). Null as a pair when the link type is defined but not
   * traversable. `"$primary_key"` refers to the instance's primary key
   * rather than one of its properties.
   */
  from_property: string | null;
  to_property: string | null;
}

/** Reserved join reference: the instance's primary key, not a property. */
export const PRIMARY_KEY_REF = "$primary_key";

/**
 * One link traversed from a single instance: which relationship, which way it
 * runs, and a first page of what is on the far side.
 */
export interface LinkedInstances {
  link_type_id: string;
  api_name: string;
  display_name: string;
  cardinality: LinkCardinality;
  /** "outbound" when the instance's type is the link's from end. */
  direction: "outbound" | "inbound";
  far_type_id: string;
  far_type_display_name: string;
  near_property: string;
  far_property: string;
  /** The value read off this instance and matched against far_property. */
  matched_value: unknown;
  total: number;
  items: ObjectInstance[];
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

export interface ObjectSourceSchedule {
  id: string;
  sync_schedule: string | null;
  sync_next_run_at: string | null;
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

// ---- canvas apps (low-code app builder) --------------------------------------
export type CanvasPublishScope = "private" | "workspace" | "groups";

export interface CanvasApp {
  id: string;
  project_id: string;
  name: string;
  slug: string;
  description: string;
  current_version: number;
  publish_scope: CanvasPublishScope;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

// The definition is a Craft.js node tree - opaque to everything except the
// canvas editor itself, so it's typed loosely here rather than modelled
// node-by-node.
export interface CanvasAppDetail extends CanvasApp {
  definition: Record<string, unknown>;
}

export interface CanvasAppVersion {
  id: string;
  version_number: number;
  created_by: string | null;
  created_at: string;
}

export interface CanvasAppShare {
  group_id: string;
  group_name: string;
}

// ---- code (ROADMAP Code item 2) ---------------------------------------------
// There is no repository object: `docs/decisions/0001-where-code-lives.md`
// decided the Code pillar renders `model_versions` rather than storing code a
// second time, so a "file" is a model and the "commit log" is its history.

export interface CodeFile {
  /** The model's id - a file *is* a transform here. */
  id: string;
  /** Derived from the name and language, stable between reads. */
  path: string;
  name: string;
  language: "sql" | "python";
  description: string;
  size_bytes: number;
  current_version: number | null;
  updated_at: string;
}

export interface CodeFileDetail extends CodeFile {
  code: string;
  version_number: number | null;
  inputs: { dataset_id: string; input_alias: string }[];
  created_by_email?: string | null;
  restored_from?: number | null;
  change_set_id?: string | null;
}

export interface CodeDiff {
  path: string;
  model_id: string;
  from_version: number | null;
  to_version: number | null;
  /** Unified diff text, computed on read and stored nowhere. */
  diff: string;
  added: number;
  removed: number;
}

/** One entry in the project's commit log. `kind` is "change_set" for a
 * grouped edit and "version" for a standalone save from the inline Models
 * editor - two kinds rather than one, because that is how the code actually
 * gets edited (migration 0030). */
export interface CodeHistoryEntry {
  kind: "change_set" | "version";
  id: string;
  summary: string;
  description: string;
  created_at: string;
  created_by_email: string | null;
  model_count: number;
  model_id?: string | null;
  version_number?: number | null;
  path?: string | null;
}

export interface CodeChangeSet {
  id: string;
  project_id: string;
  summary: string;
  description: string;
  created_at: string;
  created_by_email: string | null;
  models: {
    model_id: string;
    model_name: string;
    language: "sql" | "python";
    path: string | null;
    version_number: number;
    previous_version: number | null;
  }[];
}

// ---- code review (ROADMAP Code item 4) ---------------------------------------
// A proposal is a *request* for code to become a definition. Its files live on
// the proposal rather than in model_versions, which is what a run resolves
// against and must never hold code nobody approved.

export interface CodeProposalFile {
  model_id: string;
  model_name: string;
  language: "sql" | "python";
  path: string | null;
  code: string;
  /** The version this was written against; applying re-checks it. */
  base_version: number;
  current_version: number;
  diff: string;
}

export interface CodeReview {
  id: string;
  reviewer_id: string | null;
  reviewer_email: string | null;
  verdict: "approve" | "request_changes";
  comment: string;
  created_at: string;
}

export interface CodeProposal {
  id: string;
  project_id: string;
  summary: string;
  description: string;
  state: "open" | "applied" | "withdrawn";
  change_set_id: string | null;
  created_by: string | null;
  created_by_email: string | null;
  created_at: string;
  files_updated_at: string;
  closed_by?: string | null;
  closed_at?: string | null;
  file_count: number;
}

export interface CodeProposalDetail extends CodeProposal {
  files: CodeProposalFile[];
  reviews: CodeReview[];
  /** Every reason this cannot be applied, in the words the API used. */
  blockers: string[];
}
