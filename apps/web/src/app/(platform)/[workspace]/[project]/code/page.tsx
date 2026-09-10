"use client";

/**
 * The Code pillar: this project's repositories (§291).
 *
 * **This file used to be a second transform editor**, and `code-repositories.md`
 * opened by asking for it to be deleted — "463 lines duplicating this, worse".
 * §278 found that was only true of the editor half: five capabilities lived
 * here and nowhere else, and the page could not go until each had a home.
 * §279 took the review gate, §280 the change history, §289 succeeded the change
 * set with a commit, and §290 gave the typed-changes proposals a home beside
 * the transforms they change. This is the deletion.
 *
 * **And the deletion exposed a hole.** The old file opened with *"There is no
 * 'new repository' button, and its absence is the design"* — true when decision
 * 0001 made the pillar a view over `model_versions`, and false since §94 gave
 * the project real `code_repos`. Nothing in `apps/web` called
 * `POST /repositories`: every repository in the product had been made by a
 * script, none could be listed anywhere, and the repository application was
 * reachable only by a `/r/{id}` link somebody already had. §275's adopt dialog
 * had already been caught by it, telling people to "create one on the Code
 * screen" — a screen with no such control. So the pillar becomes what it should
 * have been: the repositories, each opening into the application.
 *
 * The rules for what to *offer* are in `lib/repository-list.ts`; the server
 * owns every refusal (`routes/repositories.py`).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, repositories as repoApi } from "@/lib/api";
import { Dialog, Field } from "@/components/dialog";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";
import { canCreate, emptyReason, openHref, subtitle } from "@/lib/repository-list";

function NewRepository({
  workspaceId,
  projectId,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  onClose: () => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const create = useMutation({
    mutationFn: () =>
      repoApi.create(workspaceId, projectId, { name, description }),
    onSuccess: async (made) => {
      await queryClient.invalidateQueries({ queryKey: ["repositories", projectId] });
      // **Straight into it.** A repository with no files is not something to
      // admire in a list; the next thing anybody does is put code in it, and
      // that is the application's Files tab.
      router.push(openHref(made));
    },
  });

  return (
    <Dialog open title="New repository" onClose={onClose}>
      <p className="login-note" style={{ marginTop: 0 }}>
        A repository holds transforms as files, with branches, review and a
        history of who changed what. Move a transform into one from the Models
        screen, or write a new file here.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <Field label="Name">
          <input
            type="text"
            value={name}
            data-testid="repository-name"
            onChange={(e) => setName(e.target.value)}
            required
            autoFocus
          />
        </Field>
        <Field label="Description" hint="Optional.">
          <input
            type="text"
            value={description}
            data-testid="repository-description"
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        {create.isError && (
          <p className="state error" data-testid="repository-error">
            {create.error instanceof ApiError
              ? create.error.message
              : (create.error as Error).message}
          </p>
        )}
        <div className="row-actions" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn quiet" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn"
            data-testid="repository-create"
            disabled={create.isPending}
          >
            {create.isPending ? "Creating…" : "Create repository"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

export default function CodePage() {
  const params = useParams<{ workspace: string; project: string }>();
  const { workspace } = useWorkspaceBySlug(params.workspace);
  const { project } = useProjectBySlug(workspace?.id, params.project);
  const [creating, setCreating] = useState(false);

  const ready = !!workspace && !!project;
  const list = useQuery({
    queryKey: ["repositories", project?.id],
    queryFn: () => repoApi.list(workspace!.id, project!.id),
    enabled: ready,
  });

  const role = project?.effective_role ?? "viewer";
  const repositories = list.data ?? [];
  const empty = list.isSuccess ? emptyReason(repositories.length, role) : null;

  return (
    <main>
      <div className="page-head">
        <div>
          <p className="eyebrow">project · code</p>
          <h1>Code</h1>
          <p className="sub">
            This project&apos;s repositories. Each one opens into the editor,
            with branches, review and history over the transforms it holds.
          </p>
        </div>
        <div className="row-actions">
          {/* Not disabled for a viewer, absent: `POST /repositories` is
              editor-level, and a control that looks like it works is worse
              than one that is not there (§214). The empty state says why. */}
          {canCreate(role) && (
            <button
              type="button"
              className="btn"
              data-testid="repository-new"
              onClick={() => setCreating(true)}
            >
              New repository
            </button>
          )}
        </div>
      </div>

      {list.isPending && <div className="state">Loading…</div>}
      {list.isError && (
        <div className="state error">Couldn&apos;t load this project&apos;s repositories.</div>
      )}

      <div data-testid="repository-list">
        {empty && (
          <div className="empty">
            <h2>No repositories yet</h2>
            <p data-testid="repository-empty">{empty}</p>
          </div>
        )}
        {repositories.length > 0 && (
          <ul className="code-log">
            {repositories.map((r) => (
              <li key={r.id}>
                {/* By resource id, never a slug path: a link built from a
                    workspace and project slug stops working the moment
                    somebody renames either, which is exactly when a shared
                    link is most likely to be clicked. */}
                <Link className="code-log-entry" href={openHref(r)}>
                  <span className="code-log-summary">{r.name}</span>
                  <span className="code-log-meta">{subtitle(r)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>

      {creating && workspace && project && (
        <NewRepository
          workspaceId={workspace.id}
          projectId={project.id}
          onClose={() => setCreating(false)}
        />
      )}
    </main>
  );
}
