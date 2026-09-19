"use client";

/** p.211's preview: the module as a reader of one language would see it (§401).
 *
 * > "Translated text may be previewed directly in the module in edit mode by
 * > navigating to the Translations tab and selecting the configured language
 * > of choice." (p.211)
 *
 * **It is a second, read-only canvas beside the builder's, never the
 * builder's canvas with different text in it**, and that is the whole design
 * rather than an implementation detail. Craft reads `<Frame data>` once at
 * mount, so translating the editing canvas means remounting it — which throws
 * away every edit the author has not saved. Worse, the translated tree then
 * *is* the document as far as `query.getSerializedNodes()` is concerned, so
 * the next Save would write French into the layout and there would be nothing
 * left to translate. §400 named both hazards and left this unbuilt rather
 * than ship either.
 *
 * So the preview renders a **snapshot** in an `<Editor enabled={false}>` of
 * its own, mounted alongside the builder. The builder keeps its tree, its
 * selection and its undo history; nothing here can be saved, because there is
 * no Save on this surface and this Editor's nodes never reach one.
 *
 * **The snapshot is the live document, not the saved one.** p.211 has an
 * author previewing while they work, and a preview of the last save would
 * show a module they had already moved on from - which is the same argument
 * the Translations tab makes for reading Craft's node map rather than the
 * stored definition.
 */
import { Editor, Frame } from "@craftjs/core";
import type { Resolver } from "@craftjs/core";

import type { WorkshopEvent, WorkshopVariable } from "@/lib/types";
import { translated, type Table } from "./translatable";

export function TranslationPreview({
  /** The live layout, serialised by the builder at the moment preview opened. */
  snapshot,
  language,
  table,
  variables,
  events,
  resolver,
  onRender,
  envelope,
  onExit,
}: {
  snapshot: Record<string, unknown>;
  language: string;
  table: Table | undefined;
  variables: Record<string, WorkshopVariable>;
  events: Record<string, WorkshopEvent>;
  // Passed in rather than imported: the resolver and the node wrapper live
  // with the builder, and importing them here would tie this file to the
  // widget library it is only ever handed.
  resolver: Resolver;
  onRender: React.ComponentType<{ render: React.ReactElement }>;
  /** Wraps the frame in whatever variable and event context the widgets need. */
  envelope: (children: React.ReactNode) => React.ReactNode;
  onExit: () => void;
}) {
  return (
    <div className="canvas-tr-preview" data-testid="translation-preview" data-language={language}>
      {/* p.177's profiler banner is the precedent: a mode you can be *in*
          needs a way out that is visible from wherever you have scrolled to,
          and a statement of which mode it is. Somebody who forgets they are
          previewing French will report the module as broken. */}
      <div className="canvas-tr-preview-bar" role="status">
        <strong>Previewing {language}</strong>
        <span className="soft">
          Nothing here can be edited, and your unsaved changes are still in the
          builder behind this.
        </span>
        <div className="spacer" />
        <button
          type="button"
          className="btn quiet"
          data-testid="translation-preview-exit"
          onClick={onExit}
        >
          Exit preview
        </button>
      </div>
      <Editor resolver={resolver} enabled={false} onRender={onRender}>
        {envelope(
          <Frame data={JSON.stringify(translated(snapshot, table))} />,
        )}
      </Editor>
    </div>
  );
}
