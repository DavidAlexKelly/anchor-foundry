"use client";

/**
 * The groups menu (Foundry `object-link-types` p.261–263).
 *
 * > "Groups are created and managed via the groups menu, accessible in the
 * > Ontology Manager sidebar." (p.261)
 *
 * A section of the ontology page rather than a menu destination of its own,
 * for the reason shared properties and value types are: this application puts
 * one workspace's ontology on one page.
 *
 * **An empty group is drawn like any other**, and that is the feature rather
 * than a detail. p.263 records Foundry changing the rule — a group used to be
 * non-discoverable when all its members were, and now "all groups will now be
 * discoverable to any user that can view the ontology … to increase clarity
 * and transparency in governance". The first thing anybody does with a new
 * group is look for it before they have put anything in it, so a listing that
 * hid it would fail on the very first use.
 *
 * **Delete says what it will *not* do.** A group carries no schema, so
 * deleting one deletes the classification and nothing else — unusually benign,
 * and therefore worth saying, because somebody expecting a cascade will not
 * press the button at all. Same reasoning as the shared property panel's
 * delete, opposite fact.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Dialog, Field } from "@/components/dialog";
import { ApiError, objects as objApi, type ObjectTypeGroupInput } from "@/lib/api";
import { memberSummary, toGroupApiName, toggleSelection } from "@/lib/object-type-groups";
import type { ObjectTypeGroup } from "@/lib/types";

/** p.261's create, and the rename beside it. One dialog, because the fields
 * are the same two and two forms would be two places for one to go missing. */
function GroupDialog({
  workspaceId,
  existing,
  onClose,
}: {
  workspaceId: string;
  /** Absent when creating. When present, `api_name` is not editable — it is
   * what p.262's search matches on, and the API has no parameter for it. */
  existing?: ObjectTypeGroup;
  onClose: () => void;
}) {
  const [displayName, setDisplayName] = useState(existing?.display_name ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const queryClient = useQueryClient();

  const body: ObjectTypeGroupInput = {
    display_name: displayName,
    description,
    ...(existing ? {} : { api_name: toGroupApiName(displayName) }),
  };

  const save = useMutation({
    mutationFn: () =>
      existing
        ? objApi.updateObjectTypeGroup(workspaceId, existing.id, body)
        : objApi.createObjectTypeGroup(workspaceId, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["object-type-groups", workspaceId],
      });
      // A renamed group is drawn on every object type row that is in it
      // (p.262's column), so the listing is stale by exactly this edit.
      await queryClient.invalidateQueries({ queryKey: ["object-types", workspaceId] });
      onClose();
    },
  });

  return (
    <Dialog
      open
      title={existing ? `Edit ${existing.api_name}` : "New group"}
      onClose={onClose}
    >
      <Field label="Name">
        <input
          type="text"
          data-testid="group-name"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
        />
      </Field>
      {!existing && (
        <p className="field-hint" data-testid="group-api-name">
          API name: <code>{toGroupApiName(displayName) || "…"}</code>
        </p>
      )}
      <Field
        label="Description"
        hint="p.261: what somebody would be looking for when they reach for this group."
      >
        <input
          type="text"
          data-testid="group-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </Field>
      {save.isError && (
        <p className="field-hint" data-testid="group-error">
          {save.error instanceof ApiError ? save.error.message : "Could not save."}
        </p>
      )}
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button
          type="button"
          className="btn primary"
          data-testid="group-save"
          disabled={!displayName.trim() || save.isPending}
          onClick={() => save.mutate()}
        >
          Save
        </button>
      </div>
    </Dialog>
  );
}

/** Which object types are in this group — p.261's groups-menu direction.
 *
 * A whole-membership PUT rather than add/remove buttons, because that is what
 * the endpoint is: "remove the last one" and "set it to these three" are the
 * same request, and a screen that made them different verbs would be inventing
 * a distinction the server does not have.
 */
