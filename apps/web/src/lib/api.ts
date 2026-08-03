/** Typed API client. Single origin (Next rewrites /api to the FastAPI
 * process in dev; CloudFront routes it in production). 401 anywhere sends
 * the user back to sign-in - the token is either absent or expired. */

import { clearSignedIn, loginHrefFor } from "./auth";
import type {
  BootstrapFirstOwnerInput, BootstrapFirstOwnerResult, BootstrapStatus,
  Me, Org, OrgUser, ProjectDetail, ProjectSummary, ResourceKindCounts, ResourceList, ResolvedResource,
  WorkspaceDetail, WorkspaceSummary,
} from "./types";

export class ApiError extends Error {
  /** The parsed error body, when there was one. Some refusals carry their
   * reasons as data alongside the message — an object-type edit blocked by
   * existing consumers lists them under `impacts` (db 0028) — and a caller
   * that wants to render a list rather than a sentence needs the original. */
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
  }
}

/** Sent on every call. The API refuses cookie authentication without it, so
 * that a request some other site caused - which cannot set headers - is not
 * authenticated by a cookie the browser attached automatically. */
const SESSION_HEADERS = { "X-Anchor-Session": "1" };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    credentials: "same-origin",
    headers: {
      ...(init?.headers ?? {}),
      ...SESSION_HEADERS,
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  if (res.status === 401) {
    clearSignedIn();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.assign(loginHrefFor(window.location.pathname, window.location.search));
    }
    throw new ApiError(401, "Signed out");
  }
  if (!res.ok) {
    let detail = res.statusText;
    let body: unknown;
    try {
      body = await res.json();
      const parsed = body as { detail?: string };
      if (typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      /* non-JSON error body - keep statusText */
    }
    throw new ApiError(res.status, detail, body);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** A multipart POST. Deliberately not `request`: the browser has to set the
 * multipart boundary itself, so this path must *not* send a Content-Type. */
async function requestForm<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    credentials: "same-origin",
    headers: SESSION_HEADERS,
    body: form,
  });
  if (!res.ok) {
    let detail = res.statusText;
    let body: unknown;
    try {
      body = await res.json();
      const parsed = body as { detail?: string };
      if (typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail, body);
  }
  return (await res.json()) as T;
}

export const api = {
  me: () => request<Me>("/auth/me"),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  org: () => request<Org>("/org"),
  orgMembers: () => request<OrgUser[]>("/org/members"),
  orgGroups: () => request<import("./types").Group[]>("/org/groups"),
  workspaces: () => request<WorkspaceSummary[]>("/workspaces"),
  workspace: (id: string) => request<WorkspaceDetail>(`/workspaces/${id}`),
  projects: (workspaceId: string) =>
    request<ProjectSummary[]>(`/workspaces/${workspaceId}/projects`),
  project: (workspaceId: string, projectId: string) =>
    request<ProjectDetail>(`/workspaces/${workspaceId}/projects/${projectId}`),
};

/** Repositories (db 0033). Read-only from the browser for now: editing
 * arrives with the editor in roadmap 2.2. */
