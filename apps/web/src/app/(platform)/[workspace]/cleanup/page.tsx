"use client";

/**
 * p.68's Ontology cleanup tool, as a destination (§325).
 *
 * > "The view can be accessed from the home page of the Ontology cleanup
 * > tool." (p.68)
 *
 * Workspace-scoped, like the ontology it is about — object types are
 * workspace-wide (db 0003), so a cleanup queue reached through a project would
 * be listing types that project does not own. Same argument that moved the
 * Object Explorer here.
 *
 * **Editors only, and it says so rather than showing an empty page.** Every
 * other workspace screen is readable by a viewer because it says what the
 * ontology *is*; this one says which types somebody should consider deleting,
 * and p.71's three buttons are all writes. The server refuses a viewer outright
 * (§325), so a viewer who followed a link would otherwise meet a red error
 * where a sentence would do.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { CleanupQueue } from "@/components/cleanup-queue";
import { useWorkspaceBySlug } from "@/components/use-workspace";

export default function CleanupPage() {
  const params = useParams<{ workspace: string }>();
  const { workspace, isPending, notFound } = useWorkspaceBySlug(params.workspace);

  if (isPending) return <main className="page"><div className="state">Loading…</div></main>;
  if (notFound || !workspace) {
    return (
      <main className="page">
        <div className="state error">
          This workspace doesn&apos;t exist or you don&apos;t have access to it.
        </div>
      </main>
    );
  }

  return (
    <main className="page">
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link href="/home">Workspaces</Link>
        <span className="link-mark" />
        <Link href={`/${params.workspace}`}>{workspace.name}</Link>
        <span className="link-mark" />
        <span className="current">Cleanup</span>
      </nav>
      <div className="page-head">
        <div>
          <p className="eyebrow">workspace</p>
          <h1>Ontology cleanup</h1>
          <p className="sub">
            Object types worth a second look, worst first. Nothing here is
            deleted until you say so.
          </p>
        </div>
      </div>

      {workspace.effective_role === "viewer" ? (
        <p className="login-note" data-testid="cleanup-read-only">
          Cleaning up the ontology is an editor&apos;s job — this page would
          only offer you buttons you cannot press.
        </p>
      ) : (
        <CleanupQueue workspaceId={workspace.id} workspaceSlug={params.workspace} />
      )}
    </main>
  );
}
