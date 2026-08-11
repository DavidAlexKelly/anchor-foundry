# 0007 — Action parameters and rules

**Status:** decided; the model is **built** in migration 0044 (`STATUS.md` §127), submission criteria in 0045 (§128), and the editing API in §129. The editor UI and the parameter-driven form are not.
**Parity item:** `docs/parity/ontology.md` §5, and the one it says to do first.
**Source:** `docs/pal/foundry_action-types.pdf` (174 pp). Citations are `(p.25)`.

---

## The problem, in one sentence

**Our action model has no word for "what the user typed".**

`action_types.editable_properties` is a list of property names. Executing an action posts `{property: value}` and each value is written to the property of the same name. So the input *is* the output: one list plays both parts, and there is nowhere to put anything that is not literally a property being overwritten.

Foundry separates them, and the separation is the whole of §5:

> "**Parameters** are the inputs of an action type. They are the interface between the Rules and other Foundry applications… Parameters are treated like variables that contain external values. Each parameter is defined by a type, which dictates what kind of values it can take." (p.25)

> "In an action type, **rules** define the ways objects should change when the action is applied. Many action types can be defined using simple rules which allow you to create, modify, and delete objects, or create and delete links between objects." (p.75)

Everything else `ontology.md` §5 lists as absent hangs off that one distinction, and each is unbuildable without it:

| Feature | Why it needs parameters |
|---|---|
| Default values (p.27) | a default belongs to an *input*; a property already has a value |
| Submission criteria (p.9, p.13) | a condition over inputs, checked before anything is written |
| Filtered parameter dropdowns | a constraint on what may be *typed*, not on what is stored |
| Create / delete objects and links (p.75) | rules that write no property at all |
| Editing multiple objects in one transaction | one input set, several targets |
| Function-backed actions | a function takes arguments — which is what parameters are |

## The decision

**Three tables, replacing one JSON column.**

```
action_types            (unchanged, less editable_properties)
action_parameters       id, action_type_id, api_name, display_name,
                        data_type, required, default_value, hidden,
                        sort_order
action_rules            id, action_type_id, kind, config, sort_order
```

### Parameters are typed, ordered, and not necessarily visible

`data_type` reuses `property_data_type` — the vocabulary the ontology already has — plus `object` for "a parameter that takes an object", which p.25's own example needs: *"the object type parameter will take the value of a selected Ticket object and the Status parameter contains the future status."*

`hidden` is from p.25 — "each parameter can be individually configured as to whether they are exposed in the form or not". Its use is not decoration: p.25's second example passes a *previous* value into a hidden parameter so a rule can compare against it.

### Rules are a small closed vocabulary, not an expression language

`kind` ∈ `modify_object`, `create_object`, `delete_object`, `create_link`, `delete_link`. `config` is JSON whose shape depends on `kind`, validated at save time by the service — the same arrangement `workshop_events` already uses for effects, and for the same reason: one place decides what a config means, and a second set of rules in the type system would be a second thing to keep in step.

**Deliberately not a general expression language.** p.75 distinguishes "simple rules" from cases where "simple rules are not sufficient", and answers the second with *functions*. Functions are `[fn]` in the parity spec and out of scope; inventing a half-expression-language to avoid them would be building the thing we said we would not build, badly.

### Submission criteria are a separate list, checked before any write

Criteria are conditions over parameter values, evaluated server-side before the first rule runs. **A criterion that fails refuses the whole action** — p.13's example is precisely that: an action that "should not be possible to run" when the ticket is not open. The refusal names the criterion, because a form that greys out with no reason is worse than one that refuses with one.

*Built in 0045, with two things this section did not anticipate.* The conditions are over parameters **and the current user**: p.140 is explicit that criteria are how Foundry does per-action permissions ("simple submission criteria can require a specific user ID or group ID"), so leaving the user out would have meant building the mechanism and omitting its main use. And the failure message is p.56's, stored per criterion and required — "the failure message informs the user about why they are blocked from submitting an Action".

## What this costs, honestly

**A migration with a real conversion, not a default.** Every existing action type has `editable_properties: ["status", "priority"]` and no parameters. The conversion is mechanical and total: each name becomes one parameter of the property's own type, plus one `modify_object` rule writing that parameter to that property. That is exactly what the current model means, spelled out — so no action changes behaviour, and the JSON column can be dropped in the migration after it.

**Two call sites move.** `routes/actions.py` executes; Workshop's `run_action` effect (`STATUS.md` §60) supplies values. Both currently speak `{property: value}`, which after conversion is `{parameter_api_name: value}` — the same wire shape by construction, because the conversion names each parameter after the property it writes. **That is the property that makes this migration safe**, and it is worth not losing: a rename of a converted parameter is a breaking change to any saved Workshop module that calls it, so the parameter editor must refuse to rename one that a module references, the way §1.2a refuses deleting a variable in use.

**The form gets harder before it gets better.** `CanvasActionForm` renders one input per editable property today. It will render one per *visible* parameter, prefilled from defaults, with hidden ones supplied by the caller and never drawn.

## What this does not do

- **No functions.** `[fn]` stays `[fn]`.
- **No side effects** — notifications, webhooks, schedule builds (p.106, p.119) are §5.2 and separate.
- **No parameter configuration overrides** (p.25's "overrides to change the configuration of a following parameter"). Real, documented, and a second mechanism; it needs parameters to exist first.
- **No multi-object transactions yet.** The schema admits them — a rule names its target — but the executor writes one object per action until there is a transaction boundary worth the name. `ontology.md` §8 asks that an action editing two objects where the second fails leaves *neither* applied, and our write-back appends a dataset version per write. Honouring that means one version per *action*, not per rule, and that is its own piece of work.

## How you would know it worked

Per the repo standard, each of these must be made to fail by removing the thing it tests:

- ✅ **The conversion changes nothing.** Take an existing action type, run the migration, execute it with the same payload, and assert the same property values land. Mutation: convert to the wrong property, and it goes red. — `tests/test_action_conversion.py` builds a database at 0043, seeds a legacy action type and migrates the rest of the way; five mutations of the migration's own SQL were checked.
- ◑ **A hidden parameter is not in the form and is still applied.** Both halves, one test — a hidden parameter that silently did nothing would pass a form check. — the *applied* half is checked; the form half arrives with the form.
- ✅ **A failed criterion refuses the action and names the criterion.** Mutation: skip the check, and the write goes through. — `tests/test_action_criteria.py`; eleven mutations checked, two of which found tests that could not fail (the `is_less_than` boundary, and emptiness written as falsiness).
- ✅ **A criterion is checked before the first rule runs.** Assert no dataset version is created by a refused action — "refused" and "refused after writing half of it" look the same from the caller. — and no `action_runs` row either, since the check precedes opening one.
- ✅ **Renaming a parameter a Workshop module calls is refused**, naming the module. — §129, and the mutation that removes the refusal goes red. Checked against what is *going* rather than what is arriving, because a parameter that survives under a new name is, to every saved module, a parameter that vanished.

## The alternative that was rejected

**Keep `editable_properties` and bolt criteria onto it.** Cheaper, and it buys exactly one of the seven features in the table above. Every other one still needs an input that is not a property — and each would then need its own side-channel, which is how a model ends up with four ways to say the same thing. The separation is the point; adding it later costs the same migration plus the interim mistakes.
