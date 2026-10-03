"use client";

/**
 * `object-views` p.37-41's default panel Object Views (§694): the compact
 * view of one object, and the view of an object *set*.
 *
 * > "Panel Object Views are embedded into applications across the Palantir
 * > platform to provide users with a consistent experience of object data
 * > across workflows. All object types have a standard Object View panel
 * > available by default" (p.37)
 *
 * Workshop's Object View widget draws them (p.261-263), which is where this
 * platform embeds a panel. Which properties each draws is `lib/object-panels`.
 */

import { useQueries, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { objects as objApi } from "@/lib/api";
import { swatch } from "@/lib/object-type-icon";
import { TypeGlyph } from "@/components/icon";
import { keyProperties, panelChartProperties, panelListProperties } from "@/lib/object-panels";
import { PropertyValue } from "@/components/property-value";
import { conditionalStyle } from "@/lib/conditional-format";
import { visibleProperties } from "@/components/object-properties";
import { Chart } from "@/components/canvas/charts";
import type { ObjectInstance } from "@/lib/types";

/** p.41: "The default object instance panel view shows a single Property List
 * widget that displays prominent properties of a single instance of the
 * object type." */
export function StandardPanelView({ workspaceId, typeId, instance, hideHeader = false }: {
  workspaceId: string;
  typeId: string;
  instance: ObjectInstance;
  hideHeader?: boolean;
}) {
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId),
  });
  if (!type.data) {
    return <p className="state" data-testid="standard-panel-view">Loading the object type…</p>;
  }
  const { prominent } = visibleProperties(type.data.properties);
  const titleProperty = type.data.properties.find((p) => p.id === type.data.title_property_id);
  const title = titleProperty
    ? String(instance.properties[titleProperty.api_name] ?? instance.primary_key)
    : instance.primary_key;
  return (
    <div className="object-panel" data-testid="standard-panel-view">
      {!hideHeader && (
        <p className="sov-type">
          <span className="ot-mark" style={{ background: swatch(type.data) }} aria-hidden="true">
            <TypeGlyph type={type.data} />
          </span>
          <strong data-testid="panel-title">{title}</strong>
        </p>
      )}
      {prominent.length === 0 ? (
        <p className="canvas-widget-empty">This type marks no property prominent.</p>
      ) : (
        <dl className="canvas-property-list" data-testid="panel-properties">
          {prominent.map((p) => (
            <div className="canvas-property" key={p.api_name}>
              <dt>{p.display_name || p.api_name}</dt>
              <dd>
                <PropertyValue
                  workspaceId={workspaceId}
                  dataType={p.data_type}
                  valueFormat={p.value_format}
                  structFields={p.struct_fields}
                  style={conditionalStyle(p.conditional_format, instance.properties)}
                  value={instance.properties[p.api_name]}
                />
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

/** How many objects the List tab shows. */
const LIST_PAGE = 25;

/** p.41's default object set panel: "a tabbed layout with two interfaces to
 * explore object collections" - Charts and List, over the set given. */
export function ObjectSetPanel({ workspaceId, definition, typeId }: {
  workspaceId: string;
  definition: unknown;
  typeId: string;
}) {
  const [tab, setTab] = useState<"charts" | "list">("charts");
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId),
  });
  const properties = type.data?.properties ?? [];
  const titleId = type.data?.title_property_id ?? null;
  // The first page is the List tab's, and it is also what says which
  // property is the key (`keyProperties`), so the Charts tab reads it too.
  const page = useQuery({
    queryKey: ["panel-list", JSON.stringify(definition)],
    queryFn: () => objApi.evaluateObjectSet(workspaceId, definition, { limit: LIST_PAGE, sort: "key" }),
  });
  const charted = page.data
    ? panelChartProperties(properties, titleId, keyProperties(page.data.instances, properties))
    : [];
  const groups = useQueries({
    queries: charted.map((p) => ({
      queryKey: ["panel-group", JSON.stringify(definition), p.api_name],
      queryFn: () => objApi.groupObjectSet(workspaceId, definition, p.api_name),
      enabled: tab === "charts",
    })),
  });
  const titleProperty = properties.find((p) => p.id === titleId);
  const listed = panelListProperties(properties, titleId);
  const tabs: ["charts" | "list", string][] = [["charts", "Charts"], ["list", "List"]];
  return (
    <div className="object-panel" data-testid="object-set-panel">
      <div className="canvas-tabstrip" role="tablist" aria-label="Object set">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={`canvas-tabstrip-tab${tab === key ? " on" : ""}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "charts" ? (
        charted.length === 0 ? (
          <p className="canvas-widget-empty" data-testid="panel-no-charts">
            {type.data && page.data ? "This type has no property to group by." : "Loading…"}
          </p>
        ) : (
          charted.map((p, n) => (
            <figure key={p.api_name} className="object-panel-chart" data-testid="panel-chart">
              <figcaption>{p.display_name || p.api_name}</figcaption>
              {groups[n]?.data ? (
                <Chart
                  kind="bar"
                  points={groups[n]!.data!.groups.map((g) => ({ label: g.value, value: g.count }))}
                />
              ) : (
                <p className="canvas-widget-empty">Loading…</p>
              )}
            </figure>
          ))
        )
      ) : !page.data ? (
        <p className="canvas-widget-empty">Loading…</p>
      ) : page.data.instances.length === 0 ? (
        <p className="canvas-widget-empty" data-testid="panel-list-empty">No objects in this set.</p>
      ) : (
        <>
          <p className="canvas-widget-empty">
            {page.data.total.toLocaleString()} {type.data?.display_name ?? "object"}
            {page.data.total === 1 ? "" : "s"}
          </p>
          <ul className="object-panel-list" data-testid="panel-list">
            {page.data.instances.map((instance) => (
              <li key={instance.id} data-testid="panel-list-item">
                <strong>
                  {titleProperty
                    ? String(instance.properties[titleProperty.api_name] ?? instance.primary_key)
                    : instance.primary_key}
                </strong>
                {listed.map((p) => (
                  <span key={p.api_name} className="object-panel-detail">
                    <PropertyValue
                      workspaceId={workspaceId}
                      dataType={p.data_type}
                      valueFormat={p.value_format}
                      structFields={p.struct_fields}
                      value={instance.properties[p.api_name]}
                      compact
                    />
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
