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
import { ObjectView } from "@/components/object-view";
import { PropertyValue } from "@/components/property-value";
import { conditionalStyle } from "@/lib/conditional-format";
import { summarise, visibleProperties } from "@/components/object-properties";
import { linkSubsetHref } from "@/lib/link-subset";
import {
  PRIMARY_KEY_REF,
  type LinkedInstances,
  type ObjectInstance,
  type ObjectTypeProperty,
} from "@/lib/types";

export type LinkStop = {
  typeId: string;
  typeName: string;
  instance: ObjectInstance;
};

function propertyLabel(name: string): string {
  return name === PRIMARY_KEY_REF ? "key" : name;
}

/** One linked object's properties, without leaving the object you came from
 * (Foundry `object-views` p.11).
 *
 * The Linked objects component's point is that a relationship is answerable in
 * place: "which team owns this ticket, and what is that team's region" should
 * not cost a hop you then have to come back from. Traversing is still one
 * click - this is the *other* click, and they are deliberately separate
 * controls rather than one that guesses.
 *
 * Typed rendering through `PropertyValue`, the same component the standard
 * view uses, so a geopoint reads as a geopoint here too.
 */
function LinkedPreview({
  workspaceId,
  properties,
  instance,
}: {
  workspaceId: string;
  properties: ObjectTypeProperty[];
  instance: ObjectInstance;
}) {
  const { prominent, normal } = visibleProperties(properties);
  const shown = [...prominent, ...normal];
  if (shown.length === 0) {
    return (
      <p className="login-note" style={{ margin: "2px 0 0 12px" }}>
        This object type has no properties a reader may see.
      </p>
    );
  }
  return (
    <table
      className="ds-table sov-table"
      style={{ margin: "4px 0 0 12px" }}
      data-testid={`link-preview-${instance.id}`}
    >
      <tbody>
        {shown.map((property) => (
          <tr key={property.api_name} data-property={property.api_name}>
            <th scope="row">{property.display_name || property.api_name}</th>
            <td>
              <PropertyValue
                workspaceId={workspaceId}
                dataType={property.data_type}
                valueFormat={property.value_format}
                style={conditionalStyle(property.conditional_format, instance.properties)}
                value={instance.properties[property.api_name]}
              />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function LinkGroup({
  workspaceId,
  group,
  browseHref,
  subsetHref,
  onOpen,
  onSelect,
  selectedId,
}: {
  workspaceId: string;
  group: LinkedInstances;
  browseHref: string | null;
  /** Where p.11's "open a subset of linked objects in a new tab" goes, or
   * null when there is no subset to open. */
  subsetHref: string | null;
  onOpen: (stop: LinkStop) => void;
  onSelect: (stop: LinkStop) => void;
  selectedId: string | null;
}) {
  // Which rows are open. A set rather than one id: two linked objects are
  // routinely compared, and a preview that closed the last one would make
  // that impossible without navigating - which is the thing this exists to
  // avoid.
  const [open, setOpen] = useState<Set<string>>(new Set());
  // **The far type's declaration, not the instance's keys.** It says which
  // properties may be shown at all (p.111) and which identify one of these
  // (p.10). One query per group, shared with everything else keyed the same
  // way, and the rows render without it - a summary that waited for a fetch
  // would blank every link row on open.
  const farType = useQuery({
    queryKey: ["object-type", group.far_type_id],
    queryFn: () => objApi.getType(workspaceId, group.far_type_id),
  });
  const properties = farType.data?.properties ?? [];
  const arrow = group.direction === "outbound" ? "→" : "←";
  // The name of the side being traversed *to* (Foundry `object-link-types`
  // p.192). Already resolved by the server against the link's own name, so an
  // unnamed side reads exactly as it did before sides could be named — and a
  // self-link's two directions finally read differently ("Manager" one way,
  // "Direct reports" the other) instead of showing one word twice.
  const label = group.side_name || group.display_name;
  return (
    <section style={{ marginBottom: 18 }}>
      <div
        className="row-actions"
        style={{ justifyContent: "space-between", alignItems: "baseline" }}
      >
        <h3 style={{ fontSize: 13.5, margin: 0 }}>
          {label} {arrow} {group.far_type_display_name}
          <span className="slug" style={{ marginLeft: 8, fontWeight: 400 }}>
            {propertyLabel(group.near_property)} = {propertyLabel(group.far_property)}
          </span>
        </h3>
        <span className="count">
          {group.total} {group.total === 1 ? "object" : "objects"}
          {/* p.11: "Open a subset of linked objects in a new tab for further
              exploration." A new tab because the point is *further*
              exploration - taking the reader away from the object they are
              standing on would make the two exclusive. */}
          {subsetHref && (
            <Link
              href={subsetHref}
              target="_blank"
              rel="noopener"
              className="slug"
              style={{ marginLeft: 10, textDecoration: "underline" }}
              data-testid={`link-subset-${group.link_type_id}`}
            >
              open these
            </Link>
          )}
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
              <div className="row-actions" style={{ gap: 4 }}>
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
                  {summarise(i, properties) && (
                    <span className="slug" style={{ marginLeft: 8 }}>
                      {summarise(i, properties)}
                    </span>
                  )}
                </button>
                {/* Separate from the row, because they are different
                    intentions: one goes there, the other looks without
                    going. A row that did both on one click would make the
                    cheaper one impossible. */}
                <button
                  type="button"
                  className="btn quiet"
                  style={{ padding: "4px 8px", fontSize: 12 }}
                  aria-expanded={open.has(i.id)}
                  aria-label={`Preview ${i.primary_key}`}
                  onClick={() =>
                    setOpen((was) => {
                      const next = new Set(was);
                      if (!next.delete(i.id)) next.add(i.id);
                      return next;
                    })
                  }
                >
                  {open.has(i.id) ? "Hide" : "Preview"}
                </button>
                {/* p.11's fourth capability, and a *third* intention: the
                    inline preview above compares several at once (which is
                    why it is a set), traversal replaces where you are, and
                    this holds one object beside everything while you keep
                    reading the groups. */}
                <button
                  type="button"
                  className="btn quiet"
                  style={{ padding: "4px 8px", fontSize: 12 }}
                  aria-pressed={selectedId === i.id}
                  aria-label={`Show ${i.primary_key} in the side panel`}
                  onClick={() =>
                    onSelect({
                      typeId: group.far_type_id,
                      typeName: group.far_type_display_name,
                      instance: i,
                    })
                  }
                >
                  Panel
                </button>
              </div>
              {open.has(i.id) && (
                <LinkedPreview
                  workspaceId={workspaceId}
                  properties={properties}
                  instance={i}
                />
              )}
            </li>
          ))}
        </ul>
      )}

      {group.total > group.items.length && (
        <p className="login-note" style={{ margin: "4px 0 0" }}>
          Showing {group.items.length} of {group.total}.{" "}
          {browseHref && (
            <Link href={browseHref}>Browse all {group.far_type_display_name}</Link>
          )}
        </p>
      )}
    </section>
  );
}

