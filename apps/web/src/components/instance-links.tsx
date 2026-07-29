"use client";

/**
 * The link explorer (ROADMAP Objects item 3): browse one instance's
 * relationships and walk from there to another object's relationships.
 *
 * Why a dialog with an internal trail rather than a route per instance: the
 * point of traversal is that you keep going - Ada → Engineering → Alan →
 * Ada's team - and each hop is a *lateral* move between object types, not a
 * descent into a hierarchy. A route per instance would put every hop in the
 * browser's history and lose the trail you came by, which is the one piece of
 * context that makes the walk legible. The trail is kept explicitly and shown
 * as breadcrumbs, so any earlier hop is one click away.
 *
 * Nothing is refetched to move a hop: a link group already carries the far
 * instances in full (key + properties), so clicking one re-targets the panel
 * from data in hand, and only the *next* set of links is fetched.
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Dialog } from "@/components/dialog";
import { objects as objApi } from "@/lib/api";
import { PRIMARY_KEY_REF, type LinkedInstances, type ObjectInstance } from "@/lib/types";

export type LinkStop = {
  typeId: string;
  typeName: string;
  instance: ObjectInstance;
};

function propertyLabel(name: string): string {
  return name === PRIMARY_KEY_REF ? "key" : name;
}

/** A short, human summary of an instance for a row you might click. */
function summarise(instance: ObjectInstance): string {
  const values = Object.entries(instance.properties)
    .filter(([, v]) => v !== null && v !== undefined && String(v) !== "")
    .slice(0, 3)
    .map(([k, v]) => `${k}: ${String(v)}`);
  return values.join(" · ");
}

function LinkGroup({
  group,
  browseHref,
  onOpen,
}: {
  group: LinkedInstances;
  browseHref: string;
  onOpen: (stop: LinkStop) => void;
}) {
  const arrow = group.direction === "outbound" ? "→" : "←";
  return (
    <section style={{ marginBottom: 18 }}>
      <div
        className="row-actions"
        style={{ justifyContent: "space-between", alignItems: "baseline" }}
      >
        <h3 style={{ fontSize: 13.5, margin: 0 }}>
          {group.display_name} {arrow} {group.far_type_display_name}
          <span className="slug" style={{ marginLeft: 8, fontWeight: 400 }}>
            {propertyLabel(group.near_property)} = {propertyLabel(group.far_property)}
          </span>
        </h3>
        <span className="count">
          {group.total} {group.total === 1 ? "object" : "objects"}
        </span>
      </div>

      {group.total === 0 && (
        <p className="login-note" style={{ margin: "4px 0 0" }}>
          {group.matched_value === null || group.matched_value === undefined
            ? `No ${propertyLabel(group.near_property)} on this object, so this link points at nothing.`
            : `Nothing matches ${String(group.matched_value)}.`}
        </p>
      )}

      {group.items.length > 0 && (
        <ul className="link-list">
          {group.items.map((i) => (
            <li key={i.id}>
              <button
                type="button"
                className="btn quiet"
                style={{ padding: "4px 10px", fontSize: 12.5, textAlign: "left" }}
                onClick={() =>
                  onOpen({
                    typeId: group.far_type_id,
                    typeName: group.far_type_display_name,
                    instance: i,
                  })
                }
              >
                <strong>{i.primary_key}</strong>
                {summarise(i) && (
                  <span className="slug" style={{ marginLeft: 8 }}>
                    {summarise(i)}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}

      {group.total > group.items.length && (
        <p className="login-note" style={{ margin: "4px 0 0" }}>
          Showing {group.items.length} of {group.total}.{" "}
          <Link href={browseHref}>Browse all {group.far_type_display_name}</Link>
        </p>
      )}
    </section>
  );
}

export function LinkExplorerDialog({
  workspaceId,
  workspaceSlug,
  projectSlug,
  start,
  onClose,
}: {
  workspaceId: string;
  workspaceSlug: string;
  projectSlug: string;
  start: LinkStop;
  onClose: () => void;
}) {
  const [trail, setTrail] = useState<LinkStop[]>([start]);
  // The trail is never empty - it starts with one stop and only ever grows or
  // truncates to an existing index - but the type says it could be, so fall
  // back to the start rather than asserting.
  const here = trail[trail.length - 1] ?? start;

  const links = useQuery({
    queryKey: ["instance-links", workspaceId, here.typeId, here.instance.id],
    queryFn: () => objApi.instanceLinks(workspaceId, here.typeId, here.instance.id),
  });

  return (
    <Dialog open wide title={`${here.typeName} · ${here.instance.primary_key}`} onClose={onClose}>
      {trail.length > 1 && (
        <nav className="row-actions" style={{ marginBottom: 10, flexWrap: "wrap" }} aria-label="Traversal trail">
          {trail.map((stop, index) => (
            <span key={`${stop.typeId}:${stop.instance.id}`}>
              {index > 0 && <span className="slug" style={{ margin: "0 6px" }}>/</span>}
              {index === trail.length - 1 ? (
                <span className="slug">{stop.instance.primary_key}</span>
              ) : (
                <button
                  type="button"
                  className="btn quiet"
                  style={{ padding: "2px 8px", fontSize: 12 }}
                  onClick={() => setTrail(trail.slice(0, index + 1))}
                >
                  {stop.instance.primary_key}
                </button>
              )}
            </span>
          ))}
        </nav>
      )}

      {links.isPending && <div className="state">Following links…</div>}
      {links.isError && <div className="state error">Couldn&apos;t load this object&apos;s links.</div>}
      {links.data && links.data.length === 0 && (
        <div className="empty" style={{ padding: "18px 0" }}>
          <h2 style={{ fontSize: 14 }}>No traversable links</h2>
          <p>
            Link types describe which object types relate to each other. To follow one from a
            specific object, a link also needs to say <em>which properties join</em> - set that on
            the Link types table and this panel fills in.
          </p>
        </div>
      )}
      {links.data?.map((group) => (
        <LinkGroup
          key={`${group.link_type_id}:${group.direction}`}
          group={group}
          browseHref={`/${workspaceSlug}/${projectSlug}/objects/${group.far_type_id}`}
          onOpen={(stop) => setTrail([...trail, stop])}
        />
      ))}

      <div className="form-actions">
        <button type="button" className="btn quiet" onClick={onClose}>
          Close
        </button>
      </div>
    </Dialog>
  );
}
