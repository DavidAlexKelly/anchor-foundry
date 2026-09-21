"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { ApiError, models as modelApi } from "@/lib/api";
import { PipelineGraphView } from "@/components/pipeline-graph";
import { Dialog, Field } from "@/components/dialog";
import { nodePath, type GraphView } from "@/lib/pipeline-graph";
import { fromParams, toParams } from "@/lib/graph-link";
import { CopyLinkButton, useUrlState } from "@/components/use-url-state";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";
import type { PipelineGraph, PipelineNode, SavedGraph } from "@/lib/types";

export default function PipelinePage() {
  const params = useParams<{ workspace: string; project: string }>();
  const router = useRouter();
  const url = useUrlState();
  const { workspace } = useWorkspaceBySlug(params.workspace);
  const { project } = useProjectBySlug(workspace?.id, params.project);
  const [saving, setSaving] = useState(false);
  const [opening, setOpening] = useState(false);

  // p.82's *View as* (§422). Part of the query key, so choosing somebody
  // fetches the graph with their access on it rather than colouring the copy
  // already in hand — the answer is the server's, and a client that worked it
  // out from roles it happened to know would be a second permissions model.
  const [viewAs, setViewAs] = useState<string | null>(null);
  const graph = useQuery<PipelineGraph>({
    queryKey: ["pipeline", project?.id, viewAs],
    queryFn: () => modelApi.pipeline(workspace!.id, project!.id, undefined, viewAs),
    enabled: !!workspace && !!project,
    // **Keep the graph on the screen while the next one is fetched.** Without
    // this, naming somebody under *View as* changes the query key, `data`
    // goes undefined for a moment, and the whole graph unmounts and remounts
    // with fresh state — which lost the Permissions colouring that is the
    // only reason the picker was on the screen, and put the reader back on
    // Build status one click after they asked a permissions question. A
    // browser test found it; nothing else could have.
    placeholderData: (previous) => previous,
  });
  // Who may be named. Fetched once for the page rather than with each graph,
  // and **only here**, of the places this graph is drawn: the endpoint is
  // editor-gated, so a surface whose readers may be viewers must not ask.
  const viewers = useQuery({
    queryKey: ["pipeline-viewers", project?.id],
    queryFn: () => modelApi.pipelineViewers(workspace!.id, project!.id),
    enabled: !!workspace && !!project,
    // A viewer gets a 403 here and that is the correct answer, not a fault to
    // retry — the control simply is not drawn for them.
    retry: false,
  });

  // p.9's builds helper (§386). **One at a time, in the order the plan gives
  // them** — `buildPlan` sorts by the `layer` the server computed, and the
  // order is the point: a transform reads its inputs' *current* versions, so
  // firing an ancestor and its descendant together would have the descendant
  // read the version the ancestor is in the middle of replacing. Awaiting each
  // is what makes "build these and their ancestors" mean what it says.
  //
  // **A refusal stops the run rather than being collected.** `run_model`
  // refuses a model with no code or no inputs, and carrying on past one would
  // build the rest of a chain on an input that never got rebuilt — the wrong
  // answer, arrived at more thoroughly. The error names which transform.
  const build = useMutation({
    mutationFn: async (models: { id: string; name: string }[]) => {
      for (const model of models) {
        try {
          await modelApi.run(workspace!.id, project!.id, model.id);
        } catch (error) {
          throw new Error(
            `${model.name}: ${error instanceof ApiError ? error.message : String(error)}`,
          );
        }
      }
    },
    onSuccess: () => graph.refetch(),
  });

  // p.10's schedules helper (§387). **One at a time like the build**, but for
  // a different reason: a schedule write is small and independent, so the
  // order does not matter — what matters is that a refusal names the model it
  // came from rather than arriving as one failure for a batch.
  //
  // **`null` clears**, which is p.10's "edit" including turning a schedule
  // off: `trigger_mode` back to `manual`.
  //
  // **The expression going with it is the server's doing, not this line's.**
  // A sweep put that right: mutating `cron_schedule` here changed nothing,
  // because `models.update`'s SQL reads `WHEN :trigger IS NOT NULL THEN NULL`
  // — any change of trigger mode clears the schedule, and it has to, or a
  // model switched to manual would keep an expression nobody can see. The
  // field is still sent because one object serves both branches, but the
  // guarantee is the server's and the comment used to claim it for this.
  const schedule = useMutation({
    mutationFn: async (
      { models, cron }: { models: { id: string; name: string }[]; cron: string | null },
    ) => {
      for (const model of models) {
        try {
          await modelApi.update(workspace!.id, project!.id, model.id, {
            trigger_mode: cron === null ? "manual" : "cron",
            cron_schedule: cron,
          });
        } catch (error) {
          throw new Error(
            `${model.name}: ${error instanceof ApiError ? error.message : String(error)}`,
          );
        }
      }
    },
    onSuccess: () => graph.refetch(),
  });

  // **The view arrives from the URL, and is read once.** p.12's "quick share
  // link" is a link, so the parameters have to be *in* one — and putting them
  // there fixes reload-loses-everything as a side effect, which this page had
  // since it was written.
  //
  // Initialised once rather than read every render: re-reading would fight the
  // graph for control of its own selection the moment somebody clicked, since
  // the URL is written *from* the graph a beat later.
  const [opened, setOpened] = useState<GraphView>(() => fromParams(url.params));
  // Bumped when a saved graph is opened, which remounts the graph so it reads
  // the new view as its initial one. A remount rather than a reload: a
  // `router.replace` has not landed by the time `location.reload()` would
  // fire, so reloading would race the URL it is meant to be applying.
  const [openedKey, setOpenedKey] = useState(0);

  // The view as it stands, for Save. A ref because nothing on this page needs
  // to re-render when it changes — the graph is already drawing it.
  const live = useRef<GraphView>(opened);

  function open(node: PipelineNode) {
    // One rule for the three graphs that draw these nodes — see
    // `lib/pipeline-graph`, which is where an object type learned to open
    // into the Ontology Manager (§351; p.32).
    router.push(nodePath(node, params.workspace, params.project));
  }

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">project · pipeline</p>
          <h1>Pipeline</h1>
          <p className="sub">
            Every dataset and model in this project, flowing left to right.
          </p>
        </div>
        {graph.data && (
          <div className="form-actions" style={{ marginTop: 0 }}>
            {/* p.12's "quick share link", and **not a new button**: this one
                copies the address bar, which is true because the view is kept
                there. A second button rebuilding the link from state could
                disagree with the URL — its own docstring says so. */}
            <CopyLinkButton label="Copy link to this view" />
            <button
              className="btn quiet"
              data-testid="graph-open"
              onClick={() => setOpening(true)}
            >
              Open graph
            </button>
            <button
              className="btn"
              data-testid="graph-save"
              onClick={() => setSaving(true)}
            >
              Save graph
            </button>
          </div>
        )}
      </div>

      {graph.isPending && <div className="state">Loading the pipeline…</div>}
      {graph.isError && <div className="state error">Couldn&apos;t load the pipeline.</div>}
      {/* **A refused build has to land somewhere.** The button is at the
          bottom of the graph and this is at the top, which is the one thing
          worth saying about the placement: the message names the transform
          that refused, so it is readable without hunting for which of six
          builds stopped (§386, §214). */}
      {build.isError && (
        <div className="state error" data-testid="pipeline-build-error">
          {(build.error as Error).message}
        </div>
      )}
      {/* The server owns whether a cron expression means anything —
          `lib/cron.py` parses it with `croniter` and refuses it by name — so
          its refusal is shown as it came rather than restated here (§387). */}
      {schedule.isError && (
        <div className="state error" data-testid="pipeline-schedule-error">
          {(schedule.error as Error).message}
        </div>
      )}
      {graph.data && (
        <PipelineGraphView
          key={openedKey}
          graph={graph.data}
          onOpen={open}
          // Only here, of the four places this graph is drawn: a review
          // surface and a dataset application are views of somebody's work,
          // and the project's own pipeline page is where work starts (§386).
          onBuild={(models) => build.mutate(models)}
          building={build.isPending}
          onSchedule={(models, cron) => schedule.mutate({ models, cron })}
          scheduling={schedule.isPending}
          exportTitle={project?.name}
          viewers={viewers.data}
          viewAs={viewAs}
          // Passed only when the list came back: a picker with nobody on it
          // would be a control that cannot do what it says (§214), which is
          // exactly a viewer's case here.
          onViewAs={viewers.data ? setViewAs : undefined}
          initialView={opened}
          onViewChange={(view) => {
            live.current = view;
            // The URL follows the view, so the link is already right when
            // somebody presses Copy. `set` removes the keys a view has
            // stopped carrying rather than leaving them blank.
            url.set(toParams(view));
          }}
        />
      )}

      {saving && workspace && project && (
        <SaveGraphDialog
          workspaceId={workspace.id}
          projectId={project.id}
          view={live.current}
          onClose={() => setSaving(false)}
        />
      )}
      {opening && workspace && project && (
        <OpenGraphDialog
          workspaceId={workspace.id}
          projectId={project.id}
          onOpen={(saved) => {
            // **The graph only, and the URL follows from it.** The address bar
            // has to say what is being looked at — that is what makes the copy
            // button honest — but writing it here as well would be a second
            // copy of the same fact: the remounted graph reports its view on
            // its first effect, and that report is what writes the URL.
            //
            // Found by mutation rather than by reading: a build with the write
            // here removed passed every test, including the one that asserts
            // the address bar right after Open (§213). The report is also the
            // *better* of the two, because it writes the view the graph could
            // actually draw — `kindsIn` drops a kind this build does not have,
            // and the copy taken from the stored view would have put it in the
            // link anyway.
            setOpened(saved.view);
            setOpenedKey((k) => k + 1);
            setOpening(false);
          }}
          onClose={() => setOpening(false)}
        />
      )}
    </>
  );
}

