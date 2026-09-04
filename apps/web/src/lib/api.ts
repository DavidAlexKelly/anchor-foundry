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
  /** Every user in the organisation, or — with `groupIds` — only those in the
   * named groups (p.478's group filter, §234).
   *
   * **A caller with a filter must not pass an empty array**: a repeated query
   * parameter has no empty form, so `[]` produces the same request as no filter
   * at all and answers with the whole directory. `user-select.shouldAsk` is
   * where that decision is made and tested. */
  orgMembers: (groupIds?: readonly string[]) =>
    request<OrgUser[]>(
      `/org/members${
        groupIds && groupIds.length > 0
          ? `?${groupIds.map((g) => `group_id=${encodeURIComponent(g)}`).join("&")}`
          : ""
      }`,
    ),
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
  createBranch: (
    wid: string,
    pid: string,
    rid: string,
    input: { name: string; from_branch?: string; from_commit_id?: string },
  ) =>
    request<import("./types").RepositoryBranch>(
      `/workspaces/${wid}/projects/${pid}/repositories/${rid}/branches`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  deleteBranch: (wid: string, pid: string, rid: string, name: string) =>
    request<void>(
      `/workspaces/${wid}/projects/${pid}/repositories/${rid}/branches/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    ),
  /** What merging `head` into `base` would do. Reads only - this is what the
   * screen shows *before* anybody presses merge. */
  compare: (wid: string, pid: string, rid: string, base: string, head: string) =>
    request<import("./types").RepositoryComparison>(
      `/workspaces/${wid}/projects/${pid}/repositories/${rid}/compare` +
        `?base=${encodeURIComponent(base)}&head=${encodeURIComponent(head)}`,
    ),
  merge: (wid: string, pid: string, rid: string, base: string, head: string) =>
    request<import("./types").RepositoryMerge>(
      `/workspaces/${wid}/projects/${pid}/repositories/${rid}/merge`,
      { method: "POST", body: JSON.stringify({ base, head }) },
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
  /** What publishing this commit would do. Reads only - this is what the
   * screen shows before anybody presses publish (roadmap 2.5). */
  publishPlan: (wid: string, pid: string, rid: string, ref: { branch?: string }) =>
    request<import("./types").PublishPlan>(
      `/workspaces/${wid}/projects/${pid}/repositories/${rid}/publish` +
        (ref.branch ? `?branch=${encodeURIComponent(ref.branch)}` : ""),
    ),
  publish: (wid: string, pid: string, rid: string, ref: { branch?: string }) =>
    request<import("./types").PublishPlan>(
      `/workspaces/${wid}/projects/${pid}/repositories/${rid}/publish`,
      { method: "POST", body: JSON.stringify(ref) },
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
  /** A sample of the rows. `version` reads an earlier one (roadmap 3.3);
   * omitted is the current one, which is what every caller meant before time
   * travel existed and still means. */
  preview: (wid: string, pid: string, did: string, version?: number) =>
    request<import("./types").TabularResult>(
      `/workspaces/${wid}/projects/${pid}/datasets/${did}/preview` +
        (version ? `?version=${version}` : ""),
    ),
  profile: (wid: string, pid: string, did: string, version?: number) =>
    request<import("./types").DatasetProfile>(
      `/workspaces/${wid}/projects/${pid}/datasets/${did}/profile` +
        (version ? `?version=${version}` : ""),
    ),
  /** What keeping every version of this dataset costs. Time travel is only
   * possible because nothing deletes one (docs/decisions/0005). */
  retention: (wid: string, pid: string, did: string) =>
    request<import("./types").DatasetRetention>(
      `/workspaces/${wid}/projects/${pid}/datasets/${did}/retention`,
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
  visibility?: import("./types").PropertyVisibility;
  /** How a reader should see the value (Foundry `object-link-types`
   * p.94–101). Null clears an existing formatter; omitted keeps nothing,
   * which is why the editor sends it explicitly on every save. */
  value_format?: import("./types").ValueFormat | null;
  /** Ordered conditional formatting rules (Foundry `object-link-types`
   * p.102–109). Null clears them; sent explicitly on every save for
   * `value_format`'s reason. */
  conditional_format?: import("./types").ConditionalRule[] | null;
  /** No dataset column, by design (Foundry `object-link-types` p.113). */
  edit_only?: boolean;
  /** Where a derived property's value comes from (`object-link-types` p.143).
   * Null clears it. */
  derivation?: import("./types").Derivation | null;
  /** The shared property this one inherits from (`object-link-types` p.187).
   * Null is p.188's Detach, which is why it is sent explicitly rather than
   * omitted — an absent field and a cleared one would be the same request. */
  shared_property_id?: string | null;
  /** The value type constraining this property (`object-link-types` p.227).
   * Null detaches it, so it is sent explicitly rather than omitted. */
  value_type_id?: string | null;
  /** Developmental state (`object-link-types` p.253). Defaults to
   * `experimental` (p.256) when a client says nothing. */
  status?: import("./types").OntologyStatus;
  deprecation?: import("./types").Deprecation | null;
}

export interface ValueTypeInput {
  api_name?: string;
  display_name: string;
  description?: string;
  example_value?: string;
  base_type?: import("./types").PropertyDataType;
  constraint?: import("./types").ValueConstraint | null;
}

/** One row of where a value type is used. p.227 names two attachment points,
 * and they are different enough that a row has to say which it is. */
export interface ValueTypeUsage {
  kind: "object_type_property" | "shared_property";
  owner_name: string;
  property_api_name: string;
  object_type_id: string | null;
}

export interface SharedPropertyInput {
  api_name?: string;
  display_name: string;
  description?: string;
  data_type: import("./types").PropertyDataType;
  visibility?: import("./types").PropertyVisibility;
  value_format?: import("./types").ValueFormat | null;
}

/** Creating or renaming a group (`object-link-types` p.261).
 *
 * `api_name` only on create: it is the stable machine name, and it is what
 * p.262's search matches on, so a rename would move a group out from under a
 * saved query with nothing to say so. */
export interface ObjectTypeGroupInput {
  api_name?: string;
  display_name: string;
  description?: string;
}

/** One row of p.191's Usage. The property's own api_name is here because
 * p.188 lets it differ from the shared property's. */
export interface SharedPropertyUsage {
  object_type_id: string;
  object_type_api_name: string;
  object_type_display_name: string;
  property_api_name: string;
}

/** What a saved search is saved *as*. Deliberately the same four parameters
 * `objects.explore` takes: a saved search is the explorer's own state, so a
 * shape of its own here would be a second place for the two to disagree. */
export interface SavedSearchInput {
  q?: string | null;
  type_ids?: string[];
  property?: string | null;
  value?: string | null;
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
  /** p.253's status. **Omitted means unchanged**, not `experimental` — this
   * is a whole-definition save, and a client that says nothing must not
   * silently demote a type somebody promoted. */
  status?: import("./types").OntologyStatus;
  deprecation?: import("./types").Deprecation | null;
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
    // `sort` is a string or a list of them - p.223's "one or more default
    // sorts". The string is not legacy: it is what one ordering should still
    // send, and what every stored module holds.
    opts: { limit?: number; offset?: number; sort?: string | string[] } = {},
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
    // **`value` is nullable as of §226**: an aggregation over an empty set
    // answers nothing rather than zero, because "total capacity: 0" and "there
    // are no sites" are different facts. The type said `number` for two units
    // after that stopped being true, which is a lie a compiler will repeat.
    request<{ value: number | null; aggregation: string; property: string | null }>(
      `/workspaces/${wid}/object-sets/aggregate`,
      { method: "POST", body: JSON.stringify({ definition, ...opts }) },
    ),
  /** One number per distinct value of a property — what a chart over a set
   * plots.
   *
   * p.310's Aggregation per bucket as of §227: a count, or one of the four
   * numeric ones over a second property. `metric` is `null` for a count, and
   * never `null` within a metric answer — the server drops the buckets with
   * nothing to measure, so a slice always has something to be sized by. */
  groupObjectSet: (
    wid: string,
    definition: unknown,
    property: string,
    opts: {
      limit?: number;
      aggregation?: string;
      aggregation_property?: string | null;
    } = {},
  ) =>
    request<{
      groups: { value: string; count: number; metric: number | null }[];
      distinct_total: number;
      truncated: boolean;
    }>(`/workspaces/${wid}/object-sets/group`, {
      method: "POST",
      body: JSON.stringify({ definition, property, ...opts }),
    }),
  /** Counts by two properties at once — what a Pivot Table shows.
   *
   * The axes are the same grouped counts `groupObjectSet` returns, so a row
   * total and a bar in a chart over that property are the same number. A row's
   * cells can therefore sum to *less* than its total: objects with no value
   * for the column property are in no cell, and columns past the limit are not
   * drawn. `total` is the whole set, so the widget can say what the grid does
   * not account for rather than leaving it to be noticed. */
  crossTabObjectSet: (
    wid: string,
    definition: unknown,
    rowProperty: string,
    columnProperty: string,
  ) =>
    request<{
      rows: { value: string; count: number }[];
      columns: { value: string; count: number }[];
      row_distinct_total: number;
      column_distinct_total: number;
      rows_truncated: boolean;
      columns_truncated: boolean;
      cells: number[][];
      total: number;
    }>(`/workspaces/${wid}/object-sets/cross-tab`, {
      method: "POST",
      body: JSON.stringify({
        definition,
        row_property: rowProperty,
        column_property: columnProperty,
      }),
    }),
  /** How many objects in a set last changed in each time bucket.
   *
   * `updated_at`, not a business date — the server's docstring says why, and
   * the widget says so on screen. Empty buckets are already filled and the
   * range is the data's own first and last, so a client plots the points as
   * given rather than deciding what the axis covers. */
  timeSeriesObjectSet: (wid: string, definition: unknown, interval?: string) =>
    request<{
      points: { start: string; count: number }[];
      interval: string;
      total: number;
    }>(`/workspaces/${wid}/object-sets/time-series`, {
      method: "POST",
      body: JSON.stringify({ definition, ...(interval ? { interval } : {}) }),
    }),
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
  /** Saved searches (item 4.1). The definition is validated server-side by the
   *  same function `explore` goes through, so a search that cannot run is
   *  refused here rather than the next time somebody opens it. */
  listSearches: (wid: string) =>
    request<import("./types").SavedSearch[]>(`/workspaces/${wid}/object-searches`),
  createSearch: (
    wid: string,
    input: { name: string; description?: string; definition: SavedSearchInput },
  ) =>
    request<import("./types").SavedSearch>(`/workspaces/${wid}/object-searches`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  updateSearch: (
    wid: string,
    searchId: string,
    input: { name?: string; description?: string; definition?: SavedSearchInput },
  ) =>
    request<import("./types").SavedSearch>(
      `/workspaces/${wid}/object-searches/${searchId}`,
      { method: "PATCH", body: JSON.stringify(input) },
    ),
  deleteSearch: (wid: string, searchId: string) =>
    request<void>(`/workspaces/${wid}/object-searches/${searchId}`, { method: "DELETE" }),
  /** p.262: the table of object types "supports displaying and filtering by
   * group". `groupId` is the filtering half — server-side, so narrowing to a
   * group of four does not make the client pay for every type in the
   * ontology. */
  listTypes: (wid: string, groupId?: string | null) =>
    request<import("./types").ObjectTypeSummary[]>(
      `/workspaces/${wid}/object-types` +
        (groupId ? `?group_id=${encodeURIComponent(groupId)}` : ""),
    ),
  /** p.258's Edit status button, over the types somebody ticked. All or
   * nothing: one refusal fails the request rather than leaving half of them
   * changed. */
  bulkTypeStatus: (
    wid: string,
    input: {
      object_type_ids: string[];
      status: import("./types").OntologyStatus;
      deprecation?: import("./types").Deprecation | null;
      /** p.258's "option to also apply the `active` status to all
       * properties" — an option, so it is asked for rather than assumed. */
      apply_to_properties?: boolean;
    },
  ) =>
    request<import("./types").ObjectTypeSummary[]>(
      `/workspaces/${wid}/object-types/bulk-status`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  /** p.258's bulk edit from the Properties page. The server caps these at the
   * object type's own status, so the answer is what was stored rather than
   * what was asked for. */
  bulkPropertyStatus: (
    wid: string,
    typeId: string,
    input: { api_names: string[]; status: import("./types").OntologyStatus },
  ) =>
    request<import("./types").ObjectTypeProperty[]>(
      `/workspaces/${wid}/object-types/${typeId}/property-statuses`,
      { method: "POST", body: JSON.stringify(input) },
    ),
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
  /** The configured Object View for a type, or null when it has none — which
   * is the ordinary answer, not an error (`object-views` p.2). */
  getView: (wid: string, typeId: string, formFactor = "full") =>
    request<import("./types").ObjectView | null>(
      `/workspaces/${wid}/object-types/${typeId}/view?form_factor=${formFactor}`,
    ),
  setView: (
    wid: string, typeId: string,
    input: { canvas_app_id: string; subject_variable: string; form_factor?: string },
  ) =>
    request<import("./types").ObjectView>(
      `/workspaces/${wid}/object-types/${typeId}/view`,
      { method: "PUT", body: JSON.stringify(input) },
    ),
  clearView: (wid: string, typeId: string, formFactor = "full") =>
    request<void>(
      `/workspaces/${wid}/object-types/${typeId}/view?form_factor=${formFactor}`,
      { method: "DELETE" },
    ),
  /** The points behind one object's `time_series` property (decision 0009).
   * Workspace-scoped, like every other read of an instance: the ontology is
   * shared across a workspace, and these points are the value of a property
   * already visible at that floor. The series id is the instance's own and is
   * not a parameter. */
  seriesPoints: (
    wid: string, typeId: string, instanceId: string, property: string,
    opts: { interval?: string; aggregate?: string } = {},
  ) =>
    request<import("./types").SeriesPoints>(
      `/workspaces/${wid}/object-types/${typeId}/instances/${instanceId}` +
        `/series/${encodeURIComponent(property)}/points` +
        `?interval=${opts.interval ?? "none"}&aggregate=${opts.aggregate ?? "avg"}`,
    ),
  /** One search across object types, properties, link types and action types
   * (`ontology-manager` p.28). Each hit says which field matched. */
  searchOntology: (wid: string, q: string) =>
    request<import("./types").OntologySearchHit[]>(
      `/workspaces/${wid}/ontology-search?q=${encodeURIComponent(q)}`,
    ),
  /** Value types (`object-link-types` p.222–234). */
  listValueTypes: (wid: string) =>
    request<import("./types").ValueType[]>(`/workspaces/${wid}/value-types`),
  createValueType: (wid: string, input: ValueTypeInput) =>
    request<import("./types").ValueType>(`/workspaces/${wid}/value-types`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  /** p.229's mutable half. A constraint change is `addValueTypeVersion`. */
  updateValueType: (wid: string, id: string, input: ValueTypeInput) =>
    request<import("./types").ValueType>(`/workspaces/${wid}/value-types/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),
  /** p.229: changing a constraint appends a version rather than editing one. */
  addValueTypeVersion: (
    wid: string,
    id: string,
    constraint: import("./types").ValueConstraint | null,
  ) =>
    request<import("./types").ValueType>(
      `/workspaces/${wid}/value-types/${id}/versions`,
      { method: "POST", body: JSON.stringify({ constraint }) },
    ),
  valueTypeVersions: (wid: string, id: string) =>
    request<import("./types").ValueTypeVersion[]>(
      `/workspaces/${wid}/value-types/${id}/versions`,
    ),
  valueTypeUsage: (wid: string, id: string) =>
    request<ValueTypeUsage[]>(`/workspaces/${wid}/value-types/${id}/usage`),
  deleteValueType: (wid: string, id: string) =>
    request<void>(`/workspaces/${wid}/value-types/${id}`, { method: "DELETE" }),

  /** Shared properties (`object-link-types` p.178–191). */
  listSharedProperties: (wid: string) =>
    request<import("./types").SharedProperty[]>(`/workspaces/${wid}/shared-properties`),
  createSharedProperty: (wid: string, input: SharedPropertyInput) =>
    request<import("./types").SharedProperty>(`/workspaces/${wid}/shared-properties`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  updateSharedProperty: (wid: string, sharedId: string, input: SharedPropertyInput) =>
    request<import("./types").SharedProperty>(
      `/workspaces/${wid}/shared-properties/${sharedId}`,
      { method: "PATCH", body: JSON.stringify(input) },
    ),
  sharedPropertyUsage: (wid: string, sharedId: string) =>
    request<SharedPropertyUsage[]>(
      `/workspaces/${wid}/shared-properties/${sharedId}/usage`,
    ),
  deleteSharedProperty: (wid: string, sharedId: string) =>
    request<void>(`/workspaces/${wid}/shared-properties/${sharedId}`, {
      method: "DELETE",
    }),

  // ---- object type groups (`object-link-types` p.261-263) ------------------
  listObjectTypeGroups: (wid: string) =>
    request<import("./types").ObjectTypeGroup[]>(
      `/workspaces/${wid}/object-type-groups`,
    ),
  createObjectTypeGroup: (wid: string, input: ObjectTypeGroupInput) =>
    request<import("./types").ObjectTypeGroup>(
      `/workspaces/${wid}/object-type-groups`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  updateObjectTypeGroup: (wid: string, groupId: string, input: ObjectTypeGroupInput) =>
    request<import("./types").ObjectTypeGroup>(
      `/workspaces/${wid}/object-type-groups/${groupId}`,
      { method: "PATCH", body: JSON.stringify(input) },
    ),
  deleteObjectTypeGroup: (wid: string, groupId: string) =>
    request<void>(`/workspaces/${wid}/object-type-groups/${groupId}`, {
      method: "DELETE",
    }),
  objectTypeGroupMembers: (wid: string, groupId: string) =>
    request<import("./types").ObjectTypeGroupMember[]>(
      `/workspaces/${wid}/object-type-groups/${groupId}/members`,
    ),
  /** PUT because the body is the whole membership (p.261's groups menu):
   * "remove the last one" and "set it to these three" are the same request. */
  setObjectTypeGroupMembers: (wid: string, groupId: string, objectTypeIds: string[]) =>
    request<import("./types").ObjectTypeGroupMember[]>(
      `/workspaces/${wid}/object-type-groups/${groupId}/members`,
      { method: "PUT", body: JSON.stringify({ object_type_ids: objectTypeIds }) },
    ),
  groupsForObjectType: (wid: string, typeId: string) =>
    request<import("./types").ObjectTypeGroupRef[]>(
      `/workspaces/${wid}/object-types/${typeId}/groups`,
    ),
  /** p.261's "Edit groups in the object type overview page".
   *
   * **Its own verb, not part of the object type's PATCH.** That endpoint
   * rebuilds the whole definition, so a client predating groups would send no
   * `groups` key and silently un-group every type it saved — the carry-through
   * failure this repo has now met seven times. A classification that is not
   * the type's own field does not belong in the type's own body. */
  setGroupsForObjectType: (wid: string, typeId: string, groupIds: string[]) =>
    request<import("./types").ObjectTypeGroupRef[]>(
      `/workspaces/${wid}/object-types/${typeId}/groups`,
      { method: "PUT", body: JSON.stringify({ group_ids: groupIds }) },
    ),
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
  /** The same bytes as a **Blob**, asked for inline (decision 0009, part 2).
   *
   * **Fetched rather than pointed at, and that is not a style choice.** Cookie
   * authentication here requires the `X-Anchor-Session` header - the CSRF
   * defence that makes a cookie safe to accept at all - and an `<img src>`
   * cannot set headers, so a plain URL in an element attribute is an
   * unauthenticated request and a 401. Exempting this one route would put the
   * hole back on the route that reads private bytes.
   *
   * The Blob keeps the server's own content type, so the allowlist on the
   * server is still what decides whether anything renders; this can only ask. */
  attachmentBlob: async (wid: string, key: string, contentType: string) => {
    const res = await fetch(
      `/api/workspaces/${wid}/attachments/download?key=${encodeURIComponent(key)}` +
        `&disposition=inline&content_type=${encodeURIComponent(contentType)}`,
      { credentials: "same-origin", headers: SESSION_HEADERS },
    );
    if (!res.ok) throw new ApiError(res.status, res.statusText);
    return res.blob();
  },
  typeLinks: (wid: string, typeId: string) =>
    request<import("./types").TypeLink[]>(
      `/workspaces/${wid}/object-types/${typeId}/links`,
    ),
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

export interface ActionDefinitionInput {
  parameters: {
    api_name: string;
    display_name: string;
    data_type: string;
    required?: boolean;
    default_value?: unknown;
    hidden?: boolean;
  }[];
  rules: { kind: string; config: Record<string, unknown> }[];
  criteria: { message: string; config: Record<string, unknown> }[];
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
  /** p.256's status dropdown. Its own call rather than a field on
   * `setDefinition`, because that body is what the action *does* and a status
   * is how much anyone should rely on it — folding them together would make
   * every rule edit a status write. **Omitting a field means unchanged.** */
  setStatus: (
    wid: string,
    actionTypeId: string,
    input: {
      status?: import("./types").OntologyStatus;
      deprecation?: import("./types").Deprecation | null;
    },
  ) =>
    request<import("./types").ActionType>(
      `/workspaces/${wid}/action-types/${actionTypeId}`,
      { method: "PATCH", body: JSON.stringify(input) },
    ),
  /** Parameters, rules and criteria as one document (decision 0007). Whole
   * document because they constrain each other - see the route. */
  setDefinition: (wid: string, actionTypeId: string, input: ActionDefinitionInput) =>
    request<import("./types").ActionType>(
      `/workspaces/${wid}/action-types/${actionTypeId}/definition`,
      { method: "PUT", body: JSON.stringify(input) },
    ),
  /** Would this submission be refused? (Workshop p.513.)
   *
   * The same `check_criteria` the executor runs, asked without writing —
   * which is the whole point: the alternative is the browser evaluating
   * p.54-55's operators in another language, free to disagree with the one
   * that governs writes. */
  check: (
    wid: string,
    pid: string,
    actionTypeId: string,
    values: Record<string, unknown>,
  ) =>
    request<{ ok: boolean; error: string | null }>(
      `/workspaces/${wid}/projects/${pid}/actions/${actionTypeId}/check`,
      { method: "POST", body: JSON.stringify({ values }) },
    ),
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
  /** One action over many objects, as the Object Table's staged inline edits
   * (`workshop` p.242–243, `action-types` p.137–138).
   *
   * **Not a loop over `execute`**, and the difference is the feature: p.138
   * makes the whole submission succeed or fail together, which a browser
   * running N requests could not promise — a failure on the fortieth would
   * leave thirty-nine written and no way to describe the result. */
  executeBatch: (
    wid: string,
    pid: string,
    actionTypeId: string,
    edits: { instance_id: string; values: Record<string, unknown> }[],
  ) =>
    request<import("./types").ActionBatchResult>(
      `/workspaces/${wid}/projects/${pid}/actions/${actionTypeId}/execute-batch`,
      { method: "POST", body: JSON.stringify({ edits }) },
    ),
  getType: (wid: string, actionTypeId: string) =>
    request<import("./types").ActionType>(
      `/workspaces/${wid}/action-types/${actionTypeId}`,
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
    /** Optional note on what changed (Foundry p.191). Never required. */
    versionDescription = "",
  ) =>
    request<import("./types").CanvasAppDetail>(
      `/workspaces/${wid}/projects/${pid}/canvas-apps/${appId}/definition`,
      {
        method: "PUT",
        body: JSON.stringify({ definition, version_description: versionDescription }),
      },
    ),
  /** Resolve every variable, computing derived ones server-side so the
   * transformation semantics have one implementation. */
  evaluateVariables: (
    wid: string,
    pid: string,
    appId: string,
    values: Record<string, unknown>,
    /** Variable ids a host module is backing — see VariableBridge. */
    bound?: string[],
    /** p.76's held values: what each non-automatic variable last computed, so
     * the server uses it instead of recomputing — and so its dependants read
     * the same number the reader is looking at. */
    held?: Record<string, unknown>,
    /** p.85's Recompute event: ids to compute fresh this time. Its own field
     * because for `only_on_event` an absence from `held` is what a page that
     * has never fired the event looks like. */
    recompute?: string[],
  ) =>
    request<{ values: Record<string, unknown>; order: string[] }>(
      `/workspaces/${wid}/projects/${pid}/canvas-apps/${appId}/variables/evaluate`,
      {
        method: "POST",
        body: JSON.stringify({
          values,
          bound: bound ?? [],
          held: held ?? {},
          recompute: recompute ?? [],
        }),
      },
    ),
  /** The same resolve for a published app, which a workspace member may open
   * without being in its project. */
  evaluatePublishedVariables: (
    wid: string,
    appId: string,
    values: Record<string, unknown>,
    bound?: string[],
    held?: Record<string, unknown>,
    recompute?: string[],
  ) =>
    request<{ values: Record<string, unknown>; order: string[] }>(
      `/workspaces/${wid}/published-canvas-apps/${appId}/variables/evaluate`,
      {
        method: "POST",
        body: JSON.stringify({
          values,
          bound: bound ?? [],
          held: held ?? {},
          recompute: recompute ?? [],
        }),
      },
    ),
  /** Saved states (p.200–206).
   *
   * **One base, two routes.** A module is reached project-scoped in the
   * builder and workspace-scoped once published, and state saving matters most
   * on the second — a published module is opened by somebody who may not be in
   * its project at all. `published` picks the prefix rather than there being
   * two sets of functions to keep in step. */
  statesBase: (wid: string, pid: string, appId: string, published: boolean) =>
    published
      ? `/workspaces/${wid}/published-canvas-apps/${appId}/states`
      : `/workspaces/${wid}/projects/${pid}/canvas-apps/${appId}/states`,
  listStates: (wid: string, pid: string, appId: string, published = false) =>
    request<import("./types").ModuleState[]>(
      canvas.statesBase(wid, pid, appId, published),
    ),
  saveState: (
    wid: string,
    pid: string,
    appId: string,
    input: { name: string; values: Record<string, unknown>; page_id?: string | null },
    published = false,
  ) =>
    request<import("./types").ModuleState>(canvas.statesBase(wid, pid, appId, published), {
      method: "POST",
      body: JSON.stringify(input),
    }),
  openState: (wid: string, pid: string, appId: string, stateId: string, published = false) =>
    request<import("./types").ModuleStateDetail>(
      `${canvas.statesBase(wid, pid, appId, published)}/${stateId}`,
    ),
  deleteState: (wid: string, pid: string, appId: string, stateId: string, published = false) =>
    request<void>(`${canvas.statesBase(wid, pid, appId, published)}/${stateId}`, {
      method: "DELETE",
    }),
  listVersions: (wid: string, pid: string, appId: string) =>
    request<import("./types").CanvasAppVersion[]>(
      `/workspaces/${wid}/projects/${pid}/canvas-apps/${appId}/versions`,
    ),
  /** One saved version, definition included — "View this version" (p.191). */
  getVersion: (wid: string, pid: string, appId: string, version: number) =>
    request<import("./types").CanvasAppVersion & { definition: Record<string, unknown> }>(
      `/workspaces/${wid}/projects/${pid}/canvas-apps/${appId}/versions/${version}`,
    ),
  describeVersion: (wid: string, pid: string, appId: string, version: number, description: string) =>
    request<import("./types").CanvasAppVersion>(
      `/workspaces/${wid}/projects/${pid}/canvas-apps/${appId}/versions/${version}`,
      { method: "PATCH", body: JSON.stringify({ description }) },
    ),
  publishVersion: (wid: string, pid: string, appId: string, version: number) =>
    request<import("./types").CanvasApp>(
      `/workspaces/${wid}/projects/${pid}/canvas-apps/${appId}/versions/${version}/publish`,
      { method: "POST" },
    ),
  revertToVersion: (wid: string, pid: string, appId: string, version: number) =>
    request<import("./types").CanvasApp>(
      `/workspaces/${wid}/projects/${pid}/canvas-apps/${appId}/versions/${version}/revert`,
      { method: "POST" },
    ),
  setVersionSettings: (
    wid: string, pid: string, appId: string,
    settings: { auto_publish_on_save?: boolean; prompt_for_description?: boolean },
  ) =>
    request<import("./types").CanvasApp>(
      `/workspaces/${wid}/projects/${pid}/canvas-apps/${appId}/version-settings`,
      { method: "PUT", body: JSON.stringify(settings) },
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
    input: {
      summary: string;
      description?: string;
      /** Files typed into the proposal, or a commit to publish - never both. */
      changes?: { model_id: string; code: string }[];
      source_repo_id?: string;
      source_commit_id?: string;
    },
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
  /** Anchor a remark to a line, or to the file when `line` is absent. Viewer
   * level, unlike a verdict: asking a question is not approving. */
  comment: (
    wid: string,
    pid: string,
    id: string,
    input: {
      /** One of these, never both: a file with no model yet anchors by path. */
      model_id?: string | null;
      source_path?: string | null;
      side: "live" | "proposed";
      line?: number | null;
      body: string;
    },
  ) =>
    request<import("./types").CodeProposalDetail>(
      `/workspaces/${wid}/projects/${pid}/code/proposals/${id}/comments`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  resolveComment: (
    wid: string,
    pid: string,
    id: string,
    commentId: string,
    resolved: boolean,
  ) =>
    request<import("./types").CodeProposalDetail>(
      `/workspaces/${wid}/projects/${pid}/code/proposals/${id}/comments/${commentId}`,
      { method: "PATCH", body: JSON.stringify({ resolved }) },
    ),
  /** Per-file resolution. Cleared by an edit to the proposal, without a write. */
  markFileRead: (
    wid: string,
    pid: string,
    id: string,
    input: { model_id?: string | null; source_path?: string | null; read: boolean },
  ) =>
    request<import("./types").CodeProposalDetail>(
      `/workspaces/${wid}/projects/${pid}/code/proposals/${id}/read`,
      { method: "PUT", body: JSON.stringify(input) },
    ),
  /** Run every check against the proposal's current files (roadmap 2.8).
   * Editor level: it executes the proposed SQL against the project's data. */
  runChecks: (wid: string, pid: string, id: string) =>
    request<import("./types").CodeProposalDetail>(
      `/workspaces/${wid}/projects/${pid}/code/proposals/${id}/checks`,
      { method: "POST" },
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
