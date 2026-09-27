/**
 * Which links an action's Create link / Delete link rules can set, and what a
 * rule on one asks for (`action-types` p.20; §136, §142, §553).
 *
 * The server decides (`actions.validate_definition`); this narrows the editor's
 * list to links it would accept, so nobody picks one to be refused on Save.
 */

import type { LinkType } from "@platform/types";

type Link = Pick<
  LinkType,
  "from_object_type_id" | "to_object_type_id" | "from_property" | "to_property" | "cardinality"
> & { join_dataset_id?: string | null };

/** A link one of this type's action rules can make or remove.
 *
 * A foreign-key link is set by writing its `from` side's property, so it must
 * join on a property (not the primary key, not nothing), and one-to-many at
 * most: no single foreign key expresses a many-to-many link. **A join-table
 * link is set by writing a pair** (§553; p.20's "many-to-many link between
 * objects that are passed via object reference parameters"), so it is
 * settable from either end. */
export function settableLink(link: Link, typeId: string | null): boolean {
  if (link.join_dataset_id) {
    return link.from_object_type_id === typeId || link.to_object_type_id === typeId;
  }
  return (
    (link.from_object_type_id === typeId ||
      (link.to_object_type_id === typeId && !!link.to_property)) &&
    link.cardinality !== "many_to_many" &&
    !!link.from_property &&
    link.from_property !== "$primary_key"
  );
}

/** Whether a rule on this link names the other object (`object`) rather than
 * the value to point this one at (`target`): on a foreign-key link's far side
 * the row written is the other object's, and on a join table the pair is this
 * object and another. */
export function namesObject(link: Link, typeId: string | null): boolean {
  return !!link.join_dataset_id || link.from_object_type_id !== typeId;
}
