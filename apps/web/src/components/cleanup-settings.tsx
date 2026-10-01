"use client";

/** p.72's "Configure Ontology cleanup" (§619; `ontology-manager` p.72-73).
 *
 * > "customize the flags used and their respective priority… with a choice
 * > of using either the default set or custom flags… an individual
 * > customization that does not affect other Ontology editors. When you save
 * > changes and return to the main Cleanup tab, you will be prompted to
 * > recalculate the cleanup queue." (p.72)
 *
 * **The queue is recalculated rather than prompted for.** Here it is computed
 * on every read, so the save that changes the flags is the moment to read it
 * again, and a prompt would be a button whose only effect is the one saving
 * already had. The panel says it happened instead. The rules are in
 * `lib/ontology-cleanup.ts`. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { objects as objApi } from "@/lib/api";
import {
  CUSTOM_FLAGS_NOTE, DEFAULT_PATTERN_NOTE, daysOf, flagHint, flagLabel, flagRows, movedFlag,
  patternOf, toggledFlag,
} from "@/lib/ontology-cleanup";

export function CleanupSettings({ workspaceId }: { workspaceId: string }) {
  const client = useQueryClient();
  const saved = useQuery({
    queryKey: ["ontology-cleanup-settings", workspaceId],
    queryFn: () => objApi.cleanupSettings(workspaceId),
  });
  // `undefined` until the saved setup arrives; `null` is the default set.
  const [draft, setDraft] = useState<string[] | null | undefined>(undefined);
  // p.74's two values (§630), as typed; blank is each one's default.
  const [pattern, setPattern] = useState("");
  const [days, setDays] = useState("");
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (saved.data && draft === undefined) {
      setDraft(saved.data.flags);
      setPattern(saved.data.name_pattern ?? "");
      setDays(saved.data.stale_days === null ? "" : String(saved.data.stale_days));
    }
  }, [saved.data, draft]);

  const save = useMutation({
    mutationFn: (flags: string[] | null) => objApi.saveCleanupSettings(workspaceId, {
      flags, name_pattern: patternOf(pattern), stale_days: daysOf(days) ?? null,
    }),
    onSuccess: async (next) => {
      client.setQueryData(["ontology-cleanup-settings", workspaceId], next);
      await client.invalidateQueries({ queryKey: ["ontology-cleanup"] });
      setDone(true);
    },
  });

  if (!saved.data || draft === undefined) return null;
  const available = saved.data.available;
  const custom = draft !== null;
  const edit = (next: string[] | null) => {
    setDraft(next);
    setDone(false);
  };
  const badDays = daysOf(days) === undefined;

  return (
    <details className="cleanup-settings" data-testid="cleanup-settings">
      <summary>Configure flags</summary>
      <p className="field-hint">
        Your own setup: it changes your queue and nobody else&apos;s.
      </p>
      <div className="row-actions" role="radiogroup" aria-label="Which flags">
        <label>
          <input type="radio" name="cleanup-flag-set" data-testid="cleanup-default-set"
                 checked={!custom} onChange={() => edit(null)} />{" "}
          Default set
        </label>
        <label>
          <input type="radio" name="cleanup-flag-set" data-testid="cleanup-custom-set"
                 checked={custom} onChange={() => edit([...available])} />{" "}
          Custom flags
        </label>
      </div>
      {custom && <p className="field-hint" data-testid="cleanup-custom-note">{CUSTOM_FLAGS_NOTE}</p>}
      <ol className="cleanup-flag-list">
        {flagRows(draft, available).map(({ flag, on }, index) => (
          <li key={flag} data-testid={`cleanup-setting-${flag}`}>
            <label title={flagHint(flag, saved.data)}>
              <input
                type="checkbox"
                checked={on}
                disabled={!custom}
                data-testid={`cleanup-setting-${flag}-on`}
                onChange={(e) => edit(toggledFlag(draft ?? available, flag, e.target.checked))}
              />{" "}
              {flagLabel(flag)}
            </label>
            {custom && on && (
              <>
                <button type="button" className="btn quiet" aria-label={`Raise ${flagLabel(flag)}`}
                        data-testid={`cleanup-setting-${flag}-up`} disabled={index === 0}
                        onClick={() => edit(movedFlag(draft!, flag, -1))}>↑</button>
                <button type="button" className="btn quiet" aria-label={`Lower ${flagLabel(flag)}`}
                        data-testid={`cleanup-setting-${flag}-down`}
                        disabled={index === draft!.length - 1}
                        onClick={() => edit(movedFlag(draft!, flag, 1))}>↓</button>
              </>
            )}
          </li>
        ))}
      </ol>
      {/* p.74's "Display name regex matches string" and "Datasource not
          updated in [x] days" (§630). */}
      <label className="field">
        <span className="field-label">Marked temporary: name pattern</span>
        <input
          type="text"
          data-testid="cleanup-name-pattern"
          value={pattern}
          placeholder="\[test|deprecated\]"
          onChange={(e) => { setPattern(e.target.value); setDone(false); }}
        />
        <span className="field-hint">
          A regular expression, matched with case. {DEFAULT_PATTERN_NOTE}
        </span>
      </label>
      <label className="field">
        <span className="field-label">Not synced lately: days</span>
        <input
          type="text"
          inputMode="numeric"
          data-testid="cleanup-stale-days"
          value={days}
          placeholder={String(saved.data.default_stale_days)}
          onChange={(e) => { setDays(e.target.value); setDone(false); }}
        />
        {badDays && (
          <span className="field-hint" data-testid="cleanup-stale-days-problem">
            A whole number of days, from 1 to 3650.
          </span>
        )}
      </label>
      <div className="row-actions">
        <button type="button" className="btn" data-testid="cleanup-settings-save"
                disabled={save.isPending || badDays} onClick={() => save.mutate(draft)}>
          Save
        </button>
        {done && (
          <span className="slug" role="status" data-testid="cleanup-settings-saved">
            Saved. The queue was worked out again with these flags.
          </span>
        )}
        {save.isError && (
          <span className="state error">Couldn&apos;t save: {String(save.error.message)}</span>
        )}
      </div>
    </details>
  );
}
