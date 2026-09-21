/** One object, named in a URL (`workshop` p.199; §416).
 *
 * > "Object set variables are limited to single objects, specified by their
 * > RID" (p.199)
 *
 * So p.199 is not the blanket refusal it reads as: one object *is* routable,
 * by an identifier rather than by a definition. This is the writing half —
 * `services/object_refs.py` is the reading half, and the two agree on one
 * format, which `test_routing.py` pins rather than trusting.
 *
 * **Two UUIDs joined by a colon**, the object type and the instance. Opaque
 * like p.199's RID, and deliberately so: a reference carrying the object's
 * properties would be a snapshot somebody could edit by hand before sending
 * the link on, and the recipient would have no way to tell.
 */

/** Between the type and the instance. Neither half can contain one, so
 * parsing needs no tie-breaking rule. */
export const REF_SEPARATOR = ":";

/** What a `single_object` variable holds — the shape `selectionOf` writes. */
export interface PickedObject {
  id?: unknown;
  object_type_id?: unknown;
  primary_key?: unknown;
  properties?: unknown;
}

/** The URL form of a picked object, or null when there is nothing to write.
 *
 * **Null rather than an empty string.** An empty parameter in a link is one
 * whose meaning somebody has to decide, and the meaning here is that the key
 * should not be in the address at all — which is what `routingParams` does
 * with a null.
 */
export function refFor(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  const picked = value as PickedObject;
  const typeId = picked.object_type_id;
  const instanceId = picked.id;
  if (typeof typeId !== "string" || !typeId) return null;
  if (typeof instanceId !== "string" || !instanceId) return null;
  return `${typeId}${REF_SEPARATOR}${instanceId}`;
}
