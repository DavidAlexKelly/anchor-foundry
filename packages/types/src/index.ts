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

/** The resource registry (db migration 0032). One row per resource, whatever
 * kind it is - the list a project browser reads, and the thing a /r/{id} link
 * resolves against. */
export type ResourceKind =
  | "connection"
  | "dataset"
  | "model"
  | "object_type"
  | "canvas_app"
  | "code_repo";

export interface Resource {
  id: string;
  workspace_id: string;
  /** Null for resources that belong to the workspace rather than to a
   * project: object types, and workspace-scoped connections. */
  project_id: string | null;
  kind: ResourceKind;
  name: string;
  description: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ResourceList {
  resources: Resource[];
  total: number;
  limit: number;
  offset: number;
}

/** Every kind is present, including the ones with nothing in them, so a
 * caller never has to tell "none of these" from "no such kind". */
export type ResourceKindCounts = Record<ResourceKind, number>;

/** What `/resources/{id}` returns: the resource plus enough of where it lives
 * to draw a breadcrumb without a second round trip. A trashed resource
 * resolves and says so rather than 404ing - answering "no such thing" for
 * something that demonstrably existed sends whoever followed the link looking
 * for a typo. */
export interface ResolvedResource extends Resource {
  workspace_slug: string;
  workspace_name: string;
  project_slug: string | null;
  project_name: string | null;
  trashed: boolean;
  /** The row's id in its own table (`datasets.id`, `models.id`, …). The
   * resource id identifies *what* this is; every per-kind endpoint is keyed by
   * this one, so an application needs both. */
  kind_id: string;
}

// ---- Workshop module format (docs/decisions/0002-workshop-module-format.md)
/** A saved app is one document with three parts. `format: 2` is the marker; a
 * v1 document is a bare Craft.js node map with `ROOT` at the top level and no
 * wrapper at all. */
export interface WorkshopModule {
  format: 2;
  /** The Craft.js node tree, unchanged from v1 apart from reference props,
   * which now hold variable ids rather than parameter names. */
  layout: Record<string, unknown>;
  variables: Record<string, WorkshopVariable>;
  events: Record<string, WorkshopEvent>;
  /** References to a parameter nothing declares, found during conversion.
   * Recorded rather than repaired: the binding has silently read as "no
   * filter" for as long as it existed, and quietly tidying it away would
   * destroy the only evidence that the app is wrong. */
  broken_bindings?: { node: string; prop: string; parameter: string }[];
}

/** Reserved now, built in roadmap item 1.2. `object_set` is the one that
 * carries the weight and the one that needs server-side evaluation. */
export type WorkshopVariableKind =
  | "string"
  | "number"
  | "boolean"
  | "date"
  | "timestamp"
  | "array"
  | "single_object"
  | "object_set";

/** Foundry's transformation vocabulary, less the two that read the ontology
 * (`object_property`, `object_set_aggregation`) — those need the instance
 * store, so they are a server round trip rather than a pure function and the
 * API refuses them until they are built. */
export type WorkshopTransform =
  | "concat"
  | "if_else"
  | "cast"
  | "is_empty"
  | "is_not_empty"
  /** Narrow an object set by a value another variable holds — Foundry's Filter
   * List driving an Object Table, expressed as a derivation. Inputs are
   * `[set, valueVariable]`; config carries the property and the operator. */
  | "filter_set"
  /** Narrow an object set by a *list* of clauses a Filter List writes. Inputs
   * are `[set, clausesVariable]`, and there is no property or operator in the
   * config — which properties get narrowed is the viewer's choice, so it lives
   * in the value rather than the declaration. */
  | "narrow_set"
  /** One property of the object a viewer picked. Input is `[objectVariable]`;
   * config carries the property name. Pure, because a `single_object` variable
   * holds the object rather than a key to fetch (`STATUS.md` §84). */
  | "object_property";

export interface WorkshopDerivation {
  transform: WorkshopTransform;
  /** Variable ids this reads. Held apart from `config` so the dependency graph
   * does not depend on knowing each transform's shape — a new transform cannot
   * accidentally become invisible to cycle detection. */
  inputs: string[];
  config?: Record<string, unknown>;
}

/** One clause of an object set. The operator list is deliberately short: every
 * one means the same thing on Postgres and OpenSearch, and an operator that did
 * not would make an app's results depend on which store the deployment runs. */
export interface ObjectSetFilter {
  property: string;
  op: "eq" | "neq" | "in" | "starts_with";
  value: unknown;
}

export interface WorkshopVariable {
  /** Opaque and stable. Deliberately not derived from the label - a derived id
   * is a rename waiting to break every reference. */
  id: string;
  kind: WorkshopVariableKind;
  label: string;
  /** Where a plain variable starts, for every viewer. Values are never
   * persisted (decision 0002 §3): a saved app is not a saved session. */
  default?: unknown;
  /** Present on a derived variable. Its value is a function of its inputs, so
   * a value supplied for it by a viewer is ignored rather than honoured. */
  derivation?: WorkshopDerivation;
  /** `object_set` variables only: the set this one starts from, as a
   * *definition* (type plus filters) rather than rows — storing rows would make
   * a saved app a saved session. A variable has this **or** a derivation, never
   * both: two answers to "where do these rows come from" and no rule for which
   * wins, which the API refuses. */
  object_set?: { object_type_id: string; filters?: ObjectSetFilter[] };
  /** What this was called when it was a string-keyed parameter, so a converted
   * app can still be read against the v1 document it came from. */
  legacy_name?: string;
  /** A stable, author-chosen name — the one mechanism behind embedding, URL
   * initialisation and state saving (Foundry p.163, p.165, p.202). Deliberately
   * *not* `id`: an id is generated by the builder and means nothing to somebody
   * writing a URL by hand, and a saved state pointing at one would break the
   * first time an app was rebuilt.
   *
   * Constrained to `[A-Za-z][A-Za-z0-9_]*` by the API, because it appears as a
   * query parameter name and anything needing percent-encoding would break the
   * documented copy-paste recipe (p.165). */
  external_id?: string;
  /** Present when this variable is on the module interface — the module's
   * public API. Requires `external_id`: the interface is addressed by external
   * ID, so one without a name cannot be reached. */
  interface?: WorkshopInterface;
}

/** A variable's membership of the module interface (Foundry p.163).
 *
 * `display_name` and `description` are documentation for whoever is embedding
 * this module or writing a URL against it, not identity — renaming one breaks
 * nothing. `required` is ours rather than Foundry's, and exists because the
 * alternative to refusing an unmapped variable is an embedded module rendering
 * against a default nobody chose. */
export interface WorkshopInterface {
  display_name?: string;
  description?: string;
  required?: boolean;
}

/** Trigger to ordered effects. Effects run in configured order and do not wait
 * on downstream recomputation; setting a variable copies the value
 * immediately, so the next effect sees it. Built in item 1.3. */
export interface WorkshopEvent {
  id: string;
  trigger: { node: string; on: string };
  effects: WorkshopEffect[];
}

/** One step of an event. `config`'s shape depends on `type`, which is why it
 * is not narrowed here: the server (`services/workshop_events.py`) is what
 * refuses a config that does not match its type, and a second set of rules in
 * the type system would be a second thing to keep in step. */
export interface WorkshopEffect {
  type: string;
  config?: Record<string, unknown>;
}

// ---- repositories (docs/decisions/0003-repository-storage.md, db 0033) -----
export interface Repository {
  id: string;
  project_id: string;
  name: string;
  slug: string;
  description: string;
  default_branch: string;
  resource_id: string;
  created_at: string;
  updated_at: string;
}

export interface RepositoryBranch {
  id: string;
  name: string;
  /** Null on a branch created before its first commit, and on the default
   * branch of a repository nobody has committed to - which has no row at all,
   * since branches are created by the first commit. */
  head_commit_id: string | null;
}

export interface RepositoryCommit {
  id: string;
  parent_id: string | null;
  message: string;
  created_by: string | null;
  created_at: string;
}

/** One transform a publish would create or update (roadmap 2.5). */
export interface PublishStep {
  path: string;
  /** The dataset the file declares it produces; also the model's name. */
  output: string;
  language: string;
  model_id: string | null;
  model_name: string;
  /** Byte-identical to what is already live, so publishing writes nothing. */
  unchanged: boolean;
  renames: boolean;
  inputs: { dataset_id: string; input_alias: string; dataset: string }[];
  /** created / updated / unchanged. Absent from a plan, which has done nothing. */
  action?: "created" | "updated" | "unchanged" | null;
  version_number?: number | null;
}

/** A model this repository published from a file the commit no longer declares.
 * Reported, never deleted: a transform that has run holds a dataset other
 * things read, and removing a file is not the same act as deciding that
 * dataset should stop being produced. */
export interface PublishOrphan {
  id: string;
  name: string;
  source_path: string;
}

export interface PublishPlan {
  commit_id: string;
  steps: PublishStep[];
  orphaned: PublishOrphan[];
}

/** A whole snapshot: every file at a commit, path to content. A commit carries
 * a flat manifest rather than a tree, so this is one join. */
export interface RepositoryTree {
  commit_id: string | null;
  files: Record<string, string>;
}

export interface RepositoryDiff {
  added: string[];
  deleted: string[];
  modified: string[];
}

/** What merging `head` into `base` would do. Four states, and the name is the
 * answer to "can I merge this":
 *
 *   identical    - the branches point at the same commit.
 *   fast_forward - base's head is an ancestor of head's, so base can move.
 *   contained    - head's history is already inside base's; nothing to merge.
 *   diverged     - each has commits the other does not. Refused: merging here
 *                  is fast-forward only (docs/decisions/0003).
 */
export type MergeState = "identical" | "fast_forward" | "contained" | "diverged";

export interface RepositoryComparison {
  base: string;
  base_commit_id: string | null;
  head: string;
  head_commit_id: string | null;
  state: MergeState;
  /** Commits on `head` that `base` does not have, and the reverse. Both, not
   * just the one that would land: a refused merge is only actionable if you
   * can see what is on the other side too. */
  ahead_by: number;
  behind_by: number;
  /** The landing commits, newest first. Capped for the screen; `ahead_by` is
   * exact. */
  commits: RepositoryCommit[];
  /** Against `base`, not against the previous commit: what merging changes. */
  files: RepositoryDiff;
}

export interface RepositoryMerge extends RepositoryComparison {
  /** False for a merge that had nothing to do, which is not a failure. */
  merged: boolean;
}

/** One input as the preview actually read it. `sampled` is the difference
 * between a number that is the answer and a number that looks like one. */
export interface PreviewedInput {
  alias: string;
  dataset: string;
  dataset_id: string;
  rows_available: number;
  rows_used: number;
  sampled: boolean;
}

export interface TransformPreview {
  output: string;
  columns: { name: string; data_type: string }[];
  rows: unknown[][];
  /** Rows produced **from the sample**, not from the datasets. */
  row_count: number;
  truncated: boolean;
  sampled: boolean;
  inputs: PreviewedInput[];
  /** What this change would do to the dataset the transform already writes,
   * or null when it writes a new one or changes nothing. */
  schema_changes: {
    added?: { name: string; data_type: string }[];
    removed?: { name: string; data_type: string }[];
    retyped?: { name: string; from: string; to: string }[];
  } | null;
  writes_to_existing_dataset: boolean;
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

/** One committed version of a dataset. The row a "time travel" view browses,
 * and the reason a record of what a dataset *was* does not change when the
 * dataset does. */
/** What keeping every version of a dataset costs (roadmap 3.3). Time travel is
 * only possible because nothing deletes an old version, and that bill has
 * always been paid without being shown — see docs/decisions/0005. */
export interface DatasetRetention {
  versions: number;
  /** Summed over the versions whose object was found. `unmeasured` says how
   * many were not, so a total is never quietly short. */
  total_bytes: number;
  unmeasured: number;
  current_version: number;
}

export interface DatasetVersion {
  id: string;
  version_number: number;
  row_count: number;
  /** What this version costs to keep. Null means the object is not where the
   * row says it is — a different state from "this version is small". */
  size_bytes?: number | null;
  table_schema: { name: string; data_type: string }[];
  /** What produced it: an upload, a sync, a model run. Null for versions
   * written before this was recorded. */
  produced_by_kind: string | null;
  created_at: string;
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

/** The explorer's own parameters, and nothing else (db 0040). A saved search
 *  holds a question, never its answer - "vessels flagged NO" reads differently
 *  tomorrow, and storing the rows would turn it into a stale report. */
export interface SavedSearchDefinition {
  q: string | null;
  type_ids: string[];
  property: string | null;
  value: string | null;
}

export interface SavedSearch {
  id: string;
  workspace_id: string;
  name: string;
  description: string;
  definition: SavedSearchDefinition;
  /** Resolved for display, so the list does not read as a wall of uuids. */
  type_names: string[];
  /** Type ids the workspace no longer has. The search still opens - that
   *  filter simply matches nothing - and naming them beats both refusing to
   *  open it and pretending it still asks what it used to. */
  missing_types: string[];
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

// ---- objects (ontology) -----------------------------------------------------
/** How prominently applications should show a property (Foundry
 * `object-link-types` p.111). **A display hint, never a permission**: a hidden
 * property is still stored and still returned by the API — access control is
 * RLS, and it is somewhere else. */
export type PropertyVisibility = "normal" | "prominent" | "hidden";

export type PropertyDataType =
  | "string" | "integer" | "float" | "boolean" | "date" | "timestamp" | "geopoint"
  | "json" | "attachment"
  /** A **series id**, not a history (decision 0009, db 0047). The value on the
   * instance is a small scalar — usually its own primary key — and
   * `object_type_series` on the object type source says which dataset, key,
   * timestamp and value columns hold the points behind it. */
  | "time_series";

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
  /** Defaults to "normal" on a property saved before visibility existed. */
  visibility: PropertyVisibility;
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
  /** api_names an application should not draw (Foundry `object-link-types`
   * p.111). Only the hidden ones — a list endpoint should not carry every
   * property of every type to answer "which columns do I skip". */
  hidden_properties: string[];
  /** Where this type opens as an application (`/r/{id}`, item 4.2). */
  resource_id: string;
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
/**
 * Which Workshop module stands in for an object type's standard view
 * (`object-views` p.2–4, db 0046).
 *
 * A pointer, not a document: the view *is* the module. `subject_variable` is
 * the whole binding — the `single_object` variable that receives the object
 * being looked at.
 */
/**
 * One thing the ontology search found, and **which field found it**
 * (`ontology-manager` p.28).
 *
 * `matched_field` comes from the server because the matcher is the only thing
 * that knows it. A browser deriving it again would be a second matcher, free
 * to disagree with the one that put the row in the list — and the
 * disagreement would look like a highlight landing on the wrong word.
 */
export interface OntologySearchHit {
  kind: "object_type" | "property" | "link_type" | "action_type";
  id: string;
  api_name: string;
  display_name: string;
  /** Where it lives. A property called "status" is not somewhere anybody can
   * navigate to; "status on Ticket" is. */
  object_type_id: string;
  object_type_name: string;
  matched_field: string;
  matched_value: string;
}

export interface ObjectView {
  id: string;
  object_type_id: string;
  canvas_app_id: string;
  canvas_app_name: string;
  /** `full` (p.3, comprehensive) or `panel` (p.4, for embedding). */
  form_factor: string;
  subject_variable: string;
  created_at: string;
  updated_at: string;
}

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
  /** What the side being traversed *to* is called (Foundry
   * `object-link-types` p.192), already resolved against the link's own
   * display name. */
  side_name: string;
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
/** An input the action declares (Foundry `action-types` p.25). */
export interface ActionParameter {
  id: string;
  api_name: string;
  display_name: string;
  data_type: string;
  required: boolean;
  /** `null` means no default, which is not the same as a default of null - see
   * migration 0044. */
  default_value: unknown;
  /** p.25: "each parameter can be individually configured as to whether they
   * are exposed in the form or not". A hidden parameter is still applied. */
  hidden: boolean;
  sort_order: number;
}

/** What the action does with them (p.75). */
export interface ActionRule {
  id: string;
  kind: string;
  config: Record<string, unknown>;
  sort_order: number;
}

/** A condition that must hold for the action to be submitted (p.49-56). */
export interface ActionCriterion {
  id: string;
  /** p.56's failure message: what the blocked user is told. */
  message: string;
  config: Record<string, unknown>;
  sort_order: number;
}

export interface ActionType {
  id: string;
  object_type_id: string;
  object_type_name: string;
  api_name: string;
  display_name: string;
  description: string;
  parameters: ActionParameter[];
  rules: ActionRule[];
  criteria: ActionCriterion[];
  /** Derived from the rules rather than stored (migration 0044). Still on the
   * wire because the object-type screens and the `run_action` editor ask
   * "which properties does this action write", and that question has this
   * exact answer while `modify_object` is the only rule kind. */
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
  /** The version viewers of a published app see. Null when nothing has been
   * published; saving never changes it, so "published v3, editing v7" is a
   * state the builder can and does show. */
  published_version: number | null;
  /** Versions-dialog settings (Foundry p.192). Both default to false, which is
   * the behaviour that existed before they did: saving does not publish, and
   * nothing prompts. */
  auto_publish_on_save: boolean;
  prompt_for_description: boolean;
  /** Where this app opens as an application (`/r/{id}`). */
  resource_id: string;
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
  /** The editor's name, which is what the Versions dialog shows (Foundry
   * p.191). Null when the account that made it has since been deleted — the
   * version outlives the account. */
  created_by_name: string | null;
  created_at: string;
  /** Optional note on what changed. Editable after the fact (p.192). */
  description: string;
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

/** One line of a side-by-side diff, carrying both sides' line numbers.
 *
 *   same    - present on both sides, unchanged
 *   added   - only on the proposed side
 *   removed - only on the live side
 *   changed - a replacement, so both sides have text and they differ
 */
export interface CodeDiffRow {
  kind: "same" | "added" | "removed" | "changed";
  live_line: number | null;
  live_text: string | null;
  proposed_line: number | null;
  proposed_text: string | null;
}

export interface CodeProposalComment {
  id: string;
  /** One of these two, never both. A commit-backed proposal may create
   * transforms that do not exist yet, and a remark about one of those has only
   * its repository path to hang on (db 0039). */
  model_id: string | null;
  source_path?: string | null;
  /** Which column of the diff it hangs on. */
  side: "live" | "proposed";
  /** Null is a remark about the file rather than about a line. */
  line: number | null;
  body: string;
  author_id: string | null;
  author_email: string | null;
  created_at: string;
  /** The proposal's `files_updated_at` this was said about: a version, not a
   * moment. */
  anchored_at: string;
  /** The proposal has been edited since, so the line this points at is not the
   * line it was written about. Shown and marked, never hidden. */
  outdated: boolean;
  resolved_at: string | null;
  resolved_by: string | null;
}

/** "I have read this file", per reviewer. Only marks against the *current*
 * files are returned - one made before the last edit says somebody read a file
 * that no longer exists in that form. */
export interface CodeFileMark {
  model_id: string | null;
  source_path?: string | null;
  reviewer_id: string;
  reviewer_email: string | null;
  marked_at: string;
}

/** A check result (db 0037).
 *
 *   pass  - it ran and found nothing
 *   warn  - it found something a reviewer should see, which does not block
 *   fail  - it found something that would break, which blocks applying
 *   error - it could not run. Not a pass: nobody has been told anything about
 *           the code.
 */
export type CodeCheckStatus = "pass" | "warn" | "fail" | "error";

export interface CodeCheck {
  id: string;
  /** Null on both is a check about the proposal as a whole. `source_path`
   * carries the file when it has no model yet (db 0039). */
  model_id: string | null;
  source_path?: string | null;
  name: string;
  status: CodeCheckStatus;
  summary: string;
  detail: Record<string, unknown>;
  ran_at: string;
  ran_by: string | null;
  ran_by_email: string | null;
  anchored_at: string;
  /** The proposal moved after this ran, so it describes code nobody will
   * apply. Shown, marked, and not counted as a gate. */
  stale: boolean;
}

export interface CodeProposalFile {
  /** Null for a file that would *create* a transform: a commit-backed proposal
   * publishes files that may have no model until it is applied. */
  model_id: string | null;
  model_name: string;
  language: "sql" | "python";
  path: string | null;
  code: string;
  /** The version this was written against; applying re-checks it. */
  base_version: number;
  current_version: number;
  diff: string;
  /** The same comparison as `diff`, aligned into rows with line numbers. */
  rows: CodeDiffRow[];
  comments: CodeProposalComment[];
  read_by: CodeFileMark[];
  checks: CodeCheck[];
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
  /** Set when this proposal asks to publish a repository commit rather than to
   * change named transforms (db 0039). Its files are derived from the commit,
   * and applying it publishes. */
  source_repo_id?: string | null;
  source_commit_id?: string | null;
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
  /** The whole conversation in one list, for a timeline rather than the
   * per-file view. Same rows as `files[].comments`, not a second store. */
  comments: CodeProposalComment[];
  /** Every check result, stale ones included: a check that went stale is
   * information, and hiding it reads as "no checks have run". */
  checks: CodeCheck[];
  /** Every reason this cannot be applied, in the words the API used. */
  blockers: string[];
}
