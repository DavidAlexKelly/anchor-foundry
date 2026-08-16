"use client";

/**
 * The standard Object View (parity `docs/parity/ontology.md` §4.1; Foundry
 * `object-views` p.10–11).
 *
 * > "When you create and configure an object type in your Ontology, Foundry
 * > automatically creates a standard Object View… The standard Object View
 * > matches the object type's configuration by spotlighting prominent
 * > properties… Normal properties are displayed in a regular table, and hidden
 * > properties are not visible."
 *
 * **Generated, never configured.** There is no builder, no saved document and
 * nothing to publish: the view *is* the object type's configuration, read back.
 * That is what makes it worth having early — every object type becomes
 * navigable the moment it exists, with no per-type work at all.
 *
 * **Property visibility (§121) is the whole input.** Prominent properties get
 * the card treatment above the table; normal ones fill the table; hidden ones
 * are absent. Without visibility this would be one undifferentiated table per
 * type, which is what the Explorer already showed.
 *
 * **Two of Foundry's four type-aware renderings are out of reach**, and the
 * reason is a missing property type rather than a missing view:
 *
 *   - media reference → a media viewer  — we have no media reference type
 *   - time series     → an interactive chart — we have no time series type
 *   - geospatial      → a Map  ✅ (geopoint)
 *   - everything else → a large card       ✅
 *
 * They are named in `ontology.md` §1.1 as ○ and will land with the types, not
 * with this file. Rendering them as plain cards in the meantime is the correct
 * behaviour, not a stub: a geopoint has a map because we can draw one.
 */

import { useQuery } from "@tanstack/react-query";
import { objects as objApi } from "@/lib/api";
import { MapCanvas } from "@/components/canvas/map";
import { toLatLon } from "@/components/canvas/map";
import { PropertyValue } from "@/components/property-value";
import { visibleProperties } from "@/components/object-properties";
import { plot } from "@/components/series-plot";
import type { ObjectInstance, ObjectTypeProperty } from "@/lib/types";

/** A prominent `time_series` property, drawn (p.11).
 *
 * The counterpart to the map above it, and the same argument: the property
 * type says what this *is*, so the view draws it rather than printing the
 * series id. Points come from the dataset they arrived in (decision 0009) -
 * nothing was copied to make this chart possible.
 *
 * **Bucketed by day and averaged.** A raw series can be tens of thousands of
 * readings and this is a card, not an analysis surface; the Workshop time
 * series widget is where a viewer chooses. Named here rather than left to be
 * inferred from a curve that looks smoother than the data.
 */
function SeriesCard({
  workspaceId,
  typeId,
  instanceId,
  property,
}: {
  workspaceId: string;
  typeId: string;
  instanceId: string;
  property: ObjectTypeProperty;
}) {
  const series = useQuery({
    queryKey: ["instance-series", workspaceId, typeId, instanceId, property.api_name],
    queryFn: () =>
      objApi.seriesPoints(workspaceId, typeId, instanceId, property.api_name, {
        interval: "day",
        aggregate: "avg",
      }),
  });
  const laid = plot(series.data?.points ?? [], { width: 260, height: 90 });

  return (
    <article className="sov-card" data-property={property.api_name}>
      <h3 className="sov-card-label">{property.display_name || property.api_name}</h3>
      {series.isPending && <p className="canvas-widget-empty">Loading readings…</p>}
      {series.isError && (
        <p className="state error" style={{ margin: 0 }}>
          Couldn&apos;t read this series.
        </p>
      )}
      {series.data && !laid && (
        // Declared, mapped, and empty. Saying so beats an axis with nothing
        // on it, which reads as a chart that failed to draw.
        <p className="canvas-widget-empty">No readings for this object yet.</p>
      )}
      {laid && (
        <div className="sov-card-series" data-testid={`sov-series-${property.api_name}`}>
          <svg viewBox="0 0 260 90" role="img" aria-label={
            `${property.display_name || property.api_name}: ${laid.points.length} readings, ` +
            `${laid.min} to ${laid.max}`
          }>
            <path d={laid.path} fill="none" stroke="currentColor" strokeWidth={1.5} />
            {/* The last reading marked, because "where is it now" is the
                question a card-sized chart is usually asked. */}
            <circle
              cx={laid.points[laid.points.length - 1]!.x}
              cy={laid.points[laid.points.length - 1]!.y}
              r={2.5}
              fill="currentColor"
            />
          </svg>
          <p className="slug" style={{ margin: 0 }}>
            {laid.points.length} readings · {laid.min} to {laid.max}
          </p>
        </div>
      )}
    </article>
  );
}

