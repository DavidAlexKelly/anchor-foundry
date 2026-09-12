"use client";

/**
 * p.66's Export and Import (§327; `ontology-manager` p.65-67).
 *
 * > "You can export your Ontology working state by selecting the Advanced
 * > settings page from the application's home page and then selecting
 * > Export." (p.66)
 *
 * > "You will be prompted to choose an Ontology file from your local drive.
 * > Next, select Import… You will see the number of changes made in the file
 * > that need to be saved in the application header." (p.66)
 *
 * **The import is two presses, and the middle one is p.66's count.** Foundry
 * stages the file into a working state and shows the unsaved changes in the
 * header; this platform has no working state, so the plan is the staging — it
 * writes nothing, and Apply is where Foundry's Save is (§326).
 *
 * The wording is in `lib/ontology-transfer.ts`.
 */

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, objects as objApi } from "@/lib/api";
import {
  exportFilename,
  leftAloneWarning,
  originNote,
  planHeadline,
  refusalText,
  sectionSummary,
} from "@/lib/ontology-transfer";
import type { OntologyPlan } from "@/lib/types";

const SECTIONS: [keyof OntologyPlan["sections"], string][] = [
  ["object_types", "Object types"],
  ["link_types", "Link types"],
  ["action_types", "Action types"],
];

export function OntologyTransfer({
  workspaceId,
  workspaceSlug,
}: {
  workspaceId: string;
  workspaceSlug: string;
}) {
  const [document, setDocument] = useState<Record<string, unknown> | null>(null);
  const [filename, setFilename] = useState("");
  const [readError, setReadError] = useState("");

  const exporting = useMutation({
    mutationFn: () => objApi.exportOntology(workspaceId),
    onSuccess: (doc) => {
      // A blob rather than a link to the route: the export needs the caller's
      // credentials, so an `<a href>` to the API would arrive unauthenticated.
      const blob = new Blob([JSON.stringify(doc, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const anchor = window.document.createElement("a");
      anchor.href = url;
      anchor.download = exportFilename(workspaceSlug);
      anchor.click();
      URL.revokeObjectURL(url);
    },
  });

  const planning = useMutation({
    mutationFn: (doc: Record<string, unknown>) =>
      objApi.planOntologyImport(workspaceId, doc),
  });
  const applying = useMutation({
    mutationFn: (doc: Record<string, unknown>) =>
      objApi.applyOntologyImport(workspaceId, doc),
  });

  async function chooseFile(file: File | null | undefined) {
    setReadError("");
    planning.reset();
    applying.reset();
    setDocument(null);
    if (!file) return;
    setFilename(file.name);
    let parsed: unknown;
    try {
      parsed = JSON.parse(await file.text());
    } catch {
      // **Said here rather than sent to the server.** A file that is not JSON
      // at all is not an ontology question, and posting it would turn a typo
      // into a round trip that comes back saying the same thing.
      setReadError("That file isn't JSON. Check it opens in a text editor.");
      return;
    }
    const doc = parsed as Record<string, unknown>;
    setDocument(doc);
    planning.mutate(doc);
  }

  const plan = planning.data as OntologyPlan | undefined;

  return (
    <section data-testid="ontology-transfer">
      <div className="page-head">
        <div>
          <h2 style={{ fontSize: 15, margin: 0 }}>Export</h2>
          <p className="sub">
            The whole ontology as JSON — object types, link types and actions.
          </p>
        </div>
        <button
          className="btn quiet"
          data-testid="ontology-export"
          disabled={exporting.isPending}
          onClick={() => exporting.mutate()}
        >
          {exporting.isPending ? "Exporting…" : "Export"}
        </button>
      </div>
      {exporting.isError && (
        <p className="form-error" data-testid="ontology-export-error">
          {exporting.error instanceof ApiError
            ? exporting.error.message
            : "Couldn't export this ontology."}
        </p>
      )}

      <div className="page-head" style={{ marginTop: 24 }}>
        <div>
          <h2 style={{ fontSize: 15, margin: 0 }}>Import</h2>
          <p className="sub">
            Choose a file to see what it would change. Nothing is written until
            you apply it.
          </p>
        </div>
        <label className="btn quiet" style={{ cursor: "pointer" }}>
          Choose file
          <input
            type="file"
            accept="application/json,.json"
            data-testid="ontology-import-file"
            style={{ display: "none" }}
            onChange={(e) => chooseFile(e.target.files?.[0])}
          />
        </label>
      </div>
      {filename && <p className="slug" data-testid="ontology-import-name">{filename}</p>}

      {readError && (
        <p className="form-error" data-testid="ontology-import-unreadable">
          {readError}
        </p>
      )}
      {planning.isPending && <p className="state">Reading the file…</p>}
      {planning.isError && (
        <p className="form-error" data-testid="ontology-import-refused">
          {refusalText(
            planning.error instanceof ApiError ? planning.error.message : null,
          )}
        </p>
      )}

      {plan && !applying.data && (
        <div data-testid="ontology-plan">
          {/* p.66's count, which is the whole reason the import is two
              presses rather than one. */}
          <p><strong data-testid="plan-headline">{planHeadline(plan)}</strong></p>
          <p className="slug" data-testid="plan-origin">{originNote(plan)}</p>
          <ul className="link-list">
            {SECTIONS.map(([key, label]) => {
              const line = sectionSummary(label, plan.sections[key]);
              return line ? (
                <li key={key} className="slug" data-testid={`plan-${key}`}>{line}</li>
              ) : null;
            })}
          </ul>
          {leftAloneWarning(plan) && (
            /* **The one thing p.66's reader must not believe.** The page says
               import "will recreate the entire working state", and this one
               declines to delete — so a copy that looks like a replacement
               gets told what it left behind. */
            <p className="login-note" data-testid="plan-left-alone">
              {leftAloneWarning(plan)}
            </p>
          )}
          <div className="form-actions">
            <button
              className="btn"
              data-testid="ontology-import-apply"
              disabled={plan.changes === 0 || applying.isPending}
              onClick={() => document && applying.mutate(document)}
            >
              {applying.isPending ? "Applying…" : "Apply"}
            </button>
          </div>
          {applying.isError && (
            <p className="form-error" data-testid="ontology-apply-error">
              {refusalText(
                applying.error instanceof ApiError
                  ? applying.error.message
                  : null,
              )}
            </p>
          )}
        </div>
      )}

      {applying.data && (
        <p className="login-note" data-testid="ontology-applied">
          Applied: {applying.data.added.length} added,{" "}
          {applying.data.updated.length} updated.
        </p>
      )}
    </section>
  );
}
