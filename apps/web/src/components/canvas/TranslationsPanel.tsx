"use client";

/** p.209-211's Translations tab: where a builder types the translations (§400).
 *
 * > "Strings within the module may be manually translated by application
 * > builders. On selection of a target language, each translatable string
 * > detected within the module will be displayed with an input field to
 * > manually enter translations." (p.209)
 *
 * > "Once satisfied with the translations, the translations may then be Marked
 * > as complete… Any new or modified strings detected in the module, for
 * > example, on the addition of a new button or on edit of a section header's
 * > title, will appear in the To translate section, separating them from the
 * > already-translated and reviewed strings." (p.210)
 *
 * **Every decision this panel makes is `translatable.ts`'s**, which §399 built
 * and swept: which strings exist, which are still untranslated, which are
 * reviewed, and which entries belong to text the module no longer holds. This
 * file draws them and owns one thing of its own — the draft a builder is
 * typing, which is not in the document until they stop.
 *
 * **p.209's automatic translation with AIP is out of scope** by
 * `docs/parity/README.md`. Its absence is said on screen rather than left as a
 * missing button somebody looks for.
 */
import { useState } from "react";
import { useEditor } from "@craftjs/core";

import type { WorkshopModule } from "@/lib/types";
import { done, occurrences, stale, toTranslate } from "./translatable";

type Settings = NonNullable<WorkshopModule["translations"]>;