function ProminentCard({
  workspaceId,
  property,
  value,
}: {
  workspaceId: string;
  property: ObjectTypeProperty;
  value: unknown;
}) {
  // p.11: "Objects with prominent geohash, geoshape, or geotemporal series
  // reference properties will render on a Map." Ours is geopoint, and one
  // point is still a map — it answers "where is this" without making somebody
  // read a coordinate pair.
  const point = property.data_type === "geopoint" ? toLatLon(value) : null;
  return (
    <article className="sov-card" data-property={property.api_name}>
      <h3 className="sov-card-label">{property.display_name || property.api_name}</h3>
      {point ? (
        <div className="sov-card-map" data-testid={`sov-map-${property.api_name}`}>
          <MapCanvas
            points={[{ id: property.api_name, ...point, label: property.display_name }]}
            total={1}
          />
        </div>
      ) : (
        <div className="sov-card-value">
          <PropertyValue
            workspaceId={workspaceId}
            dataType={property.data_type}
            valueFormat={property.value_format}
            value={value}
          />
        </div>
      )}
    </article>
  );
}

export function StandardObjectView({
  workspaceId,
  typeId,
  instance,
}: {
  workspaceId: string;
  typeId: string;
  instance: ObjectInstance;
}) {
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId),
  });

  // **The marker is on the view, not on its success.** Rendering nothing
  // identifiable while the type loads means a failure to load and a failure to
  // *render* look identical from outside - which cost a diagnosis, because the
  // browser test could only report "the view is not here" and not which of the
  // two it was.
  if (type.isPending || type.isError) {
    return (
      <div className="sov" data-testid="standard-object-view" data-state={type.isError ? "error" : "loading"}>
        {type.isError ? (
          <p className="state error">Couldn&apos;t load this object type&apos;s configuration.</p>
        ) : (
          <p className="state">Loading the object type…</p>
        )}
      </div>
    );
  }

  const properties = type.data.properties;
  const { prominent, normal } = visibleProperties(properties);
  const titleProperty = properties.find((p) => p.id === type.data.title_property_id);
  const title = titleProperty
    ? String(instance.properties[titleProperty.api_name] ?? instance.primary_key)
    : String(instance.primary_key);

  return (
    <div className="sov" data-testid="standard-object-view" data-state="ready">
      <header className="sov-head">
        <p className="sov-type">{type.data.display_name}</p>
        <h2 className="sov-title">{title}</h2>
      </header>

      {prominent.length > 0 && (
        <div className="sov-cards" data-testid="sov-prominent">
          {prominent.map((p) =>
            // A time series is not a value to print - it is a chart, and it
            // needs a fetch the other card kinds do not.
            p.data_type === "time_series" ? (
              <SeriesCard
                key={p.api_name}
                workspaceId={workspaceId}
                typeId={typeId}
                instanceId={instance.id}
                property={p}
              />
            ) : (
              <ProminentCard
                key={p.api_name}
                workspaceId={workspaceId}
                property={p}
                value={instance.properties[p.api_name]}
              />
            ),
          )}
        </div>
      )}

      {normal.length > 0 ? (
        <table className="ds-table sov-table" data-testid="sov-normal">
          <thead>
            <tr>
              <th scope="col">Property</th>
              <th scope="col">Value</th>
            </tr>
          </thead>
          <tbody>
            {normal.map((p) => (
              <tr key={p.api_name} data-property={p.api_name}>
                <th scope="row">{p.display_name || p.api_name}</th>
                <td>
                  <PropertyValue
                    workspaceId={workspaceId}
                    dataType={p.data_type}
                    valueFormat={p.value_format}
                    value={instance.properties[p.api_name]}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        // Reachable, and worth saying rather than rendering an empty table: an
        // object type whose every property is prominent has nothing left for
        // the table, and so does one where they are all hidden.
        <p className="canvas-widget-empty">No other properties to show.</p>
      )}
    </div>
  );
}
