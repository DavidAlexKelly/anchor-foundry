/** Sections on an action form, the parts a document decides (§328;
 * `action-types` p.122-124).
 *
 * > "The action form can be customized with sections. These sections provide a
 * > logical grouping of parameters to organize an action form. Sections also
 * > support columns, descriptions, and conditional overrides." (p.122)
 *
 * > "In the Form tab, click Add section… you can add a title, choose a column
 * > layout, and optionally write a user-facing description. **The description
 * > is not stylized and, unlike parameter descriptions, will always be shown in
 * > the section itself, not in a tooltip.**" (p.123)
 *
 * > "Sections are also collapsible, can be hidden entirely… A section can be
 * > hidden at first and only shown based on a prior parameter." (p.123)
 *
 * > "Parameters and sections display in the form based on their order in this
 * > Form Content section." (p.124)
 *
 * ---
 *
 * **Whether a condition is met is not decided here, and that is the whole
 * point.** p.123's conditional override is decision 0007's `{left, operator,
 * right}` — the same shape a submission criterion uses — and evaluating it in
 * TypeScript would be a second reading of a document the definition editor
 * writes and `check_criteria` runs. `POST .../visible-sections` answers it, and
 * what is in this file is what the *form* decides given that answer: which
 * sections are drawn, which parameters are inside them, which are left in the
 * body, and what to say about the ones that are neither.
 *
 * That is not a shortage of nerve. Reading the condition to learn **which
 * parameters it mentions** is here, in `conditionParameters`, because that is a
 * question about the document's shape rather than about its meaning — and it is
 * what lets a form with plain sections never make the round trip at all.
 *
 * **A section changes what a form looks like and nothing else.** Every function
 * below returns what to draw. A hidden section's parameters are still seeded,
 * still sent and still validated; the server's own module says the same thing
 * in the same words, because a form that quietly dropped values would mean the
 * same action did different things depending on which boxes were on screen.
 */

export interface FormSection {
  id: string;
  title: string;
  description: string;
  columns: number;
  collapsible: boolean;
  collapsed: boolean;
  hidden: boolean;
  /** decision 0007's condition, or `null` for a section that is always on. */
  visible_when: Record<string, unknown> | null;
  /** The parameters inside it, by `api_name`, in the order they are drawn. */
  parameters: string[];
}

/** As much of an action's parameter as a form layout needs. */
export interface FormParameter {
  api_name: string;
  display_name?: string;
  required?: boolean;
  /** p.25's hidden parameter: supplied by the caller and never drawn, whatever
   * any section says about it. */
  hidden?: boolean;
}

function side(spec: unknown): Record<string, unknown> {
  return spec && typeof spec === "object" && !Array.isArray(spec)
    ? (spec as Record<string, unknown>)
    : {};
}

/** Every parameter any section's condition reads.
 *
 * **The reason a plain form never asks the server anything.** A section with no
 * condition cannot change its mind, and one that is hidden entirely is not
 * asking a question — so if this comes back empty there is nothing to watch and
 * nothing to send.
 *
 * Reading `left` and `right` for `kind: "parameter"` is not evaluating the
 * condition: an operator this build has never heard of still names its
 * parameters here, and a condition that mentions the current user rather than a
 * parameter contributes nothing — which is correct, because who is asking does
 * not change while a form is open.
 */
export function conditionParameters(sections: FormSection[]): string[] {
  const named = new Set<string>();
  for (const section of sections ?? []) {
    if (section.hidden) continue;
    const condition = side(section.visible_when);
    for (const key of ["left", "right"]) {
      const spec = side(condition[key]);
      if (spec.kind !== "parameter") continue;
      const name = String(spec.parameter ?? "").trim();
      if (name) named.add(name);
    }
  }
  return [...named].sort();
}

/** Whether any section's visibility is a question at all.
 *
 * **This, not `conditionParameters`, is what decides whether to ask the
 * server** — and the first draft used the other one, which was a real defect
 * and the reason this function exists. p.50 gives two condition templates, and
 * only one of them names a parameter: a section shown to the person a
 * criterion names ("based on current user") reads nothing out of the form at
 * all, so `conditionParameters` came back empty, the form decided it had
 * nothing to ask about, and that section could never be drawn for anybody.
 *
 * The two questions are genuinely different and were folded into one:
 * *whether* the server has to be asked (this) and *when the answer goes stale*
 * (`conditionKey`). A condition about the current user is asked once and never
 * again, because who is asking does not change while a form is open.
 */
