"use client";

/**
 * Setting a resource's status (Foundry `object-link-types` p.253–259).
 *
 * > "By default, any new ontological resource will be given the
 * > `experimental` status. To change the status: select the dropdown next to
 * > the current status." (p.256)
 *
 * **Two things this does beyond drawing a `<select>`**, and both are about
 * telling somebody what is going to happen rather than what happened:
 *
 * * p.256's propagation is invisible until it has already run. Demoting an
 *   object type demotes every property on it, so the warning is on screen
 *   while the choice is still a choice.
 * * p.256 prompts for a deprecation note, and the server refuses one anywhere
 *   else — so the fields appear exactly where they are legal.
 */

import { Field } from "@/components/dialog";
import {
  STATUS_HINTS, STATUS_LABELS, propagationWarning, statusesFor,
  wantsDeprecationNote,
} from "@/lib/ontology-status";
import type { Deprecation, OntologyStatus } from "@/lib/types";

export function StatusField({
  kind,
  value,
  deprecation,
  onChange,
  onDeprecationChange,
  /** Present only for an object type, and only so the propagation warning has
   * something to count. Absent means "nothing hangs off this". */
  properties,
  label = "Status",
}: {
  kind: "object_type" | "property" | "link_type";
  value: OntologyStatus;
  deprecation?: Deprecation | null;
  onChange: (next: OntologyStatus) => void;
  onDeprecationChange?: (next: Deprecation | null) => void;
  properties?: { api_name: string; status: OntologyStatus }[];
  label?: string;
}) {
  const warning = properties ? propagationWarning(value, properties) : null;

  return (
    <>
      <Field label={label} hint={STATUS_HINTS[value]}>
        <select
          data-testid="status-select"
          value={value}
          onChange={(e) => {
            const next = e.target.value as OntologyStatus;
            onChange(next);
            // p.254's note belongs to a deprecated resource and the server
            // refuses it elsewhere, so moving away clears it rather than
            // leaving a resource explaining why it was going to be deleted.
            if (!wantsDeprecationNote(next)) onDeprecationChange?.(null);
          }}
        >
          {statusesFor(kind).map((s) => (
            <option key={s} value={s}>{STATUS_LABELS[s]}</option>
          ))}
        </select>
      </Field>

      {warning && (
        <p className="field-hint" data-testid="status-propagation">{warning}</p>
      )}

      {wantsDeprecationNote(value) && onDeprecationChange && (
        <>
          <Field
            label="Why it is being deprecated"
            hint="p.254 — so somebody finding this later knows what happened."
          >
            <input
              type="text"
              data-testid="deprecation-reason"
              value={deprecation?.reason ?? ""}
              onChange={(e) =>
                onDeprecationChange({ ...deprecation, reason: e.target.value })
              }
            />
          </Field>
          <Field label="Expected removal date" hint="ISO date, e.g. 2026-12-31.">
            <input
              type="text"
              data-testid="deprecation-deadline"
              value={deprecation?.deadline ?? ""}
              onChange={(e) =>
                onDeprecationChange({ ...deprecation, deadline: e.target.value })
              }
            />
          </Field>
        </>
      )}
    </>
  );
}

/** The status as a small label beside a name, for listings.
 *
 * `experimental` draws nothing: it is p.256's default, so marking it would put
 * a badge on every row of a new ontology and say nothing by being everywhere.
 */
export function StatusBadge({ status }: { status: OntologyStatus }) {
  if (status === "experimental") return null;
  return (
    <span
      className="slug"
      data-testid={`status-badge-${status}`}
      title={STATUS_HINTS[status]}
      style={{ marginLeft: 6 }}
    >
      {STATUS_LABELS[status].toLowerCase()}
    </span>
  );
}
