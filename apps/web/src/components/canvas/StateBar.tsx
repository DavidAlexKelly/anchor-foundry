"use client";

/** Saving, opening and sharing a module state (p.200–206).
 *
 * > "State saving … allows module consumers to store the current state of
 * > their work within a module and then either return to that saved state or
 * > share the saved state with other users." (p.200)
 *
 * **A reader's control, not an author's.** It appears in View mode only, and
 * only when the module says it saves state — p.206 makes both conditions
 * explicit, and the second is why an unconfigured module shows nothing at all
 * rather than an empty dropdown.
 *
 * **The wording comes from the module** (p.204's "State display name"), so an
 * application whose readers call a saved view an *inbox* says inbox
 * throughout. Nothing here reads those strings for meaning.
 *
 * **Opening a state writes the values and nothing else.** The module resolves
 * them exactly as it resolves a filter somebody typed — no separate restore
 * path, so a state cannot show something a live interaction could not.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { canvas as canvasApi, ApiError } from "@/lib/api";
import type { WorkshopModule } from "@/lib/types";
import { useCanvasPage, useCanvasParameters } from "./context";
import { pageIdOf, pageNodeFor, defaultPageNode } from "./routing";

type Settings = NonNullable<WorkshopModule["state_saving"]>;

export function StateBar({
  workspaceId,
  projectId,
  appId,
  published,
  layout,
  settings,
}: {
  workspaceId: string;
  projectId: string;
  appId: string;
  published: boolean;
  layout: unknown;
  settings: Settings;
}) {
  const { values, set } = useCanvasParameters();
  const { current, go } = useCanvasPage();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const one = settings.display_name || "module state";
  const many = settings.display_name_plural || "module states";
  const key = ["module-states", appId, published];

  const states = useQuery({
    queryKey: key,
    queryFn: () => canvasApi.listStates(workspaceId, projectId, appId, published),
  });

  const save = useMutation({
    mutationFn: (stateName: string) =>
      canvasApi.saveState(
        workspaceId, projectId, appId,
        {
          name: stateName,
          values,
          // The page the reader is *looking at*, which before any navigation
          // is the first one — the same rule routing follows, so a state and a
          // link agree about where somebody was.
          page_id: pageIdOf(layout, current ?? defaultPageNode(layout)),
        },
        published,
      ),
    onSuccess: async (saved) => {
      setFailure(null);
      setName("");
      setNote(`Saved “${saved.name}”.`);
      await queryClient.invalidateQueries({ queryKey: key });
    },
    // The server's own sentence: "…is somebody else's saved state" tells a
    // reader what to do about it, where "couldn't save" does not.
    onError: (e: Error) =>
      setFailure(e instanceof ApiError ? e.message : `Couldn't save this ${one}.`),
  });

  const open = useMutation({
    mutationFn: (stateId: string) =>
      canvasApi.openState(workspaceId, projectId, appId, stateId, published),
    onSuccess: (state) => {
      setFailure(null);
      for (const [variableId, value] of Object.entries(state.values)) {
        set(variableId, value);
      }
      if (state.page_id) {
        const node = pageNodeFor(layout, state.page_id);
        if (node) go(node);
      }
      // **Said, not hidden.** p.203 warns a state can "reload unsuccessfully"
      // when an external ID moves; a view that came back short must say which
      // part is missing, or the reader believes they are looking at what they
      // saved.
      setNote(
        state.missing.length > 0
          ? `Opened “${state.name}”. ${state.missing.length} saved ` +
            `${state.missing.length === 1 ? "value" : "values"} no longer ` +
            `${state.missing.length === 1 ? "applies" : "apply"} ` +
            `to this module (${state.missing.join(", ")}).`
          : `Opened “${state.name}”.`,
      );
    },
    onError: (e: Error) =>
      setFailure(e instanceof ApiError ? e.message : `Couldn't open this ${one}.`),
  });

  const remove = useMutation({
    mutationFn: (stateId: string) =>
      canvasApi.deleteState(workspaceId, projectId, appId, stateId, published),
    onSuccess: async () => {
      setFailure(null);
      setNote(null);
      await queryClient.invalidateQueries({ queryKey: key });
    },
    onError: (e: Error) =>
      setFailure(e instanceof ApiError ? e.message : `Couldn't delete this ${one}.`),
  });

  return (
    <div className="canvas-state-bar" data-testid="state-bar">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) save.mutate(name.trim());
        }}
      >
        <label className="field">
          <span className="field-label">Save this as a {one}</span>
          <input
            value={name}
            placeholder={`Name this ${one}`}
            aria-label={`Name this ${one}`}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <button type="submit" className="btn quiet" disabled={!name.trim() || save.isPending}>
          Save
        </button>
      </form>

      {(states.data ?? []).length > 0 && (
        <ul className="canvas-state-list">
          {(states.data ?? []).map((state) => (
            <li key={state.id}>
              <button
                type="button"
                className="btn quiet"
                onClick={() => open.mutate(state.id)}
              >
                {state.name}
              </button>
              {/* Whose it is, because a shared state and your own are deleted
                  by different people and the refusal would otherwise arrive as
                  a surprise. */}
              <span className="slug">{state.created_by_name ?? "somebody"}</span>
              <button
                type="button"
                className="btn danger"
                aria-label={`Delete ${state.name}`}
                onClick={() => remove.mutate(state.id)}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
      {states.data?.length === 0 && (
        <p className="canvas-widget-empty">No saved {many} yet.</p>
      )}
      {note && <p className="canvas-widget-empty" data-testid="state-note">{note}</p>}
      {failure && (
        <p className="state error" data-testid="state-failure">
          {failure}
        </p>
      )}
    </div>
  );
}