export function hasConditions(sections: FormSection[]): boolean {
  return (sections ?? []).some((s) => !s.hidden && !!s.visible_when);
}

/** A stable key over only the values the conditions read.
 *
 * What the form's query is keyed on, so typing in a parameter no section asks
 * about does not re-ask the server — and so the answer for values already seen
 * is the cached one rather than a round trip and a flicker.
 *
 * **A constant when no condition names a parameter**, which is right rather
 * than a degenerate case: a section shown to one person (p.50's "based on
 * current user") has an answer that cannot change while the form is open, so
 * one key means one round trip. Whether to make that round trip is
 * `hasConditions`, not this — see the note there.
 */
export function conditionKey(
  sections: FormSection[],
  values: Record<string, unknown>,
): string {
  const named = conditionParameters(sections);
  return JSON.stringify(named.map((name) => [name, values?.[name] ?? null]));
}

/** Which sections are drawn, given the server's answer.
 *
 * p.123's three states and one more the page has that the server does not:
 *
 * * `hidden` — "hidden entirely". Out, whatever else says.
 * * no condition — always in. Every section made before anybody configured one.
 * * a condition, and an answer in hand — in when the answer names it.
 * * a condition, and **no answer yet** — out.
 *
 * The last is p.123's own wording: a section is "hidden at first and only shown
 * based on a prior parameter". Drawing it while the question is in flight would
 * put the boxes on screen for a moment and then take them away, which is worse
 * than the wait — and it is the same direction the server fails in when it
 * cannot read a condition at all.
 */
export function drawnSections(
  sections: FormSection[],
  visible: string[] | undefined,
): FormSection[] {
  const shown = visible ? new Set(visible) : null;
  return (sections ?? []).filter((section) => {
    if (section.hidden) return false;
    if (!section.visible_when) return true;
    return shown !== null && shown.has(section.id);
  });
}

export interface DrawnSection {
  section: FormSection;
  parameters: FormParameter[];
}

export interface FormLayout {
  /** Parameters in no section at all, drawn in the form body. */
  loose: FormParameter[];
  /** p.124's Form Content order, filtered to what is on screen. */
  sections: DrawnSection[];
}

/** p.124's form, arranged.
 *
 * **The body first, then the sections.** p.124 says "Parameters and sections
 * display in the form based on their order in this Form Content section" — one
 * order over both — and this build stores two: a section's `sort_order` and a
 * parameter's. A parameter that has never been put in a section keeps its place
 * among the parameters, and the sections follow in theirs. Interleaving them
 * needs a single ordering across both kinds, which is a change to the document
 * rather than to this function, and `docs/parity` carries it as its own row.
 *
 * A parameter named by a section is drawn **only** in that section: absent from
 * the body when the section is on screen, and absent from the form entirely
 * when it is not. Falling back to the body would undo p.123's hiding by the
 * most direct route available.
 */
export function formLayout(
  parameters: FormParameter[],
  sections: FormSection[],
  visible: string[] | undefined,
): FormLayout {
  // p.25 first, and over every parameter rather than only the loose ones: a
  // hidden parameter is supplied by whatever runs the action, and putting one
  // in a section does not make it something to fill in.
  const drawable = (parameters ?? []).filter((p) => !p.hidden);
  const byName = new Map(drawable.map((p) => [p.api_name, p]));
  // Claimed by *any* section, drawn or not.
  const claimed = new Set(
    (sections ?? []).flatMap((s) => s.parameters ?? []),
  );
  return {
    loose: drawable.filter((p) => !claimed.has(p.api_name)),
    sections: drawnSections(sections, visible).map((section) => ({
      section,
      parameters: (section.parameters ?? [])
        .map((name) => byName.get(name))
        .filter((p): p is FormParameter => !!p),
    })),
  };
}

/** Required parameters the form is not showing anywhere.
 *
 * The case p.123 does not discuss and a builder will reach on their second
 * afternoon: a required parameter inside a section that is hidden, or whose
 * condition is not met. The server still requires it, so the submission is
 * refused — and a form that said "Priority is required" beside no Priority box
 * is §214's shape, a control that looks like it works.
 *
 * So the form keeps the button disabled, which is true, and says something a
 * reader can act on: see `unreachableNote`.
 */
