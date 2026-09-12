-- What an object parameter holds (§330; `action-types` p.25, p.33-37).
--
--     "Adding filters to non-object reference multiple choice or single object
--      reference parameters will determine the allowed values that are
--      selectable in the parameter's dropdown." (p.33)
--
--     "Within the parameter configuration view, action editors can specify
--      filters and Search Arounds to limit the objects that show up in the
--      dropdown across all action interfaces. After configuring the filters,
--      the action form will render a dropdown with only objects that match the
--      filter. **The value selected is also validated before the action is
--      executed.**" (p.34)
--
-- **p.33-37 is about narrowing a dropdown this platform does not draw.** An
-- `object` parameter has been a text box since db 0044: the person submitting
-- the action is expected to know an object's uuid and type it in. That is
-- §214's control that looks like it works, and it is the reason this column
-- comes before the filters do — a filter on a list nobody can see is a setting
-- with no observable effect.
--
-- **The type is a fact about the parameter, and until now it was a guess.**
-- `actions.object_parameter_types` reads it off the action's rules, because
-- every rule that consumes an object parameter says which type it means, and
-- its own docstring names this migration as the fix: "It is a default rather
-- than a fact, so the day `action_parameters` grows an `object_type` column
-- this reads it instead and the guess goes."
--
-- The guess does not go entirely, and deliberately. Every parameter written
-- before today has NULL here, and the rules still say what they always said —
-- so the column is read when it is set and the rules answer when it is not. An
-- ALTER that demanded a type would have to invent one for every existing row,
-- which is the same guess with no way to tell it from a decision.

ALTER TABLE action_parameters
    ADD COLUMN object_type_id uuid REFERENCES object_types(id) ON DELETE RESTRICT;

-- `ON DELETE RESTRICT` rather than CASCADE or SET NULL, and this is the only
-- interesting choice here. Deleting an object type that an action's parameter
-- points at cannot quietly succeed: CASCADE would take the parameter (and with
-- it the action's whole meaning), and SET NULL would leave an action asking for
-- an object of no particular type, which is exactly the state this column
-- exists to end. §325's cleanup queue is where a type is removed on purpose,
-- and it reports what refuses to go.

CREATE INDEX idx_action_parameters_object_type
    ON action_parameters (object_type_id)
    WHERE object_type_id IS NOT NULL;

COMMENT ON COLUMN action_parameters.object_type_id IS
    'p.25''s object parameter: which object type its value is an instance of '
    '(db 0083). NULL means the type is still inferred from the action''s rules, '
    'as it was for every parameter written before this column existed.';
