# 0024 — Link constraints on interfaces

**Status:** decided; §759 builds the model and its checks, §760 the screens, §761 the action rules that use it.
**Parity items:** `docs/parity/ontology.md` §1.5 (*Interfaces*: "○: links on an interface"), §5 (*Actions on interfaces*: "○: p.63-64's create and delete interface link rules").
**Source:** `docs/pal/foundry_ontology.pdf` p.60; `docs/pal/foundry_action-types.pdf` p.63-64, cited `(p.N)`.
**Follows:** §251's interfaces (db 0065), which took the Interfaces row's "design it from the fragments and mark what was guessed". This decision does the same for links.

---

## What the document says

`ontology` p.60 lists links among what an interface describes, beside properties and actions. The only other place that says anything about them is two action rules:

> "'Create interface link' rules allow you to create links using an interface link constraint defined on an interface … Select the interface link constraint defined on the interface. If the link constraint is between two interfaces, both the source and destination parameters will be automatically generated as interface reference parameters. If the link constraint is between an interface and an object type, the source will be an interface reference parameter and the destination will be an object reference parameter." (p.63)

> "If there are multiple concrete link implementations on the object type for the link constraint, the action will fail." (p.63) / "… the action will attempt to delete all the concrete link implementations." (p.64)

That settles three things:
* a **link constraint** belongs to an interface;
* it points at **another interface or an object type**;
* an implementing object type keeps it with **concrete link implementations**, possibly several.

Nothing says how a constraint is declared or how an implementation names its concrete links. Those are guessed below, and marked.

## 1. A constraint is part of the interface's shape

`interface_link_constraints` (db 0148) holds an interface's own constraints. Each has an `api_name` (named like a link type, since it stands for one), a display name and description, **exactly one** target (`target_interface_id` or `target_object_type_id`), and `required`.

* **Guessed:** `required`, defaulting to true, mirrors `interface_properties.required`. Nothing in the document makes a link optional; the property rule's reason (p.62's capabilities with optional parts) carries over.
* **Inherited** through `extends` like properties: an interface's effective constraints are its own, then each ancestor's. The same name pointing at the same target is agreement; pointing at different targets is refused, since nothing could keep both.
* **Not built:** cardinality on the constraint. The document's only cardinality remark (p.63's "creating a one-to-many link modifies the foreign key") is about the concrete link type, which already has one.

A constraint's target is refused if it is not in the workspace. Deleting what a constraint points at is refused with a sentence naming the constraint: an interface, from `delete_interface`, and an object type, from `delete_type`. The foreign key (`NO ACTION`, so an interface linking to itself can still go) is the backstop.

## 2. An implementation keeps it with its own link types

`object_type_interfaces.link_mapping` is `{constraint api_name: [link type id, …]}`, beside `property_mapping`. A list, because p.63-64 speak of several concrete links per constraint.

A link type keeps a constraint when one of its ends is the implementing type and **the other end is the target**: that object type, or a type implementing that interface. Implementing here includes through extension, since a type implementing `Squad extends Team` is a Team. A self-link counts, with the type itself as the other end. Saving an implementation is refused when:
* a required constraint has no link type;
* a link type does not touch the type;
* a link type's other end is the wrong thing, and the sentence names both;
* a link type is listed twice;
* the mapping names a constraint the interface does not declare.

"Implements the target" is read from the list being saved for the type itself, so a type can keep a constraint back to the interface it is implementing in the same save.

As with properties, editing an interface does not re-check its implementations. A new required constraint is refused at the next save of each implementation, not cascaded into somebody else's object type. A link type that keeps a constraint cannot be deleted until the implementation stops naming it.

**Omitted means unchanged**, on both writes: an interface update without `link_constraints`, and an implementation entry without `link_mapping`. A client that predates links must not delete them by saving.

## 3. What uses it

* **§760**: the Ontology Manager's interface editor declares constraints, and the implementation panel picks each one's link types.
* **§761**: p.63-64's Create and Delete interface link rules.