export function requiredElsewhere(
  parameters: FormParameter[],
  sections: FormSection[],
  visible: string[] | undefined,
): FormParameter[] {
  const layout = formLayout(parameters, sections, visible);
  const onScreen = new Set([
    ...layout.loose.map((p) => p.api_name),
    ...layout.sections.flatMap((d) => d.parameters.map((p) => p.api_name)),
  ]);
  return (parameters ?? []).filter(
    (p) => !p.hidden && p.required && !onScreen.has(p.api_name),
  );
}

export function labelOf(parameter: FormParameter): string {
  return parameter.display_name || parameter.api_name;
}

/** What to say about `requiredElsewhere`, or `null` when there is nothing.
 *
 * Addressed to whoever can fix it rather than to whoever is stuck: the reader
 * of a form cannot open a section somebody hid, and telling them to fill in a
 * field would be an instruction they cannot follow.
 */
export function unreachableNote(missing: FormParameter[]): string | null {
  if (!missing || missing.length === 0) return null;
  const names = missing.map(labelOf).join(", ");
  return missing.length === 1
    ? `${names} is required but is in a section this form does not show. ` +
      "Whoever arranged the form has to move it or show the section."
    : `${names} are required but are in sections this form does not show. ` +
      "Whoever arranged the form has to move them or show the sections.";
}

/** p.123: "A section can be divided into one or two columns." */
export const COLUMN_CHOICES = [1, 2];

export function columnsOf(section: { columns?: unknown }): number {
  return section?.columns === 2 ? 2 : 1;
}

export function columnsLabel(columns: unknown): string {
  return columns === 2 ? "Two columns" : "One column";
}

/** Whether a section starts folded.
 *
 * **`collapsed` means nothing without `collapsible`**, which the migration says
 * in the column's own comment: a section folded with no way to open it would be
 * p.123's "hidden entirely" wearing the wrong name, and a builder who ticked
 * one box and not the other would have made a form whose fields cannot be
 * reached without knowing that.
 */
export function collapsedInitially(section: FormSection): boolean {
  return !!section?.collapsible && !!section?.collapsed;
}

/** One line about a section, for p.124's Form tab list. */
export function sectionSummary(section: FormSection): string {
  const count = (section?.parameters ?? []).length;
  const parts = [
    count === 1 ? "1 parameter" : `${count} parameters`,
    columnsLabel(section?.columns).toLowerCase(),
  ];
  if (section?.hidden) parts.push("hidden");
  else if (section?.visible_when) parts.push("shown on a condition");
  if (section?.collapsible) {
    parts.push(collapsedInitially(section) ? "collapsible, starts folded" : "collapsible");
  }
  return parts.join(" · ");
}

/** The parameters a given section may still be given.
 *
 * **Narrowing what is declarable, not validating.** The server refuses a
 * parameter that is in two sections, and this is why nobody reaches that
 * refusal by the obvious route: the dropdown for section *n* does not offer the
 * ones section *m* already holds. A parameter this section holds is still
 * offered — removing it from its own list would make the control forget what it
 * is showing.
 */
export function availableParameters(
  parameters: FormParameter[],
  sections: FormSection[],
  index: number,
): FormParameter[] {
  const elsewhere = new Set(
    (sections ?? []).flatMap((s, i) => (i === index ? [] : s.parameters ?? [])),
  );
  return (parameters ?? []).filter((p) => !elsewhere.has(p.api_name));
}

/** Put a parameter in one section, taking it out of wherever it was.
 *
 * p.124 offers two ways to put a parameter in a section and neither is "in
 * both". A move is one edit as far as the builder is concerned, so it is one
 * here too — the alternative is a Form tab that can sit in a state the server
 * refuses until somebody notices which other section still claims the name.
 */
export function placeParameter(
  sections: FormSection[],
  index: number,
  name: string,
): FormSection[] {
  return (sections ?? []).map((section, i) => {
    const without = (section.parameters ?? []).filter((p) => p !== name);
    return i === index
      ? { ...section, parameters: [...without, name] }
      : { ...section, parameters: without };
  });
}

export function removeParameter(
  sections: FormSection[],
  index: number,
  name: string,
): FormSection[] {
  return (sections ?? []).map((section, i) =>
    i === index
      ? { ...section, parameters: (section.parameters ?? []).filter((p) => p !== name) }
      : section,
  );
}

/** Move a section up or down p.124's Form Content list.
 *
 * A no-op at the ends rather than a wrap: a list that jumped from top to bottom
 * because somebody pressed the arrow once too often would be a reorder nobody
 * asked for, and the button is disabled there anyway.
 */