export const repositories = {
  list: (wid: string, pid: string) =>
    request<import("./types").Repository[]>(
      `/workspaces/${wid}/projects/${pid}/repositories`,
    ),
  get: (wid: string, pid: string, rid: string) =>
    request<import("./types").Repository>(
      `/workspaces/${wid}/projects/${pid}/repositories/${rid}`,
    ),
  branches: (wid: string, pid: string, rid: string) =>
    request<import("./types").RepositoryBranch[]>(
      `/workspaces/${wid}/projects/${pid}/repositories/${rid}/branches`,
    ),
  tree: (wid: string, pid: string, rid: string, ref: { branch?: string; commitId?: string }) => {
    const q = new URLSearchParams();
    if (ref.commitId) q.set("commit_id", ref.commitId);
    else if (ref.branch) q.set("branch", ref.branch);
    const qs = q.toString();
    return request<import("./types").RepositoryTree>(
      `/workspaces/${wid}/projects/${pid}/repositories/${rid}/tree${qs ? `?${qs}` : ""}`,
    );
  },
  commits: (wid: string, pid: string, rid: string, branch?: string) =>
    request<import("./types").RepositoryCommit[]>(
      `/workspaces/${wid}/projects/${pid}/repositories/${rid}/commits` +
        (branch ? `?branch=${encodeURIComponent(branch)}` : ""),
    ),
  commit: (
    wid: string,
    pid: string,
    rid: string,
    input: { branch: string; files: Record<string, string>; message: string },
  ) =>
    request<import("./types").RepositoryCommit>(
      `/workspaces/${wid}/projects/${pid}/repositories/${rid}/commits`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  diff: (wid: string, pid: string, rid: string, toCommitId: string) =>
    request<import("./types").RepositoryDiff>(
      `/workspaces/${wid}/projects/${pid}/repositories/${rid}/diff?to_commit_id=${toCommitId}`,
    ),
  /** Run one file's transform against a sample of its inputs, writing nothing.
   * `content` is the editor's buffer, so this answers "does what I just typed
   * work" rather than "did what I committed work". */
  preview: (
    wid: string,
    pid: string,
    rid: string,
    input: { path: string; content?: string; branch?: string },
  ) =>
    request<import("./types").TransformPreview>(
      `/workspaces/${wid}/projects/${pid}/repositories/${rid}/preview`,
      { method: "POST", body: JSON.stringify(input) },
    ),
};

/** The resource registry (db 0032). `resolve` takes an id and nothing else -
 * that is the point of the id, so a link survives a rename or a move. */
export const resources = {
  list: (
    workspaceId: string,
    projectId: string,
    params: {
      kind?: string[];
      search?: string;
      sort?: string;
      direction?: "asc" | "desc";
      limit?: number;
      offset?: number;
      includeWorkspaceLevel?: boolean;
    } = {},
  ) => {
    const q = new URLSearchParams();
    // Repeated `kind` params rather than a comma-joined string: FastAPI reads
    // a list that way, and a name containing a comma would otherwise be a bug
    // waiting for the first customer who has one.
    for (const k of params.kind ?? []) q.append("kind", k);
    if (params.search) q.set("search", params.search);
    if (params.sort) q.set("sort", params.sort);
    if (params.direction) q.set("direction", params.direction);
    if (params.limit != null) q.set("limit", String(params.limit));
    if (params.offset != null) q.set("offset", String(params.offset));
    if (params.includeWorkspaceLevel) q.set("include_workspace_level", "true");
    const qs = q.toString();
    return request<ResourceList>(
      `/workspaces/${workspaceId}/projects/${projectId}/resources${qs ? `?${qs}` : ""}`,
    );
  },
  counts: (workspaceId: string, projectId: string) =>
    request<{ counts: ResourceKindCounts }>(
      `/workspaces/${workspaceId}/projects/${projectId}/resources/counts`,
    ),
  resolve: (resourceId: string) => request<ResolvedResource>(`/resources/${resourceId}`),
};

// Unauthenticated on purpose (services/orgs.bootstrap_first_owner): there is
// no user yet to hold a token when a fresh deployment needs its first
// organisation. request() only ever *attaches* a token if one exists in
// sessionStorage - it never requires one - so these calls work signed out.
export const bootstrap = {
  status: () => request<BootstrapStatus>("/bootstrap/status"),
  firstOwner: (input: BootstrapFirstOwnerInput) =>
    request<BootstrapFirstOwnerResult>("/bootstrap/first-owner", {
      method: "POST",
      body: JSON.stringify(input),
    }),
};

export interface WorkspaceCreateInput {
  name: string;
  description?: string;
}

export interface ProjectCreateInput {
  name: string;
  description?: string;
}

export interface InviteInput {
  email: string;
  display_name: string;
  org_role: "admin" | "member";
}

export const mutations = {
  createWorkspace: (input: WorkspaceCreateInput) =>
    request<import("./types").WorkspaceDetail>("/workspaces", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  createProject: (workspaceId: string, input: ProjectCreateInput) =>
    request<import("./types").ProjectSummary>(`/workspaces/${workspaceId}/projects`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  inviteUser: (input: InviteInput) =>
    request<import("./types").OrgUser>("/org/members", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  setUserRole: (userId: string, org_role: "admin" | "member") =>
    request<import("./types").OrgUser>(`/org/members/${userId}`, {
      method: "PATCH",
      body: JSON.stringify({ org_role }),
    }),
  disableUser: (userId: string) =>
    request<void>(`/org/members/${userId}`, { method: "DELETE" }),
};

export const connections = {
  sourceTypes: (wid: string, pid: string) =>
    request<import("./types").SourceTypeInfo[]>(
      `/workspaces/${wid}/projects/${pid}/connections/source-types`,
    ),
  list: (wid: string, pid: string) =>
    request<import("./types").Connection[]>(`/workspaces/${wid}/projects/${pid}/connections`),
  create: (
    wid: string,
    pid: string,
    input: {
      name: string;
      source_type: string;
      scope?: "project" | "workspace";
      config: Record<string, unknown>;
      secret?: Record<string, string>;
    },
  ) =>
    request<import("./types").Connection>(`/workspaces/${wid}/projects/${pid}/connections`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  test: (wid: string, pid: string, cid: string) =>
    request<import("./types").ConnectionTestResult>(
      `/workspaces/${wid}/projects/${pid}/connections/${cid}/test`,
      { method: "POST", body: JSON.stringify({}) },
    ),
  discover: (wid: string, pid: string, cid: string) =>
    request<import("./types").DiscoveredTable[]>(
      `/workspaces/${wid}/projects/${pid}/connections/${cid}/discover`,
      { method: "POST", body: JSON.stringify({}) },
    ),
  remove: (wid: string, pid: string, cid: string) =>
    request<void>(`/workspaces/${wid}/projects/${pid}/connections/${cid}`, { method: "DELETE" }),
};

export const datasets = {
  list: (wid: string, pid: string) =>
    request<import("./types").Dataset[]>(`/workspaces/${wid}/projects/${pid}/datasets`),
  get: (wid: string, pid: string, did: string) =>
    request<import("./types").Dataset>(`/workspaces/${wid}/projects/${pid}/datasets/${did}`),
  versions: (wid: string, pid: string, did: string) =>
    request<import("./types").DatasetVersion[]>(
      `/workspaces/${wid}/projects/${pid}/datasets/${did}/versions`,
    ),
  upload: (wid: string, pid: string, input: { name: string; file: File }) => {
    const form = new FormData();
    form.set("name", input.name);
    form.set("file", input.file);
    return requestForm<import("./types").Dataset>(
      `/workspaces/${wid}/projects/${pid}/datasets/upload`, form,
    );
  },
  update: (
    wid: string,
    pid: string,
    did: string,
    input: {
      name?: string;
      description?: string;
      schema_policy?: "permissive" | "strict";
    },
  ) =>
    request<import("./types").Dataset>(
      `/workspaces/${wid}/projects/${pid}/datasets/${did}`,
      { method: "PATCH", body: JSON.stringify(input) },
    ),
  fork: (
    wid: string,
    pid: string,
    did: string,
    input: { name: string; version_number?: number },
  ) =>
    request<import("./types").Dataset>(
      `/workspaces/${wid}/projects/${pid}/datasets/${did}/fork`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  preview: (wid: string, pid: string, did: string) =>
    request<import("./types").TabularResult>(
      `/workspaces/${wid}/projects/${pid}/datasets/${did}/preview`,
    ),
  profile: (wid: string, pid: string, did: string) =>
    request<import("./types").DatasetProfile>(
      `/workspaces/${wid}/projects/${pid}/datasets/${did}/profile`,
    ),
  health: (wid: string, pid: string, did: string) =>
    request<import("./types").DatasetHealth>(
      `/workspaces/${wid}/projects/${pid}/datasets/${did}/health`,
    ),
  expectations: (wid: string, pid: string, did: string) =>
    request<import("./types").Expectation[]>(
      `/workspaces/${wid}/projects/${pid}/datasets/${did}/expectations`,
    ),
  addExpectation: (
    wid: string,
    pid: string,
    did: string,
    input: {
      rule_type: string;
      column_name: string;
      config?: Record<string, unknown>;
      severity?: string;
    },
  ) =>
    request<import("./types").Expectation>(
      `/workspaces/${wid}/projects/${pid}/datasets/${did}/expectations`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  removeExpectation: (wid: string, pid: string, did: string, rid: string) =>
    request<void>(
      `/workspaces/${wid}/projects/${pid}/datasets/${did}/expectations/${rid}`,
      { method: "DELETE" },
    ),
  query: (wid: string, pid: string, did: string, sql: string) =>
    request<import("./types").TabularResult>(
      `/workspaces/${wid}/projects/${pid}/datasets/${did}/query`,
      { method: "POST", body: JSON.stringify({ sql }) },
    ),
  exportUrl: (wid: string, pid: string, did: string, format: "parquet" | "csv") =>
    `/api/workspaces/${wid}/projects/${pid}/datasets/${did}/export?format=${format}`,
  remove: (wid: string, pid: string, did: string) =>
    request<void>(`/workspaces/${wid}/projects/${pid}/datasets/${did}`, { method: "DELETE" }),
};

/** Authenticated file download. The session cookie now rides along on a plain
 * <a href>, but the CSRF header does not - and the API refuses cookie
 * authentication without it - so this still fetches the bytes and hands them to
 * the browser as an object URL. */
export async function downloadFile(url: string, filename: string): Promise<void> {
  const res = await fetch(url, {
    credentials: "same-origin",
    headers: SESSION_HEADERS,
  });
  if (!res.ok) throw new ApiError(res.status, "download failed");
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

export const sync = {
  trigger: (
    wid: string,
    pid: string,
    cid: string,
    input: { source_schema?: string; source_table: string; dataset_name?: string },
  ) =>
    request<import("./types").SyncResult>(
      `/workspaces/${wid}/projects/${pid}/connections/${cid}/sync`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  runs: (wid: string, pid: string, cid: string) =>
    request<import("./types").SyncRun[]>(
      `/workspaces/${wid}/projects/${pid}/connections/${cid}/sync-runs`,
    ),
  // One request for the whole list page rather than per-connection health.
  health: (wid: string, pid: string) =>
    request<import("./types").SyncHealth[]>(
      `/workspaces/${wid}/projects/${pid}/connections/sync-health`,
    ),
};

export const scheduledSync = {
  get: (wid: string, pid: string, cid: string) =>
    request<import("./types").ScheduledSync>(
      `/workspaces/${wid}/projects/${pid}/connections/${cid}/scheduled-sync`,
    ),
  set: (
    wid: string,
    pid: string,
    cid: string,
    input: {
      mode: "full" | "incremental";
      source_schema?: string;
      source_table: string;
      dataset_name?: string;
      primary_key_column?: string;
      cursor_column?: string;
      cron_schedule?: string;
    },
  ) =>
    request<import("./types").ScheduledSync>(
      `/workspaces/${wid}/projects/${pid}/connections/${cid}/scheduled-sync`,
      { method: "PUT", body: JSON.stringify(input) },
    ),
  clear: (wid: string, pid: string, cid: string) =>
    request<import("./types").ScheduledSync>(
      `/workspaces/${wid}/projects/${pid}/connections/${cid}/scheduled-sync`,
      { method: "DELETE" },
    ),
  run: (wid: string, pid: string, cid: string) =>
    request<import("./types").SyncResult>(
      `/workspaces/${wid}/projects/${pid}/connections/${cid}/scheduled-sync/run`,
      { method: "POST", body: JSON.stringify({}) },
    ),
};

export const models = {
  list: (wid: string, pid: string) =>
    request<import("./types").Model[]>(`/workspaces/${wid}/projects/${pid}/models`),
  create: (
    wid: string,
    pid: string,
    input: {
      name: string;
      description?: string;
      language?: "sql" | "python";
      code: string;
      inputs: { dataset_id: string; input_alias: string }[];
    },
  ) =>
    request<import("./types").Model>(`/workspaces/${wid}/projects/${pid}/models`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  update: (
    wid: string,
    pid: string,
    mid: string,
    input: {
      name?: string;
      code?: string;
      inputs?: { dataset_id: string; input_alias: string }[];
      trigger_mode?: "manual" | "cron" | "upstream";
      cron_schedule?: string | null;
      input_health_policy?: "ignore" | "warn" | "block";
    },
  ) =>
    request<import("./types").Model>(`/workspaces/${wid}/projects/${pid}/models/${mid}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),
  run: (wid: string, pid: string, mid: string) =>
    request<import("./types").ModelRunResult>(
      `/workspaces/${wid}/projects/${pid}/models/${mid}/run`,
      { method: "POST", body: JSON.stringify({}) },
    ),
  runs: (wid: string, pid: string, mid: string) =>
    request<import("./types").ModelRun[]>(
      `/workspaces/${wid}/projects/${pid}/models/${mid}/runs`,
    ),
  remove: (wid: string, pid: string, mid: string) =>
    request<void>(`/workspaces/${wid}/projects/${pid}/models/${mid}`, { method: "DELETE" }),
  versions: (wid: string, pid: string, mid: string) =>
    request<import("./types").ModelVersion[]>(
      `/workspaces/${wid}/projects/${pid}/models/${mid}/versions`,
    ),
  restoreVersion: (wid: string, pid: string, mid: string, versionNumber: number) =>
    request<import("./types").Model>(
      `/workspaces/${wid}/projects/${pid}/models/${mid}/versions/${versionNumber}/restore`,
      { method: "POST", body: JSON.stringify({}) },
    ),
  /** The whole project as one graph — datasets and models together, already
   *  laid out by the API (see apps/api/src/services/pipeline.py). */
  pipeline: (wid: string, pid: string, focus?: string) =>
    request<import("./types").PipelineGraph>(
      `/workspaces/${wid}/projects/${pid}/pipeline` +
        (focus ? `?focus=${encodeURIComponent(focus)}` : ""),
    ),
};

export interface PropertyInput {
  api_name: string;
  display_name?: string;
  data_type: import("./types").PropertyDataType;
  required?: boolean;
  description?: string;
}

export interface ObjectTypeCreateInput {
  api_name: string;
  display_name: string;
  description?: string;
  icon?: string;
  colour?: string;
  properties?: PropertyInput[];
  title_property?: string | null;
}

/** The whole definition, not a patch — `api_name` is immutable, so it is
 * absent rather than optional. */
export interface ObjectTypeUpdateInput {
  display_name: string;
  description?: string;
  icon?: string;
  colour?: string;
  properties: PropertyInput[];
  title_property?: string | null;
  /** Required to push through a change that breaks an existing consumer. */
  acknowledge_breaking?: boolean;
}

export interface LinkTypeCreateInput {
  api_name: string;
  display_name: string;
  from_type_id: string;
  to_type_id: string;
  cardinality: import("./types").LinkCardinality;
  /** Both or neither; "$primary_key" for the instance key. Omit for an
   * ontology-only link type that is not traversable yet. */
  from_property?: string | null;
  to_property?: string | null;
}

export interface SourceCreateInput {
  object_type_id: string;
  dataset_id: string;
  primary_key_column: string;
  column_mappings: Record<string, string>;
}

export const objects = {
  /** Evaluate an object-set *definition* into instances (roadmap 1.2).
   *
   * The definition comes from a resolved `object_set` variable, so a filter
   * list, a table and a count all read the same set rather than each filtering
   * its own copy. `total` is the size of the whole set, not of this page -
   * which is the answer a page of rows cannot give. */
  evaluateObjectSet: (
    wid: string,
    definition: unknown,
    opts: { limit?: number; offset?: number } = {},
  ) =>
    request<{
      instances: import("./types").ObjectInstance[];
      total: number;
      limit: number;
      offset: number;
    }>(`/workspaces/${wid}/object-sets/evaluate`, {
      method: "POST",
      body: JSON.stringify({ definition, ...opts }),
    }),
  /** One number over a whole set — what a Metric Card shows. Separate from
   * `evaluateObjectSet` because a number over every row and a page of rows are
   * different questions with different costs. */
  aggregateObjectSet: (
    wid: string,
    definition: unknown,
    opts: { aggregation?: string; property?: string } = {},
  ) =>
    request<{ value: number; aggregation: string; property: string | null }>(
      `/workspaces/${wid}/object-sets/aggregate`,
      { method: "POST", body: JSON.stringify({ definition, ...opts }) },
    ),
  /** Workspace-wide instance search across every object type at once. */
  explore: (
    wid: string,
    input: {
      q?: string;
      typeIds?: string[];
      /** Exact match on one property — a different question from `q`, which
       * is substring/prefix across every property at once. Needs exactly one
       * typeId, since a property name only means something within a type. */
      property?: string;
      value?: string;
      limit?: number;
      offset?: number;
    },
  ) => {
    const search = new URLSearchParams();
    if (input.q) search.set("q", input.q);
    for (const t of input.typeIds ?? []) search.append("type_id", t);
    if (input.property && input.value !== undefined) {
      search.set("property", input.property);
      search.set("value", input.value);
    }
    if (input.limit) search.set("limit", String(input.limit));
    if (input.offset) search.set("offset", String(input.offset));
    const qs = search.toString();
    return request<import("./types").ExplorerPage>(
      `/workspaces/${wid}/object-instances${qs ? `?${qs}` : ""}`,
    );
  },
  listTypes: (wid: string) =>
    request<import("./types").ObjectTypeSummary[]>(`/workspaces/${wid}/object-types`),
  getType: (wid: string, typeId: string) =>
    request<import("./types").ObjectTypeDetail>(`/workspaces/${wid}/object-types/${typeId}`),
  createType: (wid: string, input: ObjectTypeCreateInput) =>
    request<import("./types").ObjectTypeDetail>(`/workspaces/${wid}/object-types`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  updateType: (wid: string, typeId: string, input: ObjectTypeUpdateInput) =>
    request<import("./types").ObjectTypeDetail>(`/workspaces/${wid}/object-types/${typeId}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),
  /** Dry-run an edit: which mappings, actions and link joins it would break. */
  typeImpact: (wid: string, typeId: string, input: ObjectTypeUpdateInput) =>
    request<import("./types").ObjectTypeImpact[]>(
      `/workspaces/${wid}/object-types/${typeId}/impact`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  listTypeVersions: (wid: string, typeId: string) =>
    request<import("./types").ObjectTypeVersion[]>(
      `/workspaces/${wid}/object-types/${typeId}/versions`,
    ),
  restoreTypeVersion: (
    wid: string, typeId: string, versionNumber: number, acknowledgeBreaking = false,
  ) =>
    request<import("./types").ObjectTypeDetail>(
      `/workspaces/${wid}/object-types/${typeId}/versions/${versionNumber}/restore`,
      { method: "POST", body: JSON.stringify({ acknowledge_breaking: acknowledgeBreaking }) },
    ),
  removeType: (wid: string, typeId: string) =>
    request<void>(`/workspaces/${wid}/object-types/${typeId}`, { method: "DELETE" }),
  listLinkTypes: (wid: string) =>
    request<import("./types").LinkType[]>(`/workspaces/${wid}/link-types`),
  createLinkType: (wid: string, input: LinkTypeCreateInput) =>
    request<import("./types").LinkType>(`/workspaces/${wid}/link-types`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  setLinkJoin: (
    wid: string,
    linkId: string,
    join: { from_property: string | null; to_property: string | null },
  ) =>
    request<import("./types").LinkType>(`/workspaces/${wid}/link-types/${linkId}`, {
      method: "PATCH",
      body: JSON.stringify(join),
    }),
  removeLinkType: (wid: string, linkId: string) =>
    request<void>(`/workspaces/${wid}/link-types/${linkId}`, { method: "DELETE" }),
  listSources: (wid: string, pid: string) =>
    request<import("./types").ObjectTypeSource[]>(
      `/workspaces/${wid}/projects/${pid}/object-type-sources`,
    ),
  createSource: (wid: string, pid: string, input: SourceCreateInput) =>
    request<import("./types").ObjectTypeSource>(
      `/workspaces/${wid}/projects/${pid}/object-type-sources`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  removeSource: (wid: string, pid: string, sourceId: string) =>
    request<void>(`/workspaces/${wid}/projects/${pid}/object-type-sources/${sourceId}`, {
      method: "DELETE",
    }),
  suggest: (wid: string, pid: string, datasetId: string) =>
    request<import("./types").ObjectTypeSuggestion>(
      `/workspaces/${wid}/projects/${pid}/object-type-sources/suggest`,
      { method: "POST", body: JSON.stringify({ dataset_id: datasetId }) },
    ),
  syncSource: (wid: string, pid: string, sourceId: string) =>
    request<import("./types").SourceSyncResult>(
      `/workspaces/${wid}/projects/${pid}/object-type-sources/${sourceId}/sync`,
      { method: "POST", body: JSON.stringify({}) },
    ),
  getSourceSchedule: (wid: string, pid: string, sourceId: string) =>
    request<import("./types").ObjectSourceSchedule>(
      `/workspaces/${wid}/projects/${pid}/object-type-sources/${sourceId}/schedule`,
    ),
  setSourceSchedule: (wid: string, pid: string, sourceId: string, cronSchedule: string) =>
    request<import("./types").ObjectSourceSchedule>(
      `/workspaces/${wid}/projects/${pid}/object-type-sources/${sourceId}/schedule`,
      { method: "PUT", body: JSON.stringify({ cron_schedule: cronSchedule }) },
    ),
  clearSourceSchedule: (wid: string, pid: string, sourceId: string) =>
    request<import("./types").ObjectSourceSchedule>(
      `/workspaces/${wid}/projects/${pid}/object-type-sources/${sourceId}/schedule`,
      { method: "DELETE" },
    ),
  listInstances: (wid: string, typeId: string, limit = 50, offset = 0) =>
    request<import("./types").ObjectInstancePage>(
      `/workspaces/${wid}/object-types/${typeId}/instances?limit=${limit}&offset=${offset}`,
    ),
  getInstance: (wid: string, typeId: string, instanceId: string) =>
    request<import("./types").ObjectInstance>(
      `/workspaces/${wid}/object-types/${typeId}/instances/${instanceId}`,
    ),
  uploadAttachment: async (wid: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    // No Content-Type header: the browser must set the multipart boundary.
    return requestForm<import("./types").AttachmentRef>(
      `/workspaces/${wid}/attachments`, form,
    );
  },
  attachmentUrl: (wid: string, key: string) =>
    `/api/workspaces/${wid}/attachments/download?key=${encodeURIComponent(key)}`,
  instanceLinks: (wid: string, typeId: string, instanceId: string) =>
    request<import("./types").LinkedInstances[]>(
      `/workspaces/${wid}/object-types/${typeId}/instances/${instanceId}/links`,
    ),
};

export interface ActionTypeCreateInput {
  object_type_id: string;
  api_name: string;
  display_name: string;
  description?: string;
  editable_properties: string[];
}

export const actions = {
  listTypes: (wid: string, objectTypeId?: string) =>
    request<import("./types").ActionType[]>(
      `/workspaces/${wid}/action-types${objectTypeId ? `?object_type_id=${objectTypeId}` : ""}`,
    ),
  createType: (wid: string, input: ActionTypeCreateInput) =>
    request<import("./types").ActionType>(`/workspaces/${wid}/action-types`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  removeType: (wid: string, actionTypeId: string) =>
    request<void>(`/workspaces/${wid}/action-types/${actionTypeId}`, { method: "DELETE" }),
  execute: (
    wid: string,
    pid: string,
    actionTypeId: string,
    instanceId: string,
    values: Record<string, unknown>,
  ) =>
    request<import("./types").ActionExecuteResult>(
      `/workspaces/${wid}/projects/${pid}/actions/${actionTypeId}/execute`,
      { method: "POST", body: JSON.stringify({ instance_id: instanceId, values }) },
    ),
};

export const canvas = {
  list: (wid: string, pid: string) =>
    request<import("./types").CanvasApp[]>(`/workspaces/${wid}/projects/${pid}/canvas-apps`),
  create: (wid: string, pid: string, input: { name: string; description?: string }) =>
    request<import("./types").CanvasAppDetail>(`/workspaces/${wid}/projects/${pid}/canvas-apps`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  get: (wid: string, pid: string, appId: string) =>
    request<import("./types").CanvasAppDetail>(
      `/workspaces/${wid}/projects/${pid}/canvas-apps/${appId}`,
    ),
  update: (wid: string, pid: string, appId: string, input: { name?: string; description?: string }) =>
    request<import("./types").CanvasAppDetail>(
      `/workspaces/${wid}/projects/${pid}/canvas-apps/${appId}`,
      { method: "PATCH", body: JSON.stringify(input) },
    ),
  remove: (wid: string, pid: string, appId: string) =>
    request<void>(`/workspaces/${wid}/projects/${pid}/canvas-apps/${appId}`, { method: "DELETE" }),
  saveDefinition: (
    wid: string,
    pid: string,
    appId: string,
    // A whole module document (decision 0002), not a bare node map. The API
    // refuses a v2 document whose bindings do not resolve, so a save that
    // dropped the variables would come back 422 rather than corrupt the app.
    definition: import("./types").WorkshopModule | Record<string, unknown>,
  ) =>
    request<import("./types").CanvasAppDetail>(
      `/workspaces/${wid}/projects/${pid}/canvas-apps/${appId}/definition`,
      { method: "PUT", body: JSON.stringify({ definition }) },
    ),
  /** Resolve every variable, computing derived ones server-side so the
   * transformation semantics have one implementation. */
  evaluateVariables: (
    wid: string,
    pid: string,
    appId: string,
    values: Record<string, unknown>,
  ) =>
    request<{ values: Record<string, unknown>; order: string[] }>(
      `/workspaces/${wid}/projects/${pid}/canvas-apps/${appId}/variables/evaluate`,
      { method: "POST", body: JSON.stringify({ values }) },
    ),
  /** The same resolve for a published app, which a workspace member may open
   * without being in its project. */
  evaluatePublishedVariables: (wid: string, appId: string, values: Record<string, unknown>) =>
    request<{ values: Record<string, unknown>; order: string[] }>(
      `/workspaces/${wid}/published-canvas-apps/${appId}/variables/evaluate`,
      { method: "POST", body: JSON.stringify({ values }) },
    ),
  listVersions: (wid: string, pid: string, appId: string) =>
    request<import("./types").CanvasAppVersion[]>(
      `/workspaces/${wid}/projects/${pid}/canvas-apps/${appId}/versions`,
    ),
  publish: (
    wid: string,
    pid: string,
    appId: string,
    input: { scope: import("./types").CanvasPublishScope; group_ids?: string[] },
  ) =>
    request<import("./types").CanvasAppDetail>(
      `/workspaces/${wid}/projects/${pid}/canvas-apps/${appId}/publish`,
      { method: "PUT", body: JSON.stringify(input) },
    ),
  listShares: (wid: string, pid: string, appId: string) =>
    request<import("./types").CanvasAppShare[]>(
      `/workspaces/${wid}/projects/${pid}/canvas-apps/${appId}/shares`,
    ),
  listPublished: (wid: string) =>
    request<import("./types").CanvasApp[]>(`/workspaces/${wid}/published-canvas-apps`),
  getPublished: (wid: string, appId: string) =>
    request<import("./types").CanvasAppDetail>(`/workspaces/${wid}/published-canvas-apps/${appId}`),
};

/** The Code pillar's repository surface (ROADMAP Code item 2). Reads render
 * `model_versions`; the one write is the change set, which saves several
 * transforms as a single edit through the same service the inline Models
 * editor calls. */
export const code = {
  tree: (wid: string, pid: string) =>
    request<import("./types").CodeFile[]>(
      `/workspaces/${wid}/projects/${pid}/code/tree`,
    ),
  file: (wid: string, pid: string, modelId: string, version?: number) =>
    request<import("./types").CodeFileDetail>(
      `/workspaces/${wid}/projects/${pid}/code/files/${modelId}` +
        (version ? `?version=${version}` : ""),
    ),
  diff: (wid: string, pid: string, modelId: string, from: number | null, to?: number) =>
    request<import("./types").CodeDiff>(
      `/workspaces/${wid}/projects/${pid}/code/files/${modelId}/diff?` +
        new URLSearchParams({
          ...(from ? { from_version: String(from) } : {}),
          ...(to ? { to_version: String(to) } : {}),
        }).toString(),
    ),
  history: (wid: string, pid: string) =>
    request<import("./types").CodeHistoryEntry[]>(
      `/workspaces/${wid}/projects/${pid}/code/history`,
    ),
  changeSet: (wid: string, pid: string, id: string) =>
    request<import("./types").CodeChangeSet>(
      `/workspaces/${wid}/projects/${pid}/code/change-sets/${id}`,
    ),
  reviewPolicy: (wid: string, pid: string) =>
    request<{ require_code_review: boolean }>(
      `/workspaces/${wid}/projects/${pid}/code/review-policy`,
    ),
  setReviewPolicy: (wid: string, pid: string, required: boolean) =>
    request<{ require_code_review: boolean }>(
      `/workspaces/${wid}/projects/${pid}/code/review-policy`,
      { method: "PUT", body: JSON.stringify({ require_code_review: required }) },
    ),
  proposals: (wid: string, pid: string, state?: string) =>
    request<import("./types").CodeProposal[]>(
      `/workspaces/${wid}/projects/${pid}/code/proposals` + (state ? `?state=${state}` : ""),
    ),
  proposal: (wid: string, pid: string, id: string) =>
    request<import("./types").CodeProposalDetail>(
      `/workspaces/${wid}/projects/${pid}/code/proposals/${id}`,
    ),
  propose: (
    wid: string,
    pid: string,
    input: { summary: string; description?: string; changes: { model_id: string; code: string }[] },
  ) =>
    request<import("./types").CodeProposalDetail>(
      `/workspaces/${wid}/projects/${pid}/code/proposals`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  review: (
    wid: string,
    pid: string,
    id: string,
    input: { verdict: "approve" | "request_changes"; comment?: string },
  ) =>
    request<import("./types").CodeProposalDetail>(
      `/workspaces/${wid}/projects/${pid}/code/proposals/${id}/reviews`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  applyProposal: (wid: string, pid: string, id: string) =>
    request<import("./types").CodeProposalDetail>(
      `/workspaces/${wid}/projects/${pid}/code/proposals/${id}/apply`,
      { method: "POST" },
    ),
  withdrawProposal: (wid: string, pid: string, id: string) =>
    request<import("./types").CodeProposalDetail>(
      `/workspaces/${wid}/projects/${pid}/code/proposals/${id}/withdraw`,
      { method: "POST" },
    ),
  saveChangeSet: (
    wid: string,
    pid: string,
    input: {
      summary: string;
      description?: string;
      changes: { model_id: string; code?: string }[];
    },
  ) =>
    request<import("./types").CodeChangeSet>(
      `/workspaces/${wid}/projects/${pid}/code/change-sets`,
      { method: "POST", body: JSON.stringify(input) },
    ),
};
