"use client";

/** p.52's layout template picker: the strip at the bottom of a page in the
 * builder.
 *
 * > "You can also explore other layout templates using the layout template
 * > picker at the bottom of the page. You can preview what each layout would
 * > look like by hovering over its icon. If you would like to use a template,
 * > you can select that icon; the page layout will update to the one you
 * > selected." (p.52-53)
 *
 * The transform lives in `layout-template.ts` and is tested without a browser.
 * What is here is the three things that need one: where the strip sits, what
 * hovering shows, and reading the serialised layout out of Craft and handing
 * the new one back.
 *
 * **The preview is drawn from the template, not shipped as a picture.** Each
 * icon renders the template's own sections as boxes, and the hover panel
 * renders the same description larger. A preview that cannot disagree with
 * what the button does is worth more than a prettier one that can — this repo
 * has been caught twice by a picture and a behaviour drifting apart.
 */
import { useState } from "react";
import { useEditor } from "@craftjs/core";

import { newNodeId } from "@/lib/workshop-module";
import { applyTemplate, TEMPLATES, type LayoutTemplate } from "./layout-template";

/** The template drawn as boxes: one row per section, split into columns where
 * the section's own weights say so. */
function TemplateShape({ template }: { template: LayoutTemplate }) {
  return (
    <span className="canvas-template-shape" aria-hidden="true">
      {template.sections.map((s, i) => {
        const weights = (s.weights ?? "")
          .split(",")
          .map((w) => Number(w.trim()))
          .filter((w) => Number.isFinite(w) && w > 0);
        const parts = weights.length > 0 ? weights : [1];
        return (
          <span
            key={i}
            className={`canvas-template-row is-${s.direction}`}
            style={{ flex: s.direction === "toolbar" ? "0 0 22%" : 1 }}
          >
            {parts.map((w, j) => (
              <span key={j} className="canvas-template-cell" style={{ flex: w }} />
            ))}
          </span>
        );
      })}
    </span>
  );
}

export function LayoutTemplatePicker({ pageId }: { pageId: string }) {
  const { actions, query } = useEditor();
  // What the pointer is over, which is the whole of p.52's "preview by
  // hovering". Focus counts as hover: the strip is a row of buttons, and a
  // preview only a mouse can reach is a preview half the people using this
  // cannot see.
  const [previewing, setPreviewing] = useState<LayoutTemplate | null>(null);

  const apply = (template: LayoutTemplate) => {
    const layout = query.getSerializedNodes() as Record<string, unknown>;
    const next = applyTemplate(layout, pageId, template, newNodeId);
    actions.deserialize(next.layout as never);
    // Land the author in the first new section, so the next widget they drag
    // has an obvious home and the change is visibly *theirs*.
    const first = next.sections[0];
    if (first) {
      try {
        actions.selectNode(first);
      } catch {
        /* the node exists but has not mounted yet; the layout is still right */
      }
    }
  };

  return (
    <div
      className="canvas-template-picker"
      data-testid="layout-template-picker"
      // **Craft's drag connector is on the page node this strip sits inside**,
      // and it starts a drag on `mousedown`. That moves the DOM out from under
      // the pointer, so `mouseup` lands somewhere else and the browser never
      // synthesises a `click` at all - the button silently does nothing, with
      // no error anywhere. Stopping the press here keeps the connector from
      // ever seeing it; `onClick`'s own `stopPropagation` is about selection
      // and does not help, because it runs on an event that never happens.
      onMouseDown={(e) => e.stopPropagation()}
      onPointerDown={(e) => e.stopPropagation()}
    >
      {previewing && (
        <div className="canvas-template-preview" data-testid="layout-template-preview">
          <TemplateShape template={previewing} />
          <div>
            <strong>{previewing.label}</strong>
            <span>{previewing.hint}</span>
          </div>
        </div>
      )}
      <div className="canvas-template-strip">
        <span className="field-label">Layout templates</span>
        {TEMPLATES.map((t) => (
          <button
            key={t.key}
            type="button"
            className="canvas-template-button"
            data-testid={`layout-template-${t.key}`}
            aria-label={t.label}
            title={t.label}
            onMouseEnter={() => setPreviewing(t)}
            onFocus={() => setPreviewing(t)}
            onMouseLeave={() => setPreviewing((c) => (c === t ? null : c))}
            onBlur={() => setPreviewing((c) => (c === t ? null : c))}
            onClick={(e) => {
              // The strip sits inside the page node, which is itself
              // selectable and draggable - without this a click would also
              // select the page and read as the button having done nothing.
              e.stopPropagation();
              apply(t);
            }}
          >
            <TemplateShape template={t} />
          </button>
        ))}
      </div>
    </div>
  );
}
