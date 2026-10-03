"use client";

/** p.248-252's render hints as a checklist (§724) - p.248: "You can select
 * and deselect render hints in the properties pane of the property editor".
 * One component for a property's row and a shared property's dialog, which
 * hold the same list (p.182). */

import { RENDER_HINTS, hintsOf, toggledHint, type RenderHint } from "@/lib/render-hints";

export function RenderHintsChecklist({ value, onChange, disabled = false, testId = "render-hint" }: {
  value: readonly string[] | null | undefined;
  onChange: (next: RenderHint[]) => void;
  disabled?: boolean;
  testId?: string;
}) {
  const chosen = hintsOf(value);
  return (
    <fieldset className="render-hints" disabled={disabled} style={{ border: 0, padding: 0, margin: 0 }}>
      {RENDER_HINTS.map((h) => (
        <label key={h.key} className="field-inline" style={{ display: "flex", gap: 6, fontSize: 12.5 }}
          title={h.hint}>
          <input
            type="checkbox"
            data-testid={`${testId}-${h.key}`}
            checked={chosen.includes(h.key)}
            onChange={(e) => onChange(toggledHint(chosen, h.key, e.target.checked))}
          />
          {h.label}
          <span className="field-hint" style={{ margin: 0 }}>{h.hint}</span>
        </label>
      ))}
    </fieldset>
  );
}