/** p.11: "Preview a selected linked object in the side panel of the standard
 * Object View."
 *
 * The whole object rather than a few properties, which is what makes it a
 * different answer from the inline preview: that one is a summary you open
 * under a row to compare several, this is *the* object, held beside the view
 * you are reading. Traversing to it is still one click, from in here.
 *
 * `ObjectView` rather than a table of its own, so a configured view (§144), a
 * prominent geopoint's map and a time series chart all render here exactly as
 * they do anywhere else — a second renderer would be a second thing to keep
 * in step, which is the mistake `object-properties.ts` exists to record.
 */
function SidePanel({
  workspaceId,
  stop,
  onClose,
  onOpen,
}: {
  workspaceId: string;
  stop: LinkStop;
  onClose: () => void;
  onOpen: (stop: LinkStop) => void;
}) {
  return (
    <aside className="link-side-panel" aria-label="Linked object panel">
      <div
        className="row-actions"
        style={{ justifyContent: "space-between", alignItems: "baseline" }}
      >
        <h3 style={{ fontSize: 13.5, margin: 0 }}>
          {stop.typeName} <span className="slug">{stop.instance.primary_key}</span>
        </h3>
        <div className="row-actions" style={{ gap: 4 }}>
          <button
            type="button"
            className="btn quiet"
            style={{ padding: "3px 9px", fontSize: 12 }}
            onClick={() => onOpen(stop)}
          >
            Go to
          </button>
          <button
            type="button"
            className="btn quiet"
            style={{ padding: "3px 9px", fontSize: 12 }}
            aria-label="Close the linked object panel"
            onClick={onClose}
          >
            Close
          </button>
        </div>
      </div>
      <ObjectView
        workspaceId={workspaceId}
        typeId={stop.typeId}
        instance={stop.instance}
      />
    </aside>
  );
}

