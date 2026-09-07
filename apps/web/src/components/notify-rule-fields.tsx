"use client";

/**
 * The notify rule's half of the action definition editor (§258;
 * `action-types` p.89-101).
 *
 * §257 built the rule, the delivery and the inbox, and left the rule reachable
 * only by posting JSON — the editor offered five rule kinds and `notify` was
 * not one of them. A feature the product cannot express is the same shape as
 * §252's *implements* column that could never be non-empty.
 *
 * **Its own file rather than a sixth branch inside the editor**, because it is
 * larger than the other five put together: p.89 says a notification needs
 * recipients *and* content, and content is three fields with a reference
 * inserter over each of them. Folding that into a component already carrying
 * five rule shapes would make the file about layout rather than about rules.
 *
 * The rules that decide what this offers are in `lib/notify-rule`, which is
 * where a wrong answer is a line.
 */

import { useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Field } from "@/components/dialog";
import { TypePicker } from "@/components/type-picker";
import { api, objects as objApi } from "@/lib/api";
import {
  NotifyConfig, PERMISSION_MODES, RECIPIENT_KINDS, insertReference,
  referenceOptions,
} from "@/lib/notify-rule";

/** One text field with p.94's reference buttons under it.
 *
 * > "Click on a parameter to generate the `{{{}}}` syntax to reference that
 * > parameter." (p.94)
 *
 * **Generated rather than typed, and that is the whole reason this exists.**
 * Somebody typing braces by hand will type two, and two braces are not a
 * reference — the template would render literally and nothing on screen would
 * say so. The buttons make the correct syntax the easy path.
 */
