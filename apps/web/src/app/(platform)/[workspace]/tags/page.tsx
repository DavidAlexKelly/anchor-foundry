"use client";

/**
 * The workspace's tags (§511; `app-building` p.35, `getting-started` p.66).
 *
 * > "You can create and manage tags from the Tags section of Platform
 * > Settings. Once they are created, they can be added … in the filesystem."
 * > (p.35)
 *
 * Everybody in the workspace sees the tags and how widely each is used; only
 * an admin is offered the form, because only an admin's request would
 * succeed (§214). Tags are applied on each resource's Details.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { useWorkspaceBySlug } from "@/components/use-workspace";
import { ApiError, resourceTags } from "@/lib/api";
import { byCategory, usesText } from "@/lib/resource-tags";

export default function TagsPage() {
  const params = useParams<{ workspace: string }>();
  const { workspace, isPending, notFound } = useWorkspaceBySlug(params.workspace);
  const queryClient = useQueryClient();
  const [category, setCategory] = useState("");
  const [name, setName] = useState("");
  const wid = workspace?.id ?? "";
  const list = useQuery({
    queryKey: ["resource-tags", wid],
    queryFn: () => resourceTags.list(wid),
    enabled: !!workspace,
  });
  const create = useMutation({
    mutationFn: () => resourceTags.create(wid, { category, name }),
    onSuccess: async () => {
      setName("");
      await queryClient.invalidateQueries({ queryKey: ["resource-tags", wid] });
    },
  });
  const remove = useMutation({
    mutationFn: (tid: string) => resourceTags.remove(wid, tid),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["resource-tags", wid] }),
  });

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
  const admin = workspace.effective_role === "admin";
  const failure = create.error ?? remove.error;

  return (
    <main className="page">
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link href="/home">Workspaces</Link>
        <span className="link-mark" />
        <Link href={`/${params.workspace}`}>{workspace.name}</Link>
        <span className="link-mark" />
        <span className="current">Tags</span>
      </nav>
      <div className="page-head">
        <div>
          <p className="eyebrow">workspace</p>
          <h1>Tags</h1>
          <p className="sub">
            Labels for this workspace&apos;s resources, grouped by category. A
            tag is added to a resource from its Details.
          </p>
        </div>
      </div>

      {admin ? (
        <form
          className="ds-parse-grid"
          data-testid="tag-form"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <label>
            Category
            <input
              data-testid="tag-category"
              value={category}
              placeholder="none"
              maxLength={100}
              onChange={(e) => setCategory(e.target.value)}
            />
          </label>
          <label>
            Name
            <input
              data-testid="tag-name"
              value={name}
              maxLength={100}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <button className="btn" type="submit" data-testid="tag-create" disabled={!name.trim()}>
            Create tag
          </button>
        </form>
      ) : (
        <p className="login-note" data-testid="tags-read-only">
          Making and deleting tags is a workspace admin&apos;s job.
        </p>
      )}
      {failure && (
        <div className="form-error" data-testid="tag-error">
          {failure instanceof ApiError ? failure.message : "Couldn't change the tags."}
        </div>
      )}

      {list.data?.length === 0 && (
        <p className="soft" data-testid="no-tags">This workspace has no tags yet.</p>
      )}
      {list.data && byCategory(list.data).map((group) => (
        <section key={group.category} data-testid="tag-group">
          <h2 className="ds-h2">{group.category || "No category"}</h2>
          <ul className="ds-health">
            {group.tags.map((tag) => (
              <li key={tag.id} data-testid="tag-row">
                <strong>{tag.name}</strong>{" "}
                <span className="soft">{usesText(tag.uses)}</span>
                {admin && (
                  <button
                    type="button"
                    className="btn quiet"
                    data-testid="tag-delete"
                    style={{ marginLeft: 8 }}
                    onClick={() => remove.mutate(tag.id)}
                  >
                    Delete
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </main>
  );
}