export function LinkExplorerDialog({
  workspaceId,
  workspaceSlug,
  browseHref,
  start,
  onClose,
}: {
  workspaceId: string;
  /** Where "Browse all X" goes for a type reached by traversal. A function
   *  rather than a slug pair because traversal is no longer only reachable
   *  from inside a project: the Object Explorer (item 4.1) is workspace-wide
   *  and sends people to the type's own application instead. `null` means
   *  there is nowhere to send them, and the link is simply not offered. */
  browseHref: (farTypeId: string) => string | null;
  /** The workspace slug, only so the Explorer link can be built (p.11). Passed
   * rather than derived, for `browseHref`'s reason: this component knows about
   * objects, not about routing. */
  workspaceSlug: string;
  start: LinkStop;
  onClose: () => void;
}) {
  const [trail, setTrail] = useState<LinkStop[]>([start]);
  // p.11's side panel holds exactly one object, and it survives moving
  // between groups - that is the difference from the inline preview, which
  // belongs to the row it opened under.
  const [selected, setSelected] = useState<LinkStop | null>(null);
  // The trail is never empty - it starts with one stop and only ever grows or
  // truncates to an existing index - but the type says it could be, so fall
  // back to the start rather than asserting.
  const here = trail[trail.length - 1] ?? start;

  const links = useQuery({
    queryKey: ["instance-links", workspaceId, here.typeId, here.instance.id],
    queryFn: () => objApi.instanceLinks(workspaceId, here.typeId, here.instance.id),
  });
  // Cleared when the object under it changes: a panel still showing something
  // linked to where you *were* is the same wrong-context bug the trail exists
  // to prevent, and it would be silent.
  const hereId = here.instance.id;
  const [panelFor, setPanelFor] = useState(hereId);
  if (panelFor !== hereId) {
    setPanelFor(hereId);
    if (selected) setSelected(null);
  }

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

      {/* The Object View (Foundry `object-views` p.10-11) above the links,
          because the object is what you came to see and the Linked objects
          component is a *part* of that view rather than a separate screen. The
          dialog was links-only before there was a view to put them under;
          `ObjectView` now decides between the generated one and a configured
          module, and offers the reader the switch p.2 guarantees. */}
      <ObjectView
        workspaceId={workspaceId}
        typeId={here.typeId}
        instance={here.instance}
      />

      <h3 className="sov-section">Linked objects</h3>
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
      <div className={selected ? "links-with-panel" : undefined}>
        <div>
          {links.data?.map((group) => (
            <LinkGroup
              key={`${group.link_type_id}:${group.direction}`}
              workspaceId={workspaceId}
              group={group}
              browseHref={browseHref(group.far_type_id)}
              subsetHref={linkSubsetHref(workspaceSlug, group)}
              onOpen={(stop) => setTrail([...trail, stop])}
              onSelect={(stop) =>
                // Clicking the selected one again puts it away, so the control
                // is the same one both ways round.
                setSelected((was) =>
                  was?.instance.id === stop.instance.id ? null : stop,
                )
              }
              selectedId={selected?.instance.id ?? null}
            />
          ))}
        </div>
        {selected && (
          <SidePanel
            workspaceId={workspaceId}
            stop={selected}
            onClose={() => setSelected(null)}
            onOpen={(stop) => {
              setSelected(null);
              setTrail([...trail, stop]);
            }}
          />
        )}
      </div>

      <div className="form-actions">
        <button type="button" className="btn quiet" onClick={onClose}>
          Close
        </button>
      </div>
    </Dialog>
  );
}