function TemplateField({
  label,
  hint,
  value,
  onChange,
  parameterNames,
  testId,
  multiline,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (next: string) => void;
  parameterNames: string[];
  testId: string;
  multiline?: boolean;
}) {
  const box = useRef<HTMLInputElement & HTMLTextAreaElement>(null);

  function insert(name: string) {
    const el = box.current;
    // The caret if there is one, the end of the text if the field has never
    // been focused: a reference appended to what is there beats one dropped at
    // position zero, in front of the sentence somebody wrote.
    const start = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? value.length;
    const next = insertReference(value, start, end, name);
    onChange(next.text);
    // Put the caret back after the reference so the sentence can continue.
    // `requestAnimationFrame` because the value lands on the next render and
    // setting a selection before that is setting it on the old string.
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(next.caret, next.caret);
    });
  }

  return (
    <Field label={label} hint={hint}>
      {multiline ? (
        <textarea
          ref={box}
          data-testid={testId}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <input
          ref={box}
          type="text"
          data-testid={testId}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      <div className="row-actions" style={{ flexWrap: "wrap", gap: 4 }}>
        <span className="slug">Insert:</span>
        {referenceOptions(parameterNames).map((option) => (
          <button
            key={option.value}
            type="button"
            className="btn quiet"
            style={{ padding: "2px 7px", fontSize: 11 }}
            data-testid={`${testId}-insert-${option.value}`}
            onClick={() => insert(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </Field>
  );
}

export function NotifyRuleFields({
  workspaceId,
  config,
  parameters,
  onChange,
  index,
}: {
  workspaceId: string;
  config: NotifyConfig;
  parameters: { api_name: string; data_type: string }[];
  onChange: (next: NotifyConfig) => void;
  index: number;
}) {
  const names = parameters.map((p) => p.api_name);
  const objectParameters = parameters.filter((p) => p.data_type === "object");
  const recipients = config.recipients ?? { kind: "static" };

  // p.95: "The configuration interface for notifications provides selectors
  // for users and groups when choosing a static set of recipients." The people
  // who can be chosen are the ones p.96 would let through at send time —
  // offering anybody else would be offering a save that fails (§214), and
  // offering fewer would hide recipients that work. The endpoint answers with
  // the same predicate `permitted` applies, which is why it is not `/members`.
  const people = useQuery({
    queryKey: ["notification-recipients", workspaceId],
    queryFn: () => api.notificationRecipients(workspaceId),
    enabled: recipients.kind === "static",
  });

  // The properties of whichever object type the recipient rule names, for
  // p.100's "then select the Case managers property".
  const properties = useQuery({
    queryKey: ["object-type", workspaceId, recipients.object_type],
    queryFn: () => objApi.getType(workspaceId, recipients.object_type!),
    enabled: recipients.kind === "object_property" && !!recipients.object_type,
  });

  const patch = (next: Partial<NotifyConfig>) => onChange({ ...config, ...next });
  const patchRecipients = (next: Partial<typeof recipients>) =>
    patch({ recipients: { ...recipients, ...next } });

  return (
    <div style={{ width: "100%" }}>
      <Field label="Notify">
        <select
          data-testid={`rule-${index}-recipient-kind`}
          aria-label={`Rule ${index} recipient kind`}
          value={recipients.kind}
          onChange={(e) =>
            // The rest of the recipient config is dropped: the three shapes
            // have nothing in common, and a leftover `property` on a static
            // list is a field the server would refuse for a reason nobody
            // could see on screen — the same argument the rule-kind select one
            // file over makes.
            patch({ recipients: { kind: e.target.value } })
          }
        >
          {RECIPIENT_KINDS.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </Field>

      {recipients.kind === "static" && (
        <Field
          label="People"
          hint="Only people who can see this workspace — p.96 refuses the action for anybody who cannot."
        >
          <div data-testid={`rule-${index}-people`}>
            {/* Individual people only. p.90's static option names users *or
                groups*, and groups are absent rather than offered: a group id
                sent as a recipient reaches a lookup in `users` that finds
                nobody, so the rule would save and then silently notify
                no-one. */}
            {(people.data ?? []).map((p) => (
              <label key={p.id} className="row-actions" style={{ gap: 6 }}>
                <input
                  type="checkbox"
                  aria-label={`Notify ${p.email}`}
                  checked={(recipients.user_ids ?? []).includes(p.id)}
                  onChange={(e) =>
                    patchRecipients({
                      user_ids: e.target.checked
                        ? [...(recipients.user_ids ?? []), p.id]
                        : (recipients.user_ids ?? []).filter((id) => id !== p.id),
                    })
                  }
                />
                <span>{p.display_name}</span>
                <span className="slug">{p.email}</span>
              </label>
            ))}
            {/* **Present rather than absent** when there is nobody: an empty
                box with no explanation reads as a list still loading. There is
                always at least the person reading it, so this appearing at all
                is a fact about the fetch rather than about the workspace. */}
            {people.isSuccess && people.data.length === 0 && (
              <p className="field-hint">Nobody here can see this workspace.</p>
            )}
          </div>
        </Field>
      )}

      {(recipients.kind === "parameter" || recipients.kind === "object_property") && (
        <Field
          label="From parameter"
          hint={
            recipients.kind === "parameter"
              ? "A parameter holding a user id (p.90)."
              : "An object parameter whose property holds a user id (p.100)."
          }
        >
          <select
            data-testid={`rule-${index}-recipient-parameter`}
            aria-label={`Rule ${index} recipient parameter`}
            value={recipients.parameter ?? ""}
            onChange={(e) => patchRecipients({ parameter: e.target.value })}
          >
            <option value="">Choose…</option>
            {(recipients.kind === "object_property" ? objectParameters : parameters)
              .map((p) => (
                <option key={p.api_name} value={p.api_name}>{p.api_name}</option>
              ))}
          </select>
        </Field>
      )}

      {recipients.kind === "object_property" && (
        <>
          <Field label="Of type">
            <TypePicker
              workspaceId={workspaceId}
              testId={`rule-${index}-recipient-type`}
              value={recipients.object_type ?? ""}
              placeholder="Choose…"
              onChange={(id) =>
                // The property belongs to the type, so changing the type
                // forgets it rather than keeping one the new type may not have.
                patchRecipients({ object_type: id, property: "" })
              }
            />
          </Field>
          <Field
            label="Property holding the user id"
            hint="p.96 — it has to be a string; the server refuses anything else."
          >
            <select
              data-testid={`rule-${index}-recipient-property`}
              aria-label={`Rule ${index} recipient property`}
              value={recipients.property ?? ""}
              onChange={(e) => patchRecipients({ property: e.target.value })}
              disabled={!recipients.object_type}
            >
              <option value="">Choose…</option>
              {(properties.data?.properties ?? [])
                .filter((p) => p.data_type === "string")
                .map((p) => (
                  <option key={p.api_name} value={p.api_name}>{p.api_name}</option>
                ))}
            </select>
          </Field>
        </>
      )}

      <TemplateField
        label="Subject"
        value={config.subject}
        onChange={(subject) => patch({ subject })}
        parameterNames={names}
        testId={`rule-${index}-subject`}
      />
      <TemplateField
        label="Body"
        multiline
        value={config.body}
        onChange={(body) => patch({ body })}
        parameterNames={names}
        testId={`rule-${index}-body`}
      />

      <Field label="Link" hint="p.91 — a button under the message. Both parts or neither.">
        <div className="row-actions">
          <input
            type="text"
            data-testid={`rule-${index}-link-url`}
            placeholder="/a/path/in/this/app"
            value={config.link?.url ?? ""}
            onChange={(e) =>
              patch({
                link: e.target.value || config.link?.text
                  ? { url: e.target.value, text: config.link?.text ?? "" }
                  : null,
              })
            }
          />
          <input
            type="text"
            data-testid={`rule-${index}-link-text`}
            placeholder="Button text"
            value={config.link?.text ?? ""}
            onChange={(e) =>
              patch({
                link: e.target.value || config.link?.url
                  ? { url: config.link?.url ?? "", text: e.target.value }
                  : null,
              })
            }
          />
        </div>
      </Field>

      <Field
        label="If somebody cannot see it"
        hint="p.96 — the strict one is the default, and it cannot quietly send data to somebody who may not read it."
      >
        <select
          data-testid={`rule-${index}-permissions`}
          aria-label={`Rule ${index} permissions`}
          value={config.permissions}
          onChange={(e) => patch({ permissions: e.target.value })}
        >
          {PERMISSION_MODES.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </Field>
    </div>
  );
}
