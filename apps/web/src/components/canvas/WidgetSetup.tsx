"use client";

/**
 * The Widget setup tab, organised variables-first (Foundry `workshop` p.65-67).
 *
 * > "This is where a module builder will configure the input and output
 * > variables of a widget … as well as any additional configuration and
 * > display options." (p.65)
 *
 * Foundry's worked example is a Filter List, and the order it describes is the
 * order somebody has to think in: the Object Set that populates the widget,
 * then the filter options that set makes answerable, then the Filter Output
 * other widgets read. A flat list of controls in whatever order the widget
 * author wrote them puts those three kinds of decision on the same footing.
 *
 * **The one behaviour here is p.66's progressive disclosure.** "This
 * configuration option is revealed in more detail once the Object Set is
 * populated" - so `waitingFor` names the unbound input and the configuration
 * stays out of the way until it can be answered. The rule itself is in
 * `widget-setup.ts`, pure and tested, because getting it wrong is silent in
 * both directions.
 *
 * A widget with nothing to put in a section simply omits it: an empty
 * "Outputs" heading is a promise of a control that does not exist.
 */

import type { ReactNode } from "react";

import {
  SECTION_HINTS, SECTION_LABELS, configReady, configWaitingFor,
} from "./widget-setup";

export function WidgetSetup({
  inputs,
  configuration,
  outputs,
  /** The current values of the input bindings, keyed by prop name. */
  bindings = {},
  /** Which of them the configuration cannot be answered without (p.66). */
  requires = [],
  /** Human names for those, so the wait message reads as a sentence. */
  labels = {},
}: {
  inputs?: ReactNode;
  configuration?: ReactNode;
  outputs?: ReactNode;
  bindings?: Record<string, string | null | undefined>;
  requires?: readonly string[];
  labels?: Record<string, string>;
}) {
  const ready = configReady(bindings, requires);
  const waiting = configWaitingFor(bindings, requires, labels);

  return (
    <div data-testid="widget-setup">
      {inputs && <Section name="inputs">{inputs}</Section>}

      {configuration && (ready ? (
        <Section name="configuration">{configuration}</Section>
      ) : (
        <p className="field-hint" data-testid="setup-waiting">{waiting}</p>
      ))}

      {outputs && <Section name="outputs">{outputs}</Section>}
    </div>
  );
}

function Section({
  name,
  children,
}: {
  name: "inputs" | "configuration" | "outputs";
  children: ReactNode;
}) {
  return (
    <section data-testid={`setup-${name}`} style={{ marginBottom: 10 }}>
      <div
        className="slug"
        style={{ marginBottom: 4, letterSpacing: "0.06em", textTransform: "uppercase" }}
      >
        {SECTION_LABELS[name]}
      </div>
      <p className="field-hint" style={{ marginTop: 0 }}>{SECTION_HINTS[name]}</p>
      {children}
    </section>
  );
}
