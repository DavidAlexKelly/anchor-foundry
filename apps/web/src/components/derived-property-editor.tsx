"use client";

/**
 * Configuring a derived property (Foundry `object-link-types` p.144–147).
 *
 * > "In the Linked objects section, select a link type from the dropdown. This
 * > determines which objects the property will derive values from … Use Add
 * > linked object to traverse through another level of linked objects."
 *
 * **The chain is built one hop at a time, and each step only offers links that
 * exist from where it stands.** That is p.145's own behaviour — "the dropdown
 * menu shows all available link types from your current object type" — and it
 * is what keeps the form from being able to describe a walk the save rejects.
 * The walk itself is `lib/derived-property.ts`, pure and unit-tested; this
 * file is the controls around it.
 *
 * **One of p.145's nine aggregations is missing on purpose**, and it used to
 * be five. `approx_cardinality` is refused because OpenSearch approximates
 * where Postgres is exact, which is a difference between the stores rather
 * than a gap in this platform; `exact_cardinality` is the same question with
 * an answer both can give, so it is the one offered.
 *
 * `sum`, `avg`, `min` and `max` were refused alongside it, with a hint on this
 * screen saying "instance properties are stored untyped". True when written
 * and untrue from §220 — §406 removed the refusal. The hint is the third of
 * this shape the parity work has found (§228 on the Pie Chart's panel, §229 on
 * the Metric Card's), which is what makes it a pattern: **a control that
 * explains why it cannot work is a claim with a date on it**, and nothing
 * re-reads it when the date passes.
 *
 * **The property picker therefore offers two different lists**, the same split
 * the Metric Card makes: the four arithmetic aggregations run only over a
 * declared `integer` or `float`, and everything else works on any property.
 * p.169 is the other half of the same rule — those four run on the linked
 * type's **native** properties, so a derived one is not offered either.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Dialog, Field } from "@/components/dialog";
import { objects as objApi } from "@/lib/api";
import type { Derivation, ObjectTypeProperty } from "@/lib/types";
import {
  chainState, derivableProperties, derivationProblem, hopsFrom, type Hop,
} from "@/lib/derived-property";

/** p.145's list, minus the one the server still refuses. `""` is "no
 * aggregation", legal only when no hop can reach more than one object. */
const AGGREGATES: [string, string][] = [
  ["", "None — a single linked object"],
  ["count", "Count"],
  ["sum", "Sum"],
  ["avg", "Average"],
  ["min", "Minimum"],
  ["max", "Maximum"],
  ["exact_cardinality", "Exact cardinality"],
  ["collect_list", "Collect list"],
  ["collect_set", "Collect set"],
];

const COLLECTORS = ["collect_list", "collect_set"];