function MembersDialog({
  workspaceId,
  group,
  onClose,
}: {
  workspaceId: string;
  group: ObjectTypeGroup;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const types = useQuery({
    queryKey: ["object-types", workspaceId],
    queryFn: () => objApi.listTypes(workspaceId),
  });
  const members = useQuery({
    queryKey: ["object-type-group-members", workspaceId, group.id],
    queryFn: () => objApi.objectTypeGroupMembers(workspaceId, group.id),
  });

  const [selected, setSelected] = useState<string[] | null>(null);
  // Seeded from the server's answer on first arrival rather than in an effect:
  // the dialog can render before the members do, and an effect would leave one
  // frame in which nothing is ticked — which looks like an emptied group.
  const current = selected ?? (members.data ? members.data.map((m) => m.id) : null);

  const save = useMutation({
    mutationFn: () =>
      objApi.setObjectTypeGroupMembers(workspaceId, group.id, current ?? []),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["object-type-groups", workspaceId],
      });
      await queryClient.invalidateQueries({ queryKey: ["object-types", workspaceId] });
      await queryClient.invalidateQueries({
        queryKey: ["object-type-group-members", workspaceId, group.id],
      });
      onClose();
    },
  });

  return (
    <Dialog open title={`Object types in ${group.display_name}`} onClose={onClose}>
      {types.data && types.data.length === 0 && (
        <p className="field-hint">
          There are no object types yet — a group is somewhere to put them once
          there are.
        </p>
      )}
      {types.data && types.data.length > 0 && current && (
        <div data-testid="group-member-picker">
          {types.data.map((t) => (
            <label key={t.id} style={{ display: "block", padding: "3px 0" }}>
              <input
                type="checkbox"
                data-testid={`group-member-${t.api_name}`}
                checked={current.includes(t.id)}
                onChange={() => setSelected(toggleSelection(current, t.id))}
              />{" "}
              {t.display_name} <span className="slug">{t.api_name}</span>
            </label>
          ))}
        </div>
      )}
      {save.isError && (
        <p className="field-hint" data-testid="group-members-error">
          {save.error instanceof ApiError ? save.error.message : "Could not save."}
        </p>
      )}
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button
          type="button"
          className="btn primary"
          data-testid="group-members-save"
          disabled={!current || save.isPending}
          onClick={() => save.mutate()}
        >
          Save
        </button>
      </div>
    </Dialog>
  );
}

