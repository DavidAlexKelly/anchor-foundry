"use client";

/** The chrome every resource application shares (ROADMAP.md phase 2, section
 * 0 item 3): a breadcrumb back to where the resource lives, its name and kind,
 * and a slot for whatever that application needs in its toolbar.
 *
 * It is thin on purpose. Everything an application actually does belongs to
 * the application; what belongs here is the small set of things that must look
 * and behave the same in all of them, because a person with six tabs open
 * needs to know where they are without reading carefully.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { kindLabel } from "@/components/resource-browser";
import { CopyLinkButton } from "@/components/use-url-state";
import { ApiError, resourceFavourites } from "@/lib/api";
import { canShowStar, starGlyph, starLabel } from "@/lib/favourites";
import type { ResolvedResource } from "@/lib/types";

export function ApplicationShell({
  resource,
  toolbar,
  children,
}: {
  resource: ResolvedResource;
  toolbar?: React.ReactNode;
  children: React.ReactNode;
}) {
  // Workspace-level resources have no project to go back to; the breadcrumb
  // stops at the workspace rather than inventing a parent for them.
  const projectHref = resource.project_slug
    ? `/${resource.workspace_slug}/${resource.project_slug}`
    : null;

  return (
    <div className="app-shell">
      <header className="app-bar">
        <nav className="app-crumbs" aria-label="Breadcrumb">
          <Link href={`/${resource.workspace_slug}`}>{resource.workspace_name}</Link>
          {projectHref && (
            <>
              <span className="link-mark" />
              <Link href={projectHref}>{resource.project_name}</Link>
            </>
          )}
        </nav>
        <div className="app-title">
          <h1>{resource.name}</h1>
          <span className="chip">{kindLabel(resource.kind)}</span>
          {resource.trashed && <span className="chip warn">in trash</span>}
        </div>
        <div className="spacer" />
        {/* Every application, not each one separately (item 0.4). The state
            worth sharing is already in the query string, so the affordance
            that shares it belongs where the chrome is. */}
        <div className="app-toolbar">
          {toolbar}
          {/* p.34's "from within an open resource" (§436). Here rather than in
              each application, for the same reason `CopyLinkButton` is: the
              thing being starred is the resource, which every application
              shares and none of them owns. */}
          <FavouriteStar resource={resource} />
          <CopyLinkButton />
        </div>
      </header>
      <div className="app-body">{children}</div>
    </div>
  );
}

/** What an application renders before its own surface exists.
 *
 * Not a placeholder for the *shell* - resolution, breadcrumbs and the tab all
 * work, and the link is already the stable one that survives a rename. It is
 * the honest state of a resource whose dedicated application is a later
 * roadmap item, and it says which one rather than "coming soon".
 */
export function ResourceSummary({
  resource,
  buildingIn,
  existingHref,
  existingLabel,
}: {
  resource: ResolvedResource;
  buildingIn: string;
  existingHref: string | null;
  existingLabel: string;
}) {
  return (
    <div className="app-summary">
      {resource.description && <p className="sub">{resource.description}</p>}
      <dl className="app-facts">
        <div>
          <dt>Type</dt>
          <dd>{kindLabel(resource.kind)}</dd>
        </div>
        <div>
          <dt>Last changed</dt>
          <dd>{new Date(resource.updated_at).toLocaleString()}</dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{new Date(resource.created_at).toLocaleString()}</dd>
        </div>
      </dl>
      {existingHref && (
        <p className="app-elsewhere">
          <Link href={existingHref}>{existingLabel}</Link>
        </p>
      )}
      <p className="soft app-pending">
        A dedicated application for this resource type is {buildingIn}.
      </p>
    </div>
  );
}


/**
 * The star that keeps a shortcut to this resource (§436; `getting-started`
 * p.34).
 *
 * **Absent until the answer is known**, which is §312's rule and matters more
 * here: an unfilled star means "not a favourite", so drawing one before the
 * server has said would tell somebody their shortcut is gone — and the press
 * that follows would remove a favourite they still had.
 *
 * **Exported, because a second surface offers it** (§437): p.47 lets a
 * Workshop module offer the same star to viewers of the published module, and
 * that route draws its own chrome rather than this shell's. One
 * implementation, imported by both — a copy there would be a second star with
 * its own idea of when to invalidate the list it writes into (§292).
 */
export function FavouriteStar({ resource }: { resource: ResolvedResource }) {
  const client = useQueryClient();
  const known = useQuery({
    queryKey: ["resource-favourite", resource.id],
    queryFn: () => resourceFavourites.starred(resource.workspace_id, resource.id),
  });
  const [failure, setFailure] = useState<string | null>(null);

  const isFavourite = known.data?.favourite ?? false;
  const toggle = useMutation({
    mutationFn: async () => {
      if (isFavourite) await resourceFavourites.remove(resource.workspace_id, resource.id);
      else await resourceFavourites.add(resource.workspace_id, resource.id, resource.name);
    },
    onSuccess: async () => {
      setFailure(null);
      await client.invalidateQueries({ queryKey: ["resource-favourite", resource.id] });
      // The list that holds it is the workspace's, and it is on another screen.
      await client.invalidateQueries({ queryKey: ["object-favourites", resource.workspace_id] });
    },
    // **The cap's refusal is shown rather than swallowed.** A star that did
    // nothing and said nothing is the control §214 is about.
    onError: (e: Error) => setFailure(e instanceof ApiError ? e.message : "Couldn't."),
  });

  if (!canShowStar(known.isSuccess)) return null;

  return (
    <>
      <button
        type="button"
        className={`btn quiet app-star${isFavourite ? " on" : ""}`}
        data-testid="resource-favourite"
        data-favourite={isFavourite}
        aria-label={starLabel(isFavourite)}
        title={starLabel(isFavourite)}
        disabled={toggle.isPending}
        onClick={() => toggle.mutate()}
      >
        {starGlyph(isFavourite)}
      </button>
      {failure && (
        <span className="form-error app-star-error" data-testid="resource-favourite-error">
          {failure}
        </span>
      )}
    </>
  );
}