export function moveSection(
  sections: FormSection[],
  index: number,
  delta: number,
): FormSection[] {
  const next = [...(sections ?? [])];
  const to = index + delta;
  if (index < 0 || index >= next.length || to < 0 || to >= next.length) return next;
  const moved = next.splice(index, 1);
  next.splice(to, 0, ...moved);
  return next;
}

/** A blank section, as Add section leaves it (p.123). */
export function blankSection(existing: FormSection[]): FormSection {
  const taken = new Set((existing ?? []).map((s) => s.title));
  let title = "Section";
  for (let n = 2; taken.has(title); n += 1) title = `Section ${n}`;
  return {
    id: "",
    title,
    description: "",
    columns: 1,
    collapsible: false,
    collapsed: false,
    hidden: false,
    visible_when: null,
    parameters: [],
  };
}

/** p.123's "shown based on a prior parameter", as the Form tab edits it.
 *
 * The stored shape is decision 0007's `{left, operator, right}` — general
 * enough to compare two parameters or ask about the current user — and the
 * editor offers the one case p.123 actually describes: a prior parameter
 * against a value. **Read back tolerantly**: a condition written by hand or by
 * an import may be something this control cannot express, and `expressible`
 * says so rather than the editor quietly rewriting it into something it can.
 */
export interface ConditionDraft {
  /** The prior parameter, or `""` for a section with no condition. */
  parameter: string;
  operator: string;
  value: string;
  /** Whether the control can show what is stored without changing it. */
  expressible: boolean;
}

export function conditionDraft(section: FormSection): ConditionDraft {
  const condition = side(section?.visible_when);
  if (!section?.visible_when || Object.keys(condition).length === 0) {
    return { parameter: "", operator: "is", value: "", expressible: true };
  }
  const left = side(condition.left);
  const right = side(condition.right);
  const parameter = left.kind === "parameter" ? String(left.parameter ?? "") : "";
  const value = right.kind === "value" ? String(right.value ?? "") : "";
  return {
    parameter,
    operator: String(condition.operator ?? "is"),
    value,
    // A condition comparing two parameters, or asking about the current user,
    // is legal and the server evaluates it — this control just cannot draw it,
    // and a dropdown that silently reduced it to "no condition" would delete a
    // rule on the next save.
    expressible: !!parameter && right.kind === "value",
  };
}

/** The condition a draft stores, or `null` for "always shown".
 *
 * An empty parameter is not a condition: p.123's conditional override names a
 * prior parameter, and a half-filled row in a settings panel is what somebody
 * who changed their mind leaves behind. `null` and a condition that happens to
 * be true are different things — only the first survives the parameter being
 * renamed.
 */
export function conditionValue(draft: ConditionDraft): Record<string, unknown> | null {
  if (!draft?.parameter?.trim()) return null;
  return {
    left: { kind: "parameter", parameter: draft.parameter.trim() },
    operator: draft.operator || "is",
    right: { kind: "value", value: draft.value },
  };
}

/** Carry a parameter rename through the form.
 *
 * The same edit `patchParameter` makes to rules and criteria, for the same
 * reason: a section still naming the old parameter makes the server refuse the
 * save, and the refusal is about a row the person did not touch. A rename to
 * nothing is not a rename — an api_name is cleared mid-typing on the way to the
 * next one, and taking the parameter out of its section at that moment would
 * lose the arrangement for a keystroke.
 */
export function renameParameter(
  sections: FormSection[],
  before: string,
  after: string,
): FormSection[] {
  if (!before || !after || before === after) return sections ?? [];
  return (sections ?? []).map((section) => {
    const condition = conditionDraft(section);
    const renamed = condition.expressible && condition.parameter === before
      ? conditionValue({ ...condition, parameter: after })
      : section.visible_when;
    return {
      ...section,
      parameters: (section.parameters ?? []).map((p) => (p === before ? after : p)),
      visible_when: renamed,
    };
  });
}

/** Take a parameter the action no longer declares out of every section.
 *
 * Deleting a parameter is the other edit with consequences here. The server
 * would refuse the form for naming something that is not a parameter — true,
 * and about a section the person was not looking at.
 */
export function forgetParameters(
  sections: FormSection[],
  declared: FormParameter[],
): FormSection[] {
  const known = new Set((declared ?? []).map((p) => p.api_name));
  return (sections ?? []).map((section) => ({
    ...section,
    parameters: (section.parameters ?? []).filter((name) => known.has(name)),
  }));
}
