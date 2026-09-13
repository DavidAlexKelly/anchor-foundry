-- Where a multiple-choice parameter's allowed values come from (§335;
-- `action-types` p.33).
--
--     "Adding filters to non-object reference **multiple choice** or single
--      object reference parameters will determine the allowed values that are
--      selectable in the parameter's dropdown." (p.33)
--
--     "When configuring multiple choice parameter dropdown menus, action
--      editors can reduce allowed values to just those that are properties of
--      an object set… select `Get options from an object set`, configure the
--      desired object set, and select the property that includes all allowed
--      values for the parameter dropdown. **If only one linked object is
--      available in the resulting object set and the parameter is required, the
--      parameter dropdown will automatically prefill with the corresponding
--      property value.** The resulting multiple choice options will be derived
--      from the set of objects that the user has permission to view." (p.33)
--
-- **p.33's other half.** Its first sentence names two shapes a dropdown can be
-- narrowed on: a single object reference, which db 0083-0085 built, and a
-- *multiple choice* parameter that is not an object at all. This is the second.
-- The values are not objects — they are the values one property takes across a
-- set of objects, so "which Region" is answered by the Regions that exist
-- rather than by a list somebody retyped.
--
-- **Not a list of literals.** A column holding `["eu", "uk"]` would be the same
-- control and a worse one: p.33's whole point is that the options follow the
-- data, so a region added to the ontology appears in every form that offers
-- regions without anybody editing an action. A literal list is the thing that
-- goes stale silently, which is why p.33 describes deriving them and this
-- stores the derivation.

ALTER TABLE action_parameters
    ADD COLUMN options_from jsonb;

-- NULL rather than `'{}'`, for db 0085's reason: "no options" is a fact about
-- the parameter — it takes whatever is typed — and not a hole in it. Every
-- parameter written before today says exactly that, and none has to be
-- rewritten to keep behaving as it did.

COMMENT ON COLUMN action_parameters.options_from IS
    'p.33: where this parameter''s allowed values come from, as '
    '{"object_type_id", "property"} (db 0086). NULL means it has none and '
    'accepts whatever is typed, which is every parameter written before this.';

-- **No foreign key, for db 0085''s reason and with the same ○.** A jsonb column
-- cannot carry one. The consequence is smaller here than it is for 0083: a
-- dangling type id makes a dropdown with nothing in it, which the form says out
-- loud, rather than a submission refused with no way to see why. §325's cleanup
-- queue is still where a type is removed on purpose, and it does not yet report
-- an action parameter as a reason one will not go.
