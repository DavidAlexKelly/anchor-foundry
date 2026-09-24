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
 *   - geospatial      → a Map  ✅ (geopoint; geoshape since §426; a
 *                              geotemporal series' track since §427)
 *   - everything else → a large card       ✅
 *
 * They are named in `ontology.md` §1.1 as ○ and will land with the types, not
 * with this file. Rendering them as plain cards in the meantime is the correct
 * behaviour, not a stub: a geopoint has a map because we can draw one — and
 * §425 gave this platform the geoshape p.11 names second, so that one has a
 * map now too. The pattern holds: each rendering arrives with its type.
 */

import { useQuery } from "@tanstack/react-query";
import { objects as objApi } from "@/lib/api";
import { glyph, swatch } from "@/lib/object-type-icon";
import { MapCanvas } from "@/components/canvas/map";
import { isGeometry } from "@/lib/geoshape";
import { toLatLon } from "@/components/canvas/map";
import { PropertyValue } from "@/components/property-value";
import { ReducedValue } from "@/components/reduced-value";
import { conditionalStyle } from "@/lib/conditional-format";
import { visibleProperties } from "@/components/object-properties";
import { plot } from "@/components/series-plot";
import type { ObjectInstance, ObjectTypeProperty, PropertyStyle } from "@/lib/types";
import { OBJECT_MEDIA_TYPE, objectPayload } from "@/components/canvas/drag-payload";

/** A prominent `geotemporal_series` property, drawn on a Map (§427; p.11).
 *
 * > "Objects with prominent geohash, geoshape, or **geotemporal series
 * > reference (GTSR)** properties will render on a Map."
 *
 * **A LineString through the positions, which is §426's renderer** rather
 * than a fourth way of drawing geography: a track *is* a geometry, so the map
 * draws it the way it draws any other, and the projection has one
 * implementation (§292). The latest position gets a pin beside it, because
 * "where is it now" is the question a card-sized map is usually asked — and
 * the pin is a `points` entry rather than part of the shape, so it clusters
 * with nothing and sits above the line.
 *
 * **One position is a pin and no line**, which is the honest drawing: a
 * LineString of one point draws nothing at all, and a card that showed an
 * empty map for an object with a known location would be worse than one that
 * showed the location.
 */
function TrackCard({
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
  const track = useQuery({
    queryKey: ["instance-track", workspaceId, typeId, instanceId, property.api_name],
    queryFn: () => objApi.seriesTrack(workspaceId, typeId, instanceId, property.api_name),
  });
  const points = track.data?.points ?? [];
  const label = property.display_name || property.api_name;
  const last = points[points.length - 1];

  return (
    <article className="sov-card" data-property={property.api_name}>
      <h3 className="sov-card-label">{label}</h3>
      {track.isPending && <p className="canvas-widget-empty">Loading positions…</p>}
      {track.isError && (
        <p className="state error" style={{ margin: 0 }}>
          Couldn&apos;t read this track.
        </p>
      )}
      {track.data && points.length === 0 && (
        // Declared, mapped, and empty. Saying so beats a map of the whole
        // world, which reads as a track that failed to draw.
        <p className="canvas-widget-empty">No positions for this object yet.</p>
      )}
      {points.length > 0 && (
        <div className="sov-card-map" data-testid={`sov-track-${property.api_name}`}>
          <MapCanvas
            points={last
              ? [{ id: property.api_name, lat: last.lat, lon: last.lon, label }]
              : []}
            shapes={points.length > 1
              ? [{
                id: property.api_name,
                label,
                // [longitude, latitude], which is GeoJSON's order and the
                // opposite of the `lat`/`lon` the track arrives in — named
                // fields on one side and a positional pair on the other is
                // exactly where this gets reversed (§425).
                value: {
                  type: "LineString",
                  coordinates: points.map((p) => [p.lon, p.lat]),
                },
              }]
              : []}
            total={points.length}
            unplaceable={track.data?.unreadable ?? 0}
          />
        </div>
      )}
    </article>
  );
}

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
  style,
}: {
  workspaceId: string;
  property: ObjectTypeProperty;
  value: unknown;
  /** Evaluated by the caller, which is the one that holds the whole instance -
   * a rule may compare against a property this card was never given. */
  style: PropertyStyle | null;
}) {
  // p.11: "Objects with prominent geohash, **geoshape**, or geotemporal series
  // reference properties will render on a Map." Two of the three now: a
  // geopoint (one point is still a map — it answers "where is this" without
  // making somebody read a coordinate pair) and, since §426, a geoshape.
  //
  // **A shape gets a map on the same ground a point does, and it is a
  // stronger one**: a coordinate pair can at least be read, while a polygon's
  // coordinates are a paragraph nobody reads at all. That is why the card
  // draws the map rather than the summary `PropertyValue` shows in a table.
  const point = property.data_type === "geopoint" ? toLatLon(value) : null;
  const shape = property.data_type === "geoshape" && isGeometry(value) ? value : null;
  return (
    <article className="sov-card" data-property={property.api_name}>
      <h3 className="sov-card-label">{property.display_name || property.api_name}</h3>
      {point || shape ? (
        <div className="sov-card-map" data-testid={`sov-map-${property.api_name}`}>
          <MapCanvas
            points={point
              ? [{ id: property.api_name, ...point, label: property.display_name }]
              : []}
            shapes={shape
              ? [{ id: property.api_name, label: property.display_name, value: shape }]
              : []}
            total={1}
          />
        </div>
      ) : (
        <div className="sov-card-value">
          <PropertyValue
            workspaceId={workspaceId}
            dataType={property.data_type}
            valueFormat={property.value_format}
            structFields={property.struct_fields}
            style={style}
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
  hideHeader = false,
  dragIcon = false,
}: {
  workspaceId: string;
  typeId: string;
  instance: ObjectInstance;
  /** Workshop p.262's "Hide header", threaded down rather than reimplemented.
   * The Explorer and the traversal dialog never pass it; a module embedding
   * this view under a title of its own does. */
  hideHeader?: boolean;
  /** Workshop p.570's drag zone: "The icon in the object view widget header
   * can be dragged onto compatible drop zones". Only the Object View *widget*
   * passes it, in a running module, which is where there are drop zones. */
  dragIcon?: boolean;
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
      {!hideHeader && (
        <header className="sov-head">
          {/* p.15's own sentence, and the screen it names: the icon and
              colour "will be displayed in user applications **when a user
              views an object of this type**" (§449). Beside the type's name
              rather than the object's title — it is the *type* that is
              marked, and an object's own title is not. */}
          <p className="sov-type">
            <span
              className="ot-mark"
              data-testid="sov-type-mark"
              style={{ background: swatch(type.data), ...(dragIcon ? { cursor: "grab" } : {}) }}
              aria-hidden="true"
              draggable={dragIcon || undefined}
              title={dragIcon ? `Drag ${title} to a drop zone` : undefined}
              onDragStart={dragIcon ? (event) => {
                event.dataTransfer.setData(
                  OBJECT_MEDIA_TYPE, objectPayload(typeId, instance.primary_key),
                );
                event.dataTransfer.effectAllowed = "copy";
              } : undefined}
            >
              {glyph(type.data)}
            </span>
            {type.data.display_name}
          </p>
          <h2 className="sov-title">{title}</h2>
        </header>
      )}

      {prominent.length > 0 && (
        <div className="sov-cards" data-testid="sov-prominent">
          {prominent.map((p) =>
            // A series is not a value to print — it is a chart or a map, and
            // either needs a fetch the other card kinds do not: the instance
            // holds a series *id* and the points live in a dataset
            // (decision 0009).
            p.data_type === "time_series" ? (
              <SeriesCard
                key={p.api_name}
                workspaceId={workspaceId}
                typeId={typeId}
                instanceId={instance.id}
                property={p}
              />
            ) : p.data_type === "geotemporal_series" ? (
              <TrackCard
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
                style={conditionalStyle(p.conditional_format, instance.properties)}
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
                  {/* p.131's "in a table or application" (§349; db 0088).
                      **The ordinary list reduces and the prominent cards above
                      do not**, which is p.131's own distinction rather than an
                      omission: applications "enable you to view the complete
                      array on hover **or in expanded views**", and a card
                      given a whole row of its own is the expanded view. So the
                      reduced value is what a reader scanning the list sees,
                      and the full array is what a property promoted to a card
                      shows. `ReducedValue` falls through to the value itself
                      for every property that declares no reducer. */}
                  <ReducedValue
                    workspaceId={workspaceId}
                    property={p}
                    instance={instance}
                    style={conditionalStyle(p.conditional_format, instance.properties)}
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