export function DerivedPropertyEditor({
  open,
  onClose,
  propertyName,
  workspaceId,
  objectTypeId,
  value,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  propertyName: string;
  workspaceId: string;
  /** The type this property is on — where every chain starts. */
  objectTypeId: string;
  value: Derivation | null | undefined;
  onSave: (next: Derivation | null) => void;
}) {
  const links = useQuery({
    queryKey: ["link-types", workspaceId],
    queryFn: () => objApi.listLinkTypes(workspaceId),
  });
  const all = links.data ?? [];

  // The chain as *hops* rather than as the saved shape: a hop knows where it
  // lands and whether it reaches many, and rebuilding that from ids on every
  // render would be the same walk done twice.
  const [hops, setHops] = useState<Hop[]>(() =>
    // Rehydrated lazily below once the link types arrive; an existing
    // derivation opens with its chain already chosen.
    [],
  );
  const [loaded, setLoaded] = useState(false);
  const [aggregate, setAggregate] = useState(value?.aggregate ?? "");
  const [property, setProperty] = useState(value?.property ?? "");
  const [limit, setLimit] = useState(String(value?.limit ?? ""));

  // Rehydrate once, when the link types are in: a saved chain is a list of
  // ids, and turning it back into hops needs the ontology.
  if (!loaded && all.length && value?.links?.length) {
    setLoaded(true);
    let here = objectTypeId;
    const restored: Hop[] = [];
    for (const saved of value.links) {
      const hop = hopsFrom(all, here).find(
        (h) => h.link_type_id === saved.link_type_id
          && h.far_type_id === saved.far_type_id,
      );
      if (!hop) break;
      restored.push(hop);
      here = hop.far_type_id;
    }
    setHops(restored);
  } else if (!loaded && all.length) {
    setLoaded(true);
  }

  const state = chainState(objectTypeId, hops);
  const available = hopsFrom(all, state.here);
  const problem = derivationProblem(state, aggregate, property);

  // The properties of the type the chain lands on — p.146's "all available
  // properties from the final object type in your link chain".
  const farType = useQuery({
    queryKey: ["object-type", state.here],
    queryFn: () => objApi.getType(workspaceId, state.here),
    enabled: hops.length > 0,
  });
  const farProperties: ObjectTypeProperty[] = farType.data?.properties ?? [];

  function apply() {
    onSave({
      links: hops.map((h) => ({ link_type_id: h.link_type_id, far_type_id: h.far_type_id })),
      far_type_id: state.here,
      // **No cast.** This read `aggregate as "count"` until §410, which made
      // every aggregation type-check as a count and is why §406 could add four
      // to the dropdown without the type noticing they were not in the union.
      ...(aggregate
        ? { aggregate: aggregate as NonNullable<Derivation["aggregate"]> }
        : {}),
      ...(aggregate !== "count" && property ? { property } : {}),
      ...(COLLECTORS.includes(aggregate) && limit.trim()
        ? { limit: Number(limit) }
        : {}),
    });
    onClose();
  }

  return (
    <Dialog open={open} title={`Derive ${propertyName}`} onClose={onClose} wide>
      <p className="field-hint">
        A derived property is calculated when somebody opens the object, from
        the objects it links to. Nothing is stored under it.
      </p>

      {hops.map((hop, index) => (
        <Field key={index} label={`Link ${index + 1}`}>
          <div className="row-actions">
            <span data-testid={`derive-hop-${index + 1}`}>{hop.label}</span>
            {index === hops.length - 1 && (
              <button
                type="button"
                className="btn quiet"
                style={{ padding: "3px 9px", fontSize: 12 }}
                aria-label={`Remove link ${index + 1}`}
                onClick={() => setHops(hops.slice(0, index))}
              >
                Remove
              </button>
            )}
          </div>
        </Field>
      ))}

      {state.canExtend && (
        <Field
          label={hops.length ? "Add linked object" : "Linked objects"}
          hint="Only the links that exist from where the chain stands."
        >
          <select
            data-testid="derive-add-hop"
            value=""
            onChange={(e) => {
              const hop = available.find(
                (h) => `${h.link_type_id}:${h.far_type_id}` === e.target.value,
              );
              if (!hop) return;
              // The property goes with the landing type: keeping a name from
              // the previous far type would name a property of a different
              // object, which the save would refuse.
              setHops([...hops, hop]);
              setProperty("");
            }}
          >
            <option value="">Choose a link…</option>
            {available.map((hop) => (
              <option
                key={`${hop.link_type_id}:${hop.far_type_id}`}
                value={`${hop.link_type_id}:${hop.far_type_id}`}
              >
                {hop.label}
              </option>
            ))}
          </select>
        </Field>
      )}

      {hops.length > 0 && (
        <>
          <Field
            label="Aggregation"
            hint={
              state.reachesMany
                ? "This chain can reach more than one object, so it needs one."
                : "Optional — this chain reaches a single object."
            }
          >
            <select
              data-testid="derive-aggregate"
              value={aggregate}
              onChange={(e) => setAggregate(e.target.value)}
            >
              {AGGREGATES.map(([v, label]) => (
                <option key={v} value={v}>{label}</option>
              ))}
            </select>
          </Field>
          <p className="field-hint">
            Approximate cardinality is not available: this platform&rsquo;s two
            stores would disagree about how approximate it is. Exact
            cardinality is the same question with an answer both can give.
          </p>

          {aggregate !== "count" && (
            <Field label="Property" hint="From the object type the chain lands on.">
              <select
                data-testid="derive-property"
                value={property}
                onChange={(e) => setProperty(e.target.value)}
              >
                <option value="">Choose a property…</option>
                {/* **Two different lists.** The four arithmetic aggregations
                    need a declared number, and p.169 restricts them to the
                    linked type&rsquo;s native properties; everything else
                    works on any of them. Offering the full list to a `sum`
                    would be offering a save that fails. */}
                {derivableProperties(farProperties, aggregate).map((p) => (
                  <option key={p.api_name} value={p.api_name}>
                    {p.display_name || p.api_name}
                  </option>
                ))}
              </select>
            </Field>
          )}

          {COLLECTORS.includes(aggregate) && (
            <Field label="Limit" hint="How many to collect. Defaults to 10.">
              <input
                type="number"
                data-testid="derive-limit"
                value={limit}
                onChange={(e) => setLimit(e.target.value)}
              />
            </Field>
          )}
        </>
      )}

      {problem && <p className="field-hint" data-testid="derive-problem">{problem}</p>}
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        {value && (
          <button
            type="button"
            className="btn danger"
            data-testid="derive-clear"
            onClick={() => {
              onSave(null);
              onClose();
            }}
          >
            Not derived
          </button>
        )}
        <button
          type="button"
          className="btn primary"
          data-testid="derive-save"
          disabled={problem !== null}
          onClick={apply}
        >
          Apply
        </button>
      </div>
    </Dialog>
  );
}