export function ObjectTypeGroupsPanel({
  workspaceId,
  canEdit,
  openId,
  onOpened,
}: {
  workspaceId: string;
  canEdit: boolean;
  /** Open this one as soon as it can be resolved — the ontology search hands
   * over an id, and only this component knows how to turn one into an open
   * dialog. Same contract as the shared properties panel's. */
  openId?: string | null;
  onOpened?: () => void;
}) {
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<ObjectTypeGroup | null>(null);
  const [showingMembers, setShowingMembers] = useState<ObjectTypeGroup | null>(null);
  const queryClient = useQueryClient();

  const groups = useQuery({
    queryKey: ["object-type-groups", workspaceId],
    queryFn: () => objApi.listObjectTypeGroups(workspaceId),
  });

  // Resolved during render rather than in an effect: the id may arrive before
  // the list does, and an effect keyed on `openId` alone would miss the case
  // where the list is what arrives second.
  const requested = openId
    ? (groups.data ?? []).find((g) => g.id === openId) ?? null
    : null;
  if (requested && showingMembers?.id !== requested.id) {
    setShowingMembers(requested);
    onOpened?.();
  }

  const remove = useMutation({
    mutationFn: (id: string) => objApi.deleteObjectTypeGroup(workspaceId, id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["object-type-groups", workspaceId],
      });
      // The classification disappears from p.262's column on every row that
      // carried it, which is the only visible effect of this delete.
      await queryClient.invalidateQueries({ queryKey: ["object-types", workspaceId] });
    },
  });

  return (
    <>
      {creating && (
        <GroupDialog workspaceId={workspaceId} onClose={() => setCreating(false)} />
      )}
      {editing && (
        <GroupDialog
          workspaceId={workspaceId}
          existing={editing}
          onClose={() => setEditing(null)}
        />
      )}
      {showingMembers && (
        <MembersDialog
          workspaceId={workspaceId}
          group={showingMembers}
          onClose={() => setShowingMembers(null)}
        />
      )}

      <div className="page-head" style={{ marginTop: 32 }}>
        <div>
          <h2 style={{ fontSize: 15, margin: 0 }}>Groups</h2>
          <p className="sub">
            A way of finding object types — grouping one does not change it
          </p>
        </div>
        {canEdit && (
          <button
            className="btn quiet"
            data-testid="new-group"
            onClick={() => setCreating(true)}
          >
            New group
          </button>
        )}
      </div>
      {groups.data && groups.data.length === 0 && (
        <p className="login-note">
          No groups yet — worth creating when an ontology has grown past the
          point where one list of object types is a useful list.
        </p>
      )}
      {groups.data && groups.data.length > 0 && (
        <table className="table" style={{ marginBottom: 28 }} data-testid="groups-table">
          <thead>
            <tr>
              <th>Group</th><th>Description</th><th>Contains</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {groups.data.map((g) => (
              <tr key={g.id}>
                <td>
                  <strong>{g.display_name}</strong>
                  <div className="slug">{g.api_name}</div>
                </td>
                <td>{g.description}</td>
                <td>
                  {/* Zero is a number here. p.263 makes a group discoverable
                      whether or not it has members, and the count is how
                      somebody sees that it is empty rather than missing. */}
                  <button
                    className="btn quiet"
                    style={{ padding: "3px 9px", fontSize: 12 }}
                    data-testid={`group-count-${g.api_name}`}
                    aria-label={`Object types in ${g.api_name}`}
                    onClick={() => setShowingMembers(g)}
                  >
                    {memberSummary(g.member_count)}
                  </button>
                </td>
                <td>
                  <div className="row-actions">
                    {canEdit && (
                      <button
                        className="btn quiet"
                        style={{ padding: "3px 9px", fontSize: 12 }}
                        aria-label={`Edit ${g.api_name}`}
                        onClick={() => setEditing(g)}
                      >
                        Edit
                      </button>
                    )}
                    {canEdit && (
                      <button
                        className="btn danger"
                        style={{ padding: "3px 9px", fontSize: 12 }}
                        aria-label={`Delete ${g.api_name}`}
                        disabled={remove.isPending}
                        // A group carries no schema, so this is unusually
                        // benign — and worth saying, because somebody
                        // expecting a cascade would not press it at all.
                        title={
                          g.member_count
                            ? `${memberSummary(g.member_count)} stop being grouped. None is deleted.`
                            : "Nothing is in it"
                        }
                        onClick={() => remove.mutate(g.id)}
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
      )}
    </>
  );
}

/** p.262's filter, above the table of object types. */
export function GroupFilter({
  workspaceId,
  value,
  onChange,
}: {
  workspaceId: string;
  value: string | null;
  onChange: (groupId: string | null) => void;
}) {
  const groups = useQuery({
    queryKey: ["object-type-groups", workspaceId],
    queryFn: () => objApi.listObjectTypeGroups(workspaceId),
  });
  // Nothing to filter by is not a filter. Drawing a one-option dropdown would
  // be offering a control that cannot change anything.
  if (!groups.data || groups.data.length === 0) return null;
  return (
    <select
      data-testid="group-filter"
      aria-label="Filter object types by group"
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
    >
      <option value="">All groups</option>
      {groups.data.map((g) => (
        <option key={g.id} value={g.id}>{g.display_name}</option>
      ))}
    </select>
  );
}

/** The groups an object type is in, on its row (p.262's column). */
export function GroupChips({
  groups,
}: {
  groups: { id: string; display_name: string }[];
}) {
  if (!groups.length) return null;
  return (
    <>
      {groups.map((g) => (
        <span
          key={g.id}
          className="slug"
          data-testid={`group-chip-${g.id}`}
          style={{ marginLeft: 6 }}
        >
          {g.display_name}
        </span>
      ))}
    </>
  );
}