export function TranslationsPanel({
  translations,
  onChange,
  onPreview,
  readOnly = false,
}: {
  translations: Settings;
  onChange: (next: Settings) => void;
  /** p.211's preview, opened on the language showing. Handed up rather than
   * rendered here: the preview needs the live layout, which only the editor
   * this panel sits beside can serialise. */
  onPreview?: (language: string) => void;
  readOnly?: boolean;
}) {
  // The **live** document, like the Used colours panel and for the same
  // reason: a builder adds a button and its label should appear in To
  // translate straight away, which is what p.210's "any new… strings detected
  // in the module" describes. Waiting for a save would make the list describe
  // the module they had a minute ago.
  const layout = useEditor((state) => {
    const out: Record<string, { type: string; props: unknown }> = {};
    for (const [id, node] of Object.entries(state.nodes)) {
      out[id] = { type: node.data?.name ?? "", props: node.data?.props ?? {} };
    }
    return out;
  });

  const languages = Object.keys(translations.languages ?? {}).sort();
  const [language, setLanguage] = useState<string>(languages[0] ?? "");
  const [adding, setAdding] = useState("");
  const table = translations.languages?.[language];

  const pending = toTranslate(layout, table);
  const settled = done(layout, table);
  const orphans = stale(layout, table);
  // Where each string came from, so a builder can tell two identical-looking
  // strings apart by what uses them. Built once rather than per row.
  const where = new Map<string, string[]>();
  for (const use of occurrences(layout)) {
    where.set(use.text, [...(where.get(use.text) ?? []), use.prop]);
  }

  function writeTable(next: Record<string, { text: string; reviewed?: boolean }>) {
    onChange({
      ...translations,
      languages: { ...(translations.languages ?? {}), [language]: next },
    });
  }

  function setText(source: string, text: string) {
    const current = table ?? {};
    if (!text.trim()) {
      // Clearing the box removes the entry rather than storing `""`. An empty
      // entry is not served (§399), so keeping one would be a row that looks
      // translated in the document and reads as English on screen.
      const { [source]: _gone, ...rest } = current;
      writeTable(rest);
      return;
    }
    writeTable({ ...current, [source]: { ...current[source], text } });
  }

  function setReviewed(source: string, reviewed: boolean) {
    const current = table ?? {};
    if (!current[source]) return;
    writeTable({ ...current, [source]: { ...current[source], reviewed } });
  }

  function addLanguage() {
    const tag = adding.trim();
    if (!tag) return;
    onChange({
      ...translations,
      languages: { ...(translations.languages ?? {}), [tag]: translations.languages?.[tag] ?? {} },
    });
    setLanguage(tag);
    setAdding("");
  }

  const row = (source: string) => (
    <li key={source}>
      <span className="canvas-tr-source">{source}</span>
      <span className="soft canvas-tr-where">{(where.get(source) ?? []).join(", ")}</span>
      <input
        value={table?.[source]?.text ?? ""}
        placeholder={source}
        disabled={readOnly}
        data-testid={`tr-input-${source}`}
        onChange={(e) => setText(source, e.target.value)}
      />
      {/* p.210's Mark as complete. Per string rather than per language: the
          sentence marks "these strings as reviewed", and a whole-language
          tick would go stale the moment one string was edited. */}
      <label className="canvas-tr-reviewed">
        <input
          type="checkbox"
          checked={!!table?.[source]?.reviewed}
          disabled={readOnly || !table?.[source]?.text}
          data-testid={`tr-reviewed-${source}`}
          onChange={(e) => setReviewed(source, e.target.checked)}
        />
        <span className="soft">Reviewed</span>
      </label>
    </li>
  );

  return (
    <div className="canvas-translations" data-testid="translations-panel">
      <label className="field">
        <span className="field-label">Language</span>
        <select
          value={language}
          data-testid="tr-language"
          disabled={languages.length === 0}
          onChange={(e) => setLanguage(e.target.value)}
        >
          {languages.length === 0 && <option value="">No languages yet</option>}
          {languages.map((tag) => (
            <option key={tag} value={tag}>{tag}</option>
          ))}
        </select>
      </label>

      {/* p.211: "previewed directly in the module in edit mode by navigating
          to the Translations tab and selecting the configured language of
          choice". Beside the picker, because the language it previews is the
          one the picker is on - a preview button somewhere else would leave
          "which language" to be guessed. */}
      {onPreview && language !== "" && (
        <button
          type="button"
          className="btn quiet"
          data-testid="tr-preview"
          onClick={() => onPreview(language)}
        >
          Preview the module in {language}
        </button>
      )}

      {!readOnly && (
        <label className="field">
          <span className="field-label">Add a language</span>
          <span className="canvas-tr-add">
            <input
              value={adding}
              placeholder="fr, pt-BR"
              data-testid="tr-add-language"
              onChange={(e) => setAdding(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addLanguage();
                }
              }}
            />
            <button type="button" className="btn quiet" data-testid="tr-add" onClick={addLanguage}>
              Add
            </button>
          </span>
          {/* A tag, not a language name. The reader's browser sends tags, and
              a picker offering "French" would have to guess which of `fr`,
              `fr-CA` and `fr-FR` an author meant. */}
          <span className="field-hint">
            A language tag, the way a browser sends it. `fr` serves every
            French reader; `pt-BR` serves Brazilian Portuguese first and other
            Portuguese readers only if nothing closer is here.
          </span>
        </label>
      )}

      {!translations.enabled && (
        // Said here as well as on the Settings panel, because this is where
        // somebody has just spent ten minutes typing translations nobody is
        // being served (§214).
        <p className="state error" data-testid="tr-off">
          Translations are switched off in Settings, so no reader is being
          served any of this yet.
        </p>
      )}

      {language === "" ? (
        <p className="canvas-widget-empty" data-testid="tr-no-language">
          Add a language to start. Every string in the module appears here with
          a box to translate it.
        </p>
      ) : (
        <>
          <p className="field-label">To translate ({pending.length})</p>
          {pending.length === 0 ? (
            <p className="canvas-widget-empty" data-testid="tr-none-pending">
              Nothing left in {language}.
            </p>
          ) : (
            <ul className="canvas-tr-rows" data-testid="tr-pending">{pending.map(row)}</ul>
          )}

          <p className="field-label">Translated ({settled.length})</p>
          {settled.length > 0 && (
            <ul className="canvas-tr-rows" data-testid="tr-done">{settled.map(row)}</ul>
          )}

          {orphans.length > 0 && (
            <>
              {/* Kept rather than deleted: an edit that is undone should not
                  have cost its translations. Shown, because a builder who
                  cannot see them cannot clear them either. */}
              <p className="field-label">No longer in the module ({orphans.length})</p>
              <ul className="canvas-tr-rows canvas-tr-stale" data-testid="tr-stale">
                {orphans.map((source) => (
                  <li key={source}>
                    <span className="canvas-tr-source">{source}</span>
                    <span className="soft">{table?.[source]?.text}</span>
                    <button
                      type="button"
                      className="btn quiet"
                      disabled={readOnly}
                      data-testid={`tr-forget-${source}`}
                      onClick={() => setText(source, "")}
                    >
                      Forget
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}

      <p className="canvas-widget-empty" data-testid="tr-aip-note">
        {/* p.209's AIP translation is out of scope by docs/parity/README.md.
            Named, so its absence is a decision rather than a missing button. */}
        Translations are entered by hand. Automatic translation isn&apos;t here.
      </p>
    </div>
  );
}
