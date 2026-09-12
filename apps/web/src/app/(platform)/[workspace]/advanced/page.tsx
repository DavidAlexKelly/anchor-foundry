"use client";

/**
 * p.66's Advanced settings page (§327).
 *
 * > "You can export your Ontology working state by selecting the **Advanced
 * > settings** page from the application's home page and then selecting
 * > Export." (p.66)
 *
 * Workspace-scoped, like the ontology it transfers — and a destination of its
 * own rather than a panel on the workspace page, because p.66 names it as a
 * page and because everything on it rewrites the whole ontology at once.
 *
 * **Editors only, and it says why.** The server refuses a viewer outright
 * (§326), so a viewer following a link would otherwise meet a red error where
 * a sentence would do — the same reasoning as §325's cleanup page.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { OntologyTransfer } from "@/components/ontology-transfer";
import { useWorkspaceBySlug } from "@/components/use-workspace";

export default function AdvancedSettingsPage() {
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
        <span className="current">Advanced</span>
      </nav>
      <div className="page-head">
        <div>
          <p className="eyebrow">workspace</p>
          <h1>Advanced settings</h1>
          <p className="sub">
            Move this workspace&apos;s ontology in and out as a JSON file.
          </p>
        </div>
      </div>

      {workspace.effective_role === "viewer" ? (
        <p className="login-note" data-testid="advanced-read-only">
          Exporting and importing an ontology is an editor&apos;s job — this
          page would only offer you buttons you cannot press.
        </p>
      ) : (
        <OntologyTransfer
          workspaceId={workspace.id}
          workspaceSlug={params.workspace}
        />
      )}
    </main>
  );
}
