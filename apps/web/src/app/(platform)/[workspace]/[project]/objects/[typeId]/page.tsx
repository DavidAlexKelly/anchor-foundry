"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { objects as objApi } from "@/lib/api";
import { useWorkspaceBySlug } from "@/components/use-workspace";

const PAGE_SIZE = 50;

export default function ObjectInstancesPage() {
  const params = useParams<{ workspace: string; project: string; typeId: string }>();
  const { workspace } = useWorkspaceBySlug(params.workspace);
  const [page, setPage] = useState(0);

  const type = useQuery({
    queryKey: ["object-type", params.typeId],
    queryFn: () => objApi.getType(workspace!.id, params.typeId),
    enabled: !!workspace,
  });
  const instances = useQuery({
    queryKey: ["object-instances", params.typeId, page],
    queryFn: () => objApi.listInstances(workspace!.id, params.typeId, PAGE_SIZE, page * PAGE_SIZE),
    enabled: !!workspace,
  });

  const properties = type.data?.properties ?? [];
  const rows = instances.data?.items ?? [];
  const total = instances.data?.total ?? 0;
  const hasNext = (page + 1) * PAGE_SIZE < total;

  return (
    <main>
      <div className="page-head">
        <div>
          <p className="eyebrow">project · objects</p>
          <h1>{type.data?.display_name ?? "Instances"}</h1>
        </div>
        <Link href={`/${params.workspace}/${params.project}/objects`} className="btn quiet">
          Back to Objects
        </Link>
      </div>

      {(type.isPending || instances.isPending) && <div className="state">Loading instances…</div>}
      {(type.isError || instances.isError) && (
        <div className="state error">Couldn&apos;t load instances. Refresh to try again.</div>
      )}

      {type.data && instances.data && total === 0 && (
        <div className="empty">
          <h2>No instances yet</h2>
          <p>
            This object type has no materialised instances. Map a dataset to it and sync from
            the Objects page to populate this view.
          </p>
        </div>
      )}

      {type.data && rows.length > 0 && (
        <>
          <p className="sub" style={{ marginBottom: 12 }}>
            {total.toLocaleString()} instance{total === 1 ? "" : "s"}
          </p>
          <div style={{ overflowX: "auto" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Primary key</th>
                  {properties.map((p) => (
                    <th key={p.api_name}>{p.display_name || p.api_name}</th>
                  ))}
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((instance) => (
                  <tr key={instance.id}>
                    <td className="slug">{instance.primary_key}</td>
                    {properties.map((p) => (
                      <td key={p.api_name}>
                        {instance.properties[p.api_name] === null ||
                        instance.properties[p.api_name] === undefined
                          ? <span style={{ color: "var(--ink-soft)" }}>—</span>
                          : String(instance.properties[p.api_name])}
                      </td>
                    ))}
                    <td className="count">{new Date(instance.updated_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row-actions" style={{ marginTop: 14, justifyContent: "flex-end" }}>
            <button
              className="btn quiet"
              style={{ padding: "4px 12px", fontSize: 12.5 }}
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              Previous
            </button>
            <span className="count">
              {page * PAGE_SIZE + 1}–{Math.min(total, (page + 1) * PAGE_SIZE)} of {total}
            </span>
            <button
              className="btn quiet"
              style={{ padding: "4px 12px", fontSize: 12.5 }}
              disabled={!hasNext}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </main>
  );
}