/** p.12's **Save**. The name is the whole form: the view is whatever is on the
 *  screen, which is the point of a save button rather than a builder. */
function SaveGraphDialog({
  workspaceId,
  projectId,
  view,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  view: GraphView;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: () => modelApi.saveGraph(workspaceId, projectId, { name, view }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["saved-graphs", projectId] });
      onClose();
    },
  });

  return (
    <Dialog open title="Save graph" onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <p className="login-note" style={{ marginTop: 0 }}>
          Saves what you are looking at — the focus, the highlighted column, the
          selection and the search — not the nodes themselves. The pipeline
          keeps changing; the question does not.
        </p>
        <Field label="Name">
          <input
            type="text"
            data-testid="graph-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={200}
          />
        </Field>
        {save.isError && (
          <div className="form-error" data-testid="graph-save-error">
            {save.error instanceof ApiError ? save.error.message : "Couldn't save."}
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn quiet" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn" disabled={save.isPending}>
            Save
          </button>
        </div>
      </form>
    </Dialog>
  );
}

/** p.12's **Open graph**. Shared within the project, following db 0040. */
function OpenGraphDialog({
  workspaceId,
  projectId,
  onOpen,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  onOpen: (saved: SavedGraph) => void;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const saved = useQuery({
    queryKey: ["saved-graphs", projectId],
    queryFn: () => modelApi.savedGraphs(workspaceId, projectId),
  });
  const remove = useMutation({
    mutationFn: (id: string) => modelApi.deleteSavedGraph(workspaceId, projectId, id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["saved-graphs", projectId] }),
  });

  return (
    <Dialog open title="Open graph" onClose={onClose}>
      {saved.isPending && <div className="state">Loading…</div>}
      {saved.data?.length === 0 && (
        <div className="state" data-testid="no-saved-graphs">
          Nothing saved yet. Set the graph up the way you want it and press Save
          graph.
        </div>
      )}
      {saved.data && saved.data.length > 0 && (
        <div className="data-grid">
          <table>
            <tbody>
              {saved.data.map((g) => (
                <tr key={g.id} data-testid="saved-graph" data-name={g.name}>
                  <td>{g.name}</td>
                  <td style={{ textAlign: "right" }}>
                    <button
                      className="btn quiet"
                      data-testid="open-saved-graph"
                      onClick={() => onOpen(g)}
                    >
                      Open
                    </button>
                    <button
                      className="btn quiet"
                      data-testid="delete-saved-graph"
                      onClick={() => remove.mutate(g.id)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="form-actions">
        <button type="button" className="btn quiet" onClick={onClose}>
          Close
        </button>
      </div>
    </Dialog>
  );
}
