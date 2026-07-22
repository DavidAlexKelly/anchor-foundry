"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import {
  actions as actionApi,
  ApiError,
  datasets as dsApi,
  objects as objApi,
  type PropertyInput,
} from "@/lib/api";
import { Dialog, Field } from "@/components/dialog";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";
import type {
  ActionType,
  Dataset,
  LinkCardinality,
  LinkType,
  ObjectTypeSource,
  ObjectTypeSummary,
  ObjectTypeSuggestion,
  PropertyDataType,
} from "@/lib/types";

const PROPERTY_TYPES: PropertyDataType[] = [
  "string", "integer", "float", "boolean", "date", "timestamp", "geopoint", "json",
];
const CARDINALITIES: LinkCardinality[] = ["one_to_one", "one_to_many", "many_to_many"];

function toApiName(display: string, typeCase: boolean): string {
  const words = display.match(/[A-Za-z0-9]+/g) ?? [];
  if (words.length === 0) return "";
  return typeCase
    ? words.map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join("").slice(0, 100)
    : words.map((w) => w.toLowerCase()).join("_").slice(0, 100);
}

// ---- object type creation (manual or pre-filled from a suggestion) --------
function ObjectTypeDialog({
  workspaceId,
  initial,
  onClose,
  onCreated,
}: {
  workspaceId: string;
  initial?: { displayName: string; properties: PropertyInput[]; titleProperty: string | null };
  onClose: () => void;
  onCreated?: (typeId: string) => void;
}) {
  const [displayName, setDisplayName] = useState(initial?.displayName ?? "");
  const [description, setDescription] = useState("");
  const [properties, setProperties] = useState<PropertyInput[]>(
    initial?.properties ?? [{ api_name: "", data_type: "string", required: false }],
  );
  const [titleProperty, setTitleProperty] = useState(initial?.titleProperty ?? "");
  const queryClient = useQueryClient();

  const create = useMutation({
    mutationFn: () =>
      objApi.createType(workspaceId, {
        api_name: toApiName(displayName, true),
        display_name: displayName,
        description,
        properties: properties.filter((p) => p.api_name.trim()),
        title_property: titleProperty || null,
      }),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ["object-types", workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["link-types", workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["project", workspaceId] });
      onCreated?.(created.id);
      onClose();
    },
  });

  return (
    <Dialog open wide title="New object type" onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <Field
          label="Display name"
          hint={displayName ? `API name: ${toApiName(displayName, true) || "—"}` : "e.g. Customer"}
        >
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            required
            maxLength={200}
            autoFocus
          />
        </Field>
        <Field label="Description" hint="Optional">
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={2000}
          />
        </Field>
        <Field label="Properties" hint="Typed fields on this object">
          <div>
            {properties.map((prop, index) => (
              <div key={index} className="row-actions" style={{ marginBottom: 6 }}>
                <input
                  type="text"
                  placeholder="property_name"
                  style={{
                    fontFamily: "var(--font-mono)", fontSize: 12.5,
                    padding: "4px 8px", border: "1px solid var(--line-strong)",
                    borderRadius: "var(--radius)", width: 160,
                  }}
                  value={prop.api_name}
                  onChange={(e) => {
                    const next = [...properties];
                    next[index] = { ...prop, api_name: toApiName(e.target.value, false) };
                    setProperties(next);
                  }}
                />
                <select
                  value={prop.data_type}
                  onChange={(e) => {
                    const next = [...properties];
                    next[index] = { ...prop, data_type: e.target.value as PropertyDataType };
                    setProperties(next);
                  }}
                >
                  {PROPERTY_TYPES.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
                <label style={{ fontSize: 12.5, display: "flex", gap: 4, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={!!prop.required}
                    onChange={(e) => {
                      const next = [...properties];
                      next[index] = { ...prop, required: e.target.checked };
                      setProperties(next);
                    }}
                  />
                  required
                </label>
                <button
                  type="button"
                  className="btn danger"
                  style={{ padding: "3px 9px", fontSize: 12 }}
                  onClick={() => setProperties(properties.filter((_, i) => i !== index))}
                >
                  Remove
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn quiet"
              style={{ padding: "4px 10px", fontSize: 12.5 }}
              onClick={() =>
                setProperties([...properties, { api_name: "", data_type: "string", required: false }])
              }
            >
              Add property
            </button>
          </div>
        </Field>
        <Field label="Title property" hint="Shown as the object's name — optional">
          <select value={titleProperty} onChange={(e) => setTitleProperty(e.target.value)}>
            <option value="">None</option>
            {properties.filter((p) => p.api_name).map((p) => (
              <option key={p.api_name} value={p.api_name}>{p.api_name}</option>
            ))}
          </select>
        </Field>
        {create.isError && (
          <div className="form-error">
            {create.error instanceof ApiError && create.error.status === 409
              ? "An object type with this name already exists."
              : create.error instanceof ApiError ? create.error.message : "Couldn't create the object type."}
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn quiet" onClick={onClose}>Cancel</button>
          <button
            type="submit"
            className="btn"
            disabled={create.isPending || !displayName.trim() || !toApiName(displayName, true)}
          >
            {create.isPending ? "Creating…" : "Create object type"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

// ---- suggest an object type from a dataset's schema -----------------------
function SuggestDialog({
  workspaceId,
  projectId,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  onClose: () => void;
}) {
  const [datasetId, setDatasetId] = useState("");
  const [suggestion, setSuggestion] = useState<ObjectTypeSuggestion | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [included, setIncluded] = useState<Record<string, boolean>>({});
  const queryClient = useQueryClient();

  const projectDatasets = useQuery({
    queryKey: ["datasets", projectId],
    queryFn: () => dsApi.list(workspaceId, projectId),
  });

  const suggest = useMutation({
    mutationFn: (id: string) => objApi.suggest(workspaceId, projectId, id),
    onSuccess: (result) => {
      setSuggestion(result);
      setDisplayName(result.suggested_display_name);
      setIncluded(Object.fromEntries(result.properties.map((p) => [p.api_name, true])));
    },
  });

  const createAndMap = useMutation({
    mutationFn: async () => {
      if (!suggestion) throw new Error("no suggestion");
      const chosen = suggestion.properties.filter((p) => included[p.api_name]);
      const type = await objApi.createType(workspaceId, {
        api_name: toApiName(displayName, true),
        display_name: displayName,
        properties: chosen.map((p) => ({
          api_name: p.api_name, data_type: p.data_type, required: p.required,
        })),
        title_property: suggestion.suggested_title_property,
      });
      const mappings = Object.fromEntries(chosen.map((p) => [p.source_column, p.api_name]));
      const pk = suggestion.suggested_primary_key;
      const pkColumn = pk && chosen.some((p) => p.source_column === pk) ? pk : chosen[0]?.source_column;
      if (!pkColumn) throw new Error("select at least one property to map");
      await objApi.createSource(workspaceId, projectId, {
        object_type_id: type.id,
        dataset_id: datasetId,
        primary_key_column: pkColumn,
        column_mappings: mappings,
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["object-types", workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["object-sources", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["project", workspaceId] });
      onClose();
    },
  });

  return (
    <Dialog open wide title="Suggest an object type from a dataset" onClose={onClose}>
      <Field label="Dataset" hint="Pick a dataset and we'll suggest an object type from its columns">
        <select
          value={datasetId}
          onChange={(e) => {
            setDatasetId(e.target.value);
            setSuggestion(null);
            if (e.target.value) suggest.mutate(e.target.value);
          }}
        >
          <option value="">Choose a dataset…</option>
          {projectDatasets.data?.map((d: Dataset) => (
            <option key={d.id} value={d.id}>{d.name}</option>
          ))}
        </select>
      </Field>

      {suggest.isPending && <p className="login-note">Looking at the schema…</p>}

      {suggestion && (
        <>
          <Field label="Object type name">
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              maxLength={200}
            />
          </Field>
          <Field label="Properties to include">
            <div>
              {suggestion.properties.map((p) => (
                <label
                  key={p.api_name}
                  style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, padding: "3px 0" }}
                >
                  <input
                    type="checkbox"
                    checked={!!included[p.api_name]}
                    onChange={(e) => setIncluded({ ...included, [p.api_name]: e.target.checked })}
                  />
                  <span className="chip">{p.data_type}</span>
                  <strong>{p.api_name}</strong>
                  <span style={{ color: "var(--ink-soft)" }}>from column {p.source_column}</span>
                  {p.api_name === suggestion.suggested_primary_key && <span className="chip brass">primary key</span>}
                </label>
              ))}
            </div>
          </Field>
        </>
      )}

      {createAndMap.isError && (
        <div className="form-error">
          {createAndMap.error instanceof ApiError ? createAndMap.error.message : "Couldn't create the object type."}
        </div>
      )}
      <div className="form-actions">
        <button type="button" className="btn quiet" onClick={onClose}>Cancel</button>
        <button
          type="button"
          className="btn"
          disabled={!suggestion || createAndMap.isPending || !displayName.trim()}
          onClick={() => createAndMap.mutate()}
        >
          {createAndMap.isPending ? "Creating…" : "Create type & map dataset"}
        </button>
      </div>
    </Dialog>
  );
}

// ---- link types -------------------------------------------------------------
function LinkTypeDialog({
  workspaceId,
  types,
  onClose,
}: {
  workspaceId: string;
  types: ObjectTypeSummary[];
  onClose: () => void;
}) {
  const [displayName, setDisplayName] = useState("");
  const [fromId, setFromId] = useState("");
  const [toId, setToId] = useState("");
  const [cardinality, setCardinality] = useState<LinkCardinality>("one_to_many");
  const queryClient = useQueryClient();

  const create = useMutation({
    mutationFn: () =>
      objApi.createLinkType(workspaceId, {
        api_name: toApiName(displayName, false),
        display_name: displayName,
        from_type_id: fromId,
        to_type_id: toId,
        cardinality,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["link-types", workspaceId] });
      onClose();
    },
  });

  return (
    <Dialog open title="New link type" onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
        <Field label="Name" hint="e.g. Placed, Owns, Reports to">
          <input type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)} required maxLength={200} autoFocus />
        </Field>
        <Field label="From">
          <select value={fromId} onChange={(e) => setFromId(e.target.value)} required>
            <option value="">Choose a type…</option>
            {types.map((t) => <option key={t.id} value={t.id}>{t.display_name}</option>)}
          </select>
        </Field>
        <Field label="To">
          <select value={toId} onChange={(e) => setToId(e.target.value)} required>
            <option value="">Choose a type…</option>
            {types.map((t) => <option key={t.id} value={t.id}>{t.display_name}</option>)}
          </select>
        </Field>
        <Field label="Cardinality">
          <select value={cardinality} onChange={(e) => setCardinality(e.target.value as LinkCardinality)}>
            {CARDINALITIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </Field>
        {create.isError && (
          <div className="form-error">
            {create.error instanceof ApiError ? create.error.message : "Couldn't create the link type."}
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn quiet" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn" disabled={create.isPending || !displayName.trim() || !fromId || !toId}>
            {create.isPending ? "Creating…" : "Create link type"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

// ---- action types (write-back) ---------------------------------------------
function ActionTypeDialog({
  workspaceId,
  types,
  onClose,
}: {
  workspaceId: string;
  types: ObjectTypeSummary[];
  onClose: () => void;
}) {
  const [objectTypeId, setObjectTypeId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [editable, setEditable] = useState<Record<string, boolean>>({});
  const queryClient = useQueryClient();

  const typeDetail = useQuery({
    queryKey: ["object-type", objectTypeId],
    queryFn: () => objApi.getType(workspaceId, objectTypeId),
    enabled: !!objectTypeId,
  });

  const create = useMutation({
    mutationFn: () =>
      actionApi.createType(workspaceId, {
        object_type_id: objectTypeId,
        api_name: toApiName(displayName, false),
        display_name: displayName,
        description,
        editable_properties: Object.entries(editable).filter(([, v]) => v).map(([k]) => k),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["action-types", workspaceId] });
      onClose();
    },
  });

  const editableCount = Object.values(editable).filter(Boolean).length;

  return (
    <Dialog open title="New action" onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
        <Field label="Object type">
          <select
            value={objectTypeId}
            onChange={(e) => { setObjectTypeId(e.target.value); setEditable({}); }}
            required
          >
            <option value="">Choose a type…</option>
            {types.map((t) => <option key={t.id} value={t.id}>{t.display_name}</option>)}
          </select>
        </Field>
        <Field label="Name" hint="e.g. Update contact, Approve, Close case">
          <input type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)} required maxLength={200} autoFocus />
        </Field>
        <Field label="Description" hint="Optional">
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} />
        </Field>
        {typeDetail.data && (
          <Field label="Editable properties" hint="What this action is allowed to write back">
            <div>
              {typeDetail.data.properties.map((p) => (
                <label key={p.api_name} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, padding: "3px 0" }}>
                  <input
                    type="checkbox"
                    checked={!!editable[p.api_name]}
                    onChange={(e) => setEditable({ ...editable, [p.api_name]: e.target.checked })}
                  />
                  <strong>{p.api_name}</strong>
                  <span className="chip">{p.data_type}</span>
                </label>
              ))}
            </div>
          </Field>
        )}
        {create.isError && (
          <div className="form-error">
            {create.error instanceof ApiError ? create.error.message : "Couldn't create the action."}
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn quiet" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn" disabled={create.isPending || !displayName.trim() || !objectTypeId || editableCount === 0}>
            {create.isPending ? "Creating…" : "Create action"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

// ---- map a dataset onto an existing object type ----------------------------
function SourceDialog({
  workspaceId,
  projectId,
  types,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  types: ObjectTypeSummary[];
  onClose: () => void;
}) {
  const [typeId, setTypeId] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [primaryKey, setPrimaryKey] = useState("");
  const [mappings, setMappings] = useState<Record<string, string>>({});
  const queryClient = useQueryClient();

  const projectDatasets = useQuery({
    queryKey: ["datasets", projectId],
    queryFn: () => dsApi.list(workspaceId, projectId),
  });
  const typeDetail = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId),
    enabled: !!typeId,
  });
  const dataset = projectDatasets.data?.find((d) => d.id === datasetId);

  const create = useMutation({
    mutationFn: () =>
      objApi.createSource(workspaceId, projectId, {
        object_type_id: typeId,
        dataset_id: datasetId,
        primary_key_column: primaryKey,
        column_mappings: Object.fromEntries(Object.entries(mappings).filter(([, v]) => v)),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["object-sources", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["object-types", workspaceId] });
      onClose();
    },
  });

  return (
    <Dialog open wide title="Map a dataset to an object type" onClose={onClose}>
      <Field label="Object type">
        <select value={typeId} onChange={(e) => { setTypeId(e.target.value); setMappings({}); }} required>
          <option value="">Choose a type…</option>
          {types.map((t) => <option key={t.id} value={t.id}>{t.display_name}</option>)}
        </select>
      </Field>
      <Field label="Dataset">
        <select
          value={datasetId}
          onChange={(e) => { setDatasetId(e.target.value); setPrimaryKey(""); setMappings({}); }}
          required
        >
          <option value="">Choose a dataset…</option>
          {projectDatasets.data?.map((d: Dataset) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
      </Field>
      {dataset && (
        <Field label="Primary key column">
          <select value={primaryKey} onChange={(e) => setPrimaryKey(e.target.value)} required>
            <option value="">Choose a column…</option>
            {dataset.table_schema.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
          </select>
        </Field>
      )}
      {dataset && typeDetail.data && (
        <Field label="Column mappings" hint="Map dataset columns onto the object type's properties">
          <table className="table">
            <thead><tr><th>Column</th><th>Property</th></tr></thead>
            <tbody>
              {dataset.table_schema.map((c) => (
                <tr key={c.name}>
                  <td className="slug">{c.name}</td>
                  <td>
                    <select
                      value={mappings[c.name] ?? ""}
                      onChange={(e) => setMappings({ ...mappings, [c.name]: e.target.value })}
                    >
                      <option value="">— skip —</option>
                      {typeDetail.data.properties.map((p) => (
                        <option key={p.api_name} value={p.api_name}>{p.api_name}</option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Field>
      )}
      {create.isError && (
        <div className="form-error">
          {create.error instanceof ApiError ? create.error.message : "Couldn't create the mapping."}
        </div>
      )}
      <div className="form-actions">
        <button type="button" className="btn quiet" onClick={onClose}>Cancel</button>
        <button
          type="submit"
          className="btn"
          disabled={create.isPending || !typeId || !datasetId || !primaryKey}
          onClick={() => create.mutate()}
        >
          {create.isPending ? "Saving…" : "Create mapping"}
        </button>
      </div>
    </Dialog>
  );
}

const SYNC_STATUS_CLASS: Record<string, string> = {
  ok: "status-ok",
  error: "status-error",
  syncing: "status-testing",
  never_synced: "status-unconfigured",
};

function SourceRow({
  workspaceId,
  projectId,
  source,
  canEdit,
  onRemove,
}: {
  workspaceId: string;
  projectId: string;
  source: ObjectTypeSource;
  canEdit: boolean;
  onRemove: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const sync = useMutation({
    mutationFn: () => objApi.syncSource(workspaceId, projectId, source.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["object-sources", projectId] });
    },
  });
  const result = sync.data;

  return (
    <tr>
      <td>
        <strong>{source.object_type_name}</strong>
      </td>
      <td>{source.dataset_name}</td>
      <td className="slug">{source.primary_key_column}</td>
      <td>
        <span className={SYNC_STATUS_CLASS[source.sync_status] ?? "status-unconfigured"}>
          <span className="status-dot" />
          <span className="status-label">{source.sync_status.replace("_", " ")}</span>
        </span>
        {source.last_synced_at && (
          <div className="slug">{new Date(source.last_synced_at).toLocaleString()}</div>
        )}
        {source.last_error && (
          <div className="form-error" style={{ marginTop: 4 }}>{source.last_error}</div>
        )}
        {result && result.ok && (
          <p className="login-note" style={{ margin: "4px 0 0" }}>
            {result.upserted} synced{result.removed > 0 ? `, ${result.removed} removed` : ""}
          </p>
        )}
      </td>
      <td>
        {canEdit && (
          <div className="row-actions">
            <button
              className="btn"
              style={{ padding: "3px 11px", fontSize: 12 }}
              disabled={sync.isPending}
              onClick={() => sync.mutate()}
            >
              {sync.isPending ? "Syncing…" : "Sync now"}
            </button>
            <button
              className="btn danger"
              style={{ padding: "3px 9px", fontSize: 12 }}
              onClick={() => onRemove(source.id)}
            >
              Remove
            </button>
          </div>
        )}
      </td>
    </tr>
  );
}

export default function ObjectsPage() {
  const params = useParams<{ workspace: string; project: string }>();
  const { workspace } = useWorkspaceBySlug(params.workspace);
  const { project } = useProjectBySlug(workspace?.id, params.project);
  const [creatingType, setCreatingType] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [creatingLink, setCreatingLink] = useState(false);
  const [creatingSource, setCreatingSource] = useState(false);
  const [creatingAction, setCreatingAction] = useState(false);
  const queryClient = useQueryClient();

  const types = useQuery({
    queryKey: ["object-types", workspace?.id],
    queryFn: () => objApi.listTypes(workspace!.id),
    enabled: !!workspace,
  });
  const linkTypes = useQuery({
    queryKey: ["link-types", workspace?.id],
    queryFn: () => objApi.listLinkTypes(workspace!.id),
    enabled: !!workspace,
  });
  const sources = useQuery({
    queryKey: ["object-sources", project?.id],
    queryFn: () => objApi.listSources(workspace!.id, project!.id),
    enabled: !!workspace && !!project,
  });
  const actionTypes = useQuery({
    queryKey: ["action-types", workspace?.id],
    queryFn: () => actionApi.listTypes(workspace!.id),
    enabled: !!workspace,
  });

  const removeType = useMutation({
    mutationFn: (typeId: string) => objApi.removeType(workspace!.id, typeId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["object-types", workspace?.id] });
      queryClient.invalidateQueries({ queryKey: ["link-types", workspace?.id] });
      queryClient.invalidateQueries({ queryKey: ["object-sources", project?.id] });
      queryClient.invalidateQueries({ queryKey: ["action-types", workspace?.id] });
      queryClient.invalidateQueries({ queryKey: ["project", workspace?.id] });
    },
  });
  const removeLink = useMutation({
    mutationFn: (linkId: string) => objApi.removeLinkType(workspace!.id, linkId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["link-types", workspace?.id] }),
  });
  const removeSource = useMutation({
    mutationFn: (sourceId: string) => objApi.removeSource(workspace!.id, project!.id, sourceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["object-sources", project?.id] });
      queryClient.invalidateQueries({ queryKey: ["object-types", workspace?.id] });
    },
  });
  const removeAction = useMutation({
    mutationFn: (actionTypeId: string) => actionApi.removeType(workspace!.id, actionTypeId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["action-types", workspace?.id] }),
  });

  const canEditOntology = workspace ? workspace.effective_role !== "viewer" : false;
  const canEditSources = project ? project.effective_role !== "viewer" : false;

  return (
    <main>
      <div className="page-head">
        <div>
          <p className="eyebrow">project · objects</p>
          <h1>Objects</h1>
        </div>
        {canEditOntology && (
          <div className="row-actions">
            <button className="btn quiet" onClick={() => setSuggesting(true)}>Suggest from dataset</button>
            <button className="btn" onClick={() => setCreatingType(true)}>Define object type</button>
          </div>
        )}
      </div>

      {types.isPending && <div className="state">Loading the ontology…</div>}
      {types.isError && <div className="state error">Couldn&apos;t load object types. Refresh to try again.</div>}

      {types.data && types.data.length === 0 && (
        <div className="empty">
          <h2>The ontology starts here</h2>
          <p>Object types give your data business meaning: a Customer, an Order, a Shipment — typed properties, typed relationships, shared across the workspace.</p>
          {canEditOntology && (
            <div className="row-actions" style={{ justifyContent: "center" }}>
              <button className="btn quiet" onClick={() => setSuggesting(true)}>Suggest from dataset</button>
              <button className="btn" onClick={() => setCreatingType(true)}>Define object type</button>
            </div>
          )}
        </div>
      )}

      {types.data && types.data.length > 0 && (
        <>
          <table className="table" style={{ marginBottom: 28 }}>
            <thead>
              <tr><th>Object type</th><th>Sources</th><th aria-label="Actions" /></tr>
            </thead>
            <tbody>
              {types.data.map((t) => (
                <tr key={t.id}>
                  <td>
                    <strong>{t.display_name}</strong>
                    <div className="slug">{t.api_name}</div>
                  </td>
                  <td className="count">{t.source_count}</td>
                  <td>
                    <div className="row-actions">
                      <Link
                        href={`/${params.workspace}/${params.project}/objects/${t.id}`}
                        className="btn quiet"
                        style={{ padding: "3px 9px", fontSize: 12 }}
                      >
                        Browse
                      </Link>
                      {canEditOntology && (
                        <button
                          className="btn danger"
                          style={{ padding: "3px 9px", fontSize: 12 }}
                          disabled={removeType.isPending}
                          onClick={() => {
                            if (window.confirm(`Delete ${t.display_name}? Its link types and dataset mappings go with it.`)) {
                              removeType.mutate(t.id);
                            }
                          }}
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="page-head" style={{ marginTop: 32 }}>
            <div><h2 style={{ fontSize: 15, margin: 0 }}>Link types</h2></div>
            {canEditOntology && types.data.length >= 2 && (
              <button className="btn quiet" onClick={() => setCreatingLink(true)}>New link type</button>
            )}
          </div>
          {linkTypes.data && linkTypes.data.length === 0 && (
            <p className="login-note">No link types yet — define relationships between object types once you have at least two.</p>
          )}
          {linkTypes.data && linkTypes.data.length > 0 && (
            <table className="table" style={{ marginBottom: 28 }}>
              <thead><tr><th>Link</th><th>From → To</th><th>Cardinality</th><th aria-label="Actions" /></tr></thead>
              <tbody>
                {linkTypes.data.map((lt: LinkType) => (
                  <tr key={lt.id}>
                    <td><strong>{lt.display_name}</strong></td>
                    <td>{lt.from_display_name} → {lt.to_display_name}</td>
                    <td className="count">{lt.cardinality}</td>
                    <td>
                      {canEditOntology && (
                        <button
                          className="btn danger"
                          style={{ padding: "3px 9px", fontSize: 12 }}
                          disabled={removeLink.isPending}
                          onClick={() => removeLink.mutate(lt.id)}
                        >
                          Delete
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className="page-head" style={{ marginTop: 32 }}>
            <div>
              <h2 style={{ fontSize: 15, margin: 0 }}>Actions</h2>
              <p className="sub">Write-back operations available on an object type&apos;s instances</p>
            </div>
            {canEditOntology && (
              <button className="btn quiet" onClick={() => setCreatingAction(true)}>New action</button>
            )}
          </div>
          {actionTypes.data && actionTypes.data.length === 0 && (
            <p className="login-note">No actions yet — define one to let instances write values back to their mapped datasets.</p>
          )}
          {actionTypes.data && actionTypes.data.length > 0 && (
            <table className="table" style={{ marginBottom: 28 }}>
              <thead><tr><th>Action</th><th>Object type</th><th>Editable properties</th><th aria-label="Actions" /></tr></thead>
              <tbody>
                {actionTypes.data.map((a: ActionType) => (
                  <tr key={a.id}>
                    <td><strong>{a.display_name}</strong><div className="slug">{a.api_name}</div></td>
                    <td>{a.object_type_name}</td>
                    <td>{a.editable_properties.map((p) => <span key={p} className="chip" style={{ marginRight: 4 }}>{p}</span>)}</td>
                    <td>
                      {canEditOntology && (
                        <button
                          className="btn danger"
                          style={{ padding: "3px 9px", fontSize: 12 }}
                          disabled={removeAction.isPending}
                          onClick={() => removeAction.mutate(a.id)}
                        >
                          Delete
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className="page-head" style={{ marginTop: 32 }}>
            <div>
              <h2 style={{ fontSize: 15, margin: 0 }}>Dataset mappings</h2>
              <p className="sub">Datasets in this project mapped onto the workspace ontology</p>
            </div>
            {canEditSources && (
              <button className="btn quiet" onClick={() => setCreatingSource(true)}>Map a dataset</button>
            )}
          </div>
          {sources.data && sources.data.length === 0 && (
            <p className="login-note">No datasets are mapped yet in this project.</p>
          )}
          {sources.data && sources.data.length > 0 && workspace && project && (
            <table className="table">
              <thead><tr><th>Object type</th><th>Dataset</th><th>Primary key</th><th>Status</th><th aria-label="Actions" /></tr></thead>
              <tbody>
                {sources.data.map((s) => (
                  <SourceRow
                    key={s.id}
                    workspaceId={workspace.id}
                    projectId={project.id}
                    source={s}
                    canEdit={canEditSources}
                    onRemove={(id) => removeSource.mutate(id)}
                  />
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      {creatingType && workspace && (
        <ObjectTypeDialog workspaceId={workspace.id} onClose={() => setCreatingType(false)} />
      )}
      {suggesting && workspace && project && (
        <SuggestDialog workspaceId={workspace.id} projectId={project.id} onClose={() => setSuggesting(false)} />
      )}
      {creatingLink && workspace && types.data && (
        <LinkTypeDialog workspaceId={workspace.id} types={types.data} onClose={() => setCreatingLink(false)} />
      )}
      {creatingSource && workspace && project && types.data && (
        <SourceDialog
          workspaceId={workspace.id}
          projectId={project.id}
          types={types.data}
          onClose={() => setCreatingSource(false)}
        />
      )}
      {creatingAction && workspace && types.data && (
        <ActionTypeDialog
          workspaceId={workspace.id}
          types={types.data}
          onClose={() => setCreatingAction(false)}
        />
      )}
    </main>
  );
}
