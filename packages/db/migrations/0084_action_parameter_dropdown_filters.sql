-- Narrowing what an object parameter offers (§331; `action-types` p.33-36, p.40-41).
--
--     "Within the parameter configuration view, action editors can specify
--      filters … to limit the objects that show up in the dropdown across all
--      action interfaces. After configuring the filters, the action form will
--      render a dropdown with only objects that match the filter. **The value
--      selected is also validated before the action is executed.**" (p.34)
--
--     "The object dropdown only shows objects where the specified property
--      matches any of the provided values. The value can be statically defined
--      by the user, inferred from another parameter, or a property of an Object
--      Reference parameter. **If more than one value is provided to compare
--      against, the result will be an OR operation.**" (p.36)
--
-- **A jsonb column rather than a child table, and §329 went the other way.**
-- An override block is ordered and the order *is* the rule ("only the first one
-- will be executed"), so those rows have identity and a position. A filter list
-- has neither: p.36 gives each filter a property and a set of values, several
-- filters narrow together, and narrowing is commutative — so a table would be
-- giving rows an identity nothing reads and an order nothing means.
--
-- Each entry is `{"property": <api_name>, "values": [<side>, ...]}`, where a
-- side is decision 0007's vocabulary: `{"kind": "value", "value": ...}` or
-- `{"kind": "parameter", "parameter": <api_name>}`. **The same shape a
-- criterion's sides use**, because "where does this value come from" is a
-- question this platform has already answered once and a second vocabulary
-- would be a second answer.
--
-- p.36's third kind — a property of an object-reference parameter — is not in
-- that vocabulary and is not implemented; `docs/parity` carries it as a named
-- ○ rather than a silent gap.

ALTER TABLE action_parameters
    ADD COLUMN dropdown_filters jsonb NOT NULL DEFAULT '[]'::jsonb;

-- **These values are readable by anyone who can read the action type, and
-- p.40-41 is about exactly that.** Foundry's own warning: "Static value filters
-- in object dropdown validations are exposed to all users who can view the
-- action type. Use of these filters risks exposing property value combinations
-- to users without permissions to view the filtered objects."
--
-- p.41 says the mitigation is redaction — "a user will not be able to see the
-- new object dropdown filters in the action type definition in the interface or
-- while inspecting the response in the backend" — and that is done in the route
-- rather than here, because the answer depends on *who is asking* and a column
-- cannot know. A viewer gets the dropdown; only somebody who may edit the
-- action gets the sentence that produced it.
--
-- p.41 then admits the leak Foundry could not close: the filter reaches the
-- browser as an object set, so "users could review the network request
-- containing this object set". This platform's form never receives the filter
-- at all — it asks for the resulting objects — so that particular hole is
-- closed here by the shape rather than by a decision, and the roadmap says so.

COMMENT ON COLUMN action_parameters.dropdown_filters IS
    'p.36''s object dropdown filters (db 0084): a list of {property, values}, '
    'ANDed together, each value list read as an OR. Redacted from the '
    'definition for callers who may not edit the action type (p.40-41).';
