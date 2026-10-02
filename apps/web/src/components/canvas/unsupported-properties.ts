/** p.266 and p.595's unsupported property types (§693).
 *
 * > "Some large properties, such as Geoshape and Vector, are not loaded by
 * > default to improve performance. In View mode, users can select Load next
 * > to an unsupported property to reveal its value on demand. During
 * > configuration, unsupported properties are indicated with a warning icon
 * > and tooltip." (p.266)
 *
 * > "Object Table: To view an unsupported property's value in an object table
 * > widget, select ... button to reveal its value." (p.596)
 *
 * Geoshape is the one of p.595's two this ontology has; Vector is not a
 * property type here. The Map loads geoshapes, as p.597 says it does.
 */

export const UNSUPPORTED_TYPES: readonly string[] = ["geoshape"];

/** p.266's tooltip, said where a builder chooses the property. */
export const UNSUPPORTED_HINT =
  "Large: not loaded with the page, and shown when a reader asks for it (Load).";

export function isUnsupported(property: { data_type: string }): boolean {
  return UNSUPPORTED_TYPES.includes(property.data_type);
}

/** The api names a widget leaves out of its page, of the properties it shows. */
export function omittedOf(properties: readonly { api_name: string; data_type: string }[]): string[] {
  return [...new Set(properties.filter(isUnsupported).map((p) => p.api_name))];
}

/** A row's values for p.266's Hide null properties: an unsupported property
 * not loaded yet is not known to be null, so it is not hidden for it. */
export function valuesForHiding(
  values: Record<string, unknown> | undefined,
  omitted: readonly string[],
): Record<string, unknown> | undefined {
  if (!values || omitted.length === 0) return values;
  return { ...Object.fromEntries(omitted.map((name) => [name, true])), ...values };
}
