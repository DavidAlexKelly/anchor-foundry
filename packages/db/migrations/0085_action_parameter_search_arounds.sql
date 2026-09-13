-- Where an object dropdown's objects come from (§333; `action-types` p.34,
-- p.36-37).
--
--     "Within the parameter configuration view, action editors can specify
--      filters **and Search Arounds** to limit the objects that show up in the
--      dropdown across all action interfaces." (p.34)
--
--     "The starting set for the query is set to all objects of the object type
--      by default, but this can be changed to any other type. The starting set
--      could also be set to an ObjectReference list parameter." (p.36)
--
--     "A Search Around would create a new set by traversing a link on every
--      object in the current set. For example, `Github Issue of Current
--      Employee` would take the `Employees` in the current set and create a
--      resulting set of `Github Issues` linked to those `Employees`." (p.37)
--
-- **db 0084's filters narrow a set; this says which set.** Until now the answer
-- was always "every object of the parameter's declared type", which is p.36's
-- default and was the only thing this build could express. p.37's example
-- cannot be written with a filter at all: "the Github Issues of *this*
-- Employee" is not a property comparison, it is a walk.
--
-- One jsonb column rather than a table of hops, and unlike 0084's filters the
-- argument is not commutativity — hops are emphatically ordered. It is that a
-- chain is read and written whole. There is no operation on this platform that
-- adds a hop to the middle of a walk, or reads the second one without the
-- first; `derived_properties` stores the same shape as `links` inside one jsonb
-- `derivation` for the same reason, and this deliberately matches it.

ALTER TABLE action_parameters
    ADD COLUMN dropdown_search_around jsonb;

-- NULL rather than `'{}'::jsonb`, and rather than 0084's `NOT NULL DEFAULT
-- '[]'`. An empty list of filters is a real, meaningful state — "narrow this by
-- nothing" — whereas an empty *source* is not: a dropdown always starts
-- somewhere, and the somewhere for every parameter written before today is
-- p.36's default. NULL says "the default", which is a fact about the parameter
-- rather than a hole in it, and it means no row has to be rewritten to keep
-- behaving as it did.

COMMENT ON COLUMN action_parameters.dropdown_search_around IS
    'p.36-37: where this object dropdown''s objects come from, as '
    '{"start": {...}, "hops": [{"link_type_id", "far_type_id"}]} (db 0085). '
    'NULL is p.36''s default - every object of the type in object_type_id.';

-- **No foreign key to link_types or object_types, which 0083 has and this does
-- not.** A jsonb column cannot carry one, and the difference in consequence is
-- what makes that acceptable here: 0083's `object_type_id` decides whether a
-- submission is *refused*, so a dangling id there would refuse everything with
-- no way to see why. A dangling hop makes a dropdown that cannot be built, and
-- `object_set_eval.resolve_traversal` already refuses a link that does not
-- connect the set being traversed - by name, at the moment somebody opens the
-- form. §325's cleanup queue is where a link type is removed on purpose, and
-- the ○ that goes with this column is that it does not yet report an action
-- parameter as a reason a link type will not go.
