"use client";

/**
 * Rendering and editing property values by their declared type (ROADMAP
 * Objects item 4).
 *
 * Before this, every value went through `String(value)`, which is why the
 * richer types were invisible even where they already existed: a geopoint
 * rendered as `[object Object]` and a date was indistinguishable from a
 * string that happened to look like one. Rendering is the half of "make the
 * type mean something" that a user can actually see.
 */

import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { ApiError, objects as objApi } from "@/lib/api";
import { mediaKind } from "@/components/media-kind";
import type {
  AttachmentRef, GeoPoint, PropertyDataType, PropertyStyle, ValueFormat,
} from "@/lib/types";
import { formatValue } from "@/lib/value-format";
// The Canvas Action Form's rule for which control a type gets, now shared
// rather than duplicated (§237).
import { inputTypeFor } from "@/components/canvas/pure";

function isGeoPoint(value: unknown): value is GeoPoint {
  return (
    typeof value === "object" && value !== null &&
    typeof (value as GeoPoint).lat === "number" &&
    typeof (value as GeoPoint).lon === "number"
  );
}

/** Whether this is the reference `POST /attachments` returned.
 *
 * **A JSON string counts, and that is the round trip rather than laxity** —
 * exactly the reasoning `property_values._coerce_attachment` gives for
 * accepting one on the way in. Two places produce the string form: write-back
 * stores the whole reference as JSON text in the dataset column, so the next
 * sync reads it back; and `pure.seedActionForm` stringifies every object it
 * seeds a form with.
 *
 * §237 found the second the way the server found the first. A form re-opened on
 * an object that already carries an attachment seeds the parameter as JSON
 * text; reading only the object form meant the file input kept its `required`,
 * and the browser refused to submit a value that was already there.
 */
function isAttachment(value: unknown): value is AttachmentRef {
  const parsed = parseAttachment(value);
  return parsed !== null;
}

function parseAttachment(value: unknown): AttachmentRef | null {
  let candidate = value;
  if (typeof candidate === "string") {
    const text = candidate.trim();
    // Cheap gate before parsing: every other seeded value is a plain string,
    // and running `JSON.parse` over each of them to fail would be a try/catch
    // in the render path of every text field.
    if (!text.startsWith("{")) return null;
    try {
      candidate = JSON.parse(text);
    } catch {
      return null;
    }
  }
  if (
    typeof candidate === "object" && candidate !== null &&
    typeof (candidate as AttachmentRef).key === "string" &&
    typeof (candidate as AttachmentRef).filename === "string"
  ) {
    return candidate as AttachmentRef;
  }
  return null;
}

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** The bytes, fetched through the authenticated client and handed to the
 * element as an object URL.
 *
 * The fetch is what carries the session header; the `blob:` URL that comes
 * out is same-origin, needs no credentials, and is revoked when this unmounts
 * so a table of fifty rows does not leak fifty blobs.
 *
 * A failure renders nothing rather than a broken-image glyph: the download
 * link underneath is unaffected and is a better answer than a grey box.
 */
function Media({
  workspaceId,
  kind,
  attachment,
}: {
  workspaceId: string;
  kind: "image" | "video" | "audio";
  attachment: AttachmentRef;
}) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let revoked = false;
    let objectUrl: string | null = null;
    objApi
      .attachmentBlob(workspaceId, attachment.key, attachment.content_type)
      .then((blob) => {
        if (revoked) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => setUrl(null));
    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [workspaceId, attachment.key, attachment.content_type]);

  if (!url) return null;
  // `alt` is the filename because it is the only description this platform
  // has; an empty alt would tell a screen reader the image is decorative,
  // which it is not - it is the value of a property.
  if (kind === "image") {
    return <img src={url} alt={attachment.filename} className="media-image" />;
  }
  if (kind === "video") return <video src={url} controls className="media-player" />;
  return <audio src={url} controls className="media-player" />;
}

export function PropertyValue({
  workspaceId,
  dataType,
  value,
  valueFormat,
  style: conditional,
  emptyText = "∅",
}: {
  workspaceId: string;
  dataType: PropertyDataType | undefined;
  value: unknown;
  /** The property's own formatter (Foundry `object-link-types` p.94–101).
   * Optional so a caller that has no property declaration to hand — an action
   * form preview, a value read off an instance — keeps working unchanged. */
  valueFormat?: ValueFormat | null;
  /** What a matching conditional rule asked for (p.102–109). Already
   * evaluated: the rule may read a *different* property, so only a caller
   * holding the whole instance can work it out. */
  style?: PropertyStyle | null;
  /** What to show where there is no value.
   *
   * **Optional, with the platform's own marker as the default.** Foundry
   * `workshop` p.224 gives the Object Table a "Custom 'No value' display" and
   * says the default there is the words "No value" — so that widget passes its
   * own text and every other caller keeps the `∅` this platform uses
   * everywhere. A page about one widget does not get to restyle the rest.
   */
  emptyText?: ReactNode;
}) {
  // Applied to the empty marker too. A rule whose whole purpose is "colour it
  // grey when the value is null" (p.106) would otherwise be invisible on
  // precisely the values it is about.
  const paint = styleOf(conditional);
  if (value === null || value === undefined || value === "") {
    return <span style={{ color: "var(--ink-soft)", ...paint }}>{emptyText}</span>;
  }
  if (valueFormat) {
    const formatted = formatValue(value, valueFormat);
    if (formatted !== null) {
      // **The raw value stays reachable in the tooltip.** p.94's whole point is
      // that "$100K" is easier to read, and the cost of easier is that the
      // reader can no longer see 100000 — which is the number they will type
      // into a filter. Both, rather than a choice between them.
      return <span title={String(value)} style={paint}>{formatted}</span>;
    }
  }
  if (dataType === "geopoint" && isGeoPoint(value)) {
    // Coordinates, not a map. A map needs a tile source, which means an
    // outbound request from a page that renders a customer's own data - the
    // Canvas map widget this item unblocks is where that decision belongs,
    // made once, not smuggled into a table cell.
    return (
      <span className="slug" title="latitude, longitude" style={paint}>
        {value.lat.toFixed(4)}, {value.lon.toFixed(4)}
      </span>
    );
  }
  const attached = dataType === "attachment" ? parseAttachment(value) : null;
  if (attached) {
    // **Shown, not just offered** (decision 0009, part 2). An attachment
    // holding an image *is* the media reference this platform can honour -
    // bytes, a MIME type, and a URL that enforces the workspace boundary - and
    // the only thing missing was that a PNG drew a download link. The filename
    // and size stay under it either way: a picture with no name is not a file
    // anybody can go and find.
    const href = objApi.attachmentUrl(workspaceId, attached.key);
    const kind = mediaKind(attached.content_type);
    const caption = (
      <a href={href} download={attached.filename} className="slug">
        {attached.filename} ({humanSize(attached.size)})
      </a>
    );
    if (kind === "file") {
      return (
        <a href={href} download={attached.filename}>
          {attached.filename} <span className="slug">({humanSize(attached.size)})</span>
        </a>
      );
    }
    return (
      <span className="media-value" data-media-kind={kind} style={paint}>
        <Media
          workspaceId={workspaceId}
          kind={kind}
          attachment={attached}
        />
        {caption}
      </span>
    );
  }
  if ((dataType === "date" || dataType === "timestamp") && typeof value === "string") {
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) {
      return (
        <span title={value} style={paint}>
          {dataType === "date" ? parsed.toLocaleDateString() : parsed.toLocaleString()}
        </span>
      );
    }
  }
  if (dataType === "json" || (typeof value === "object" && value !== null)) {
    return <span className="slug" style={paint}>{JSON.stringify(value)}</span>;
  }
  // The bare-text case is the common one, so it gets the span only when a rule
  // asked for something — an unstyled wrapper on every cell of every table is
  // a lot of DOM for nothing.
  return paint ? <span style={paint}>{String(value)}</span> : <>{String(value)}</>;
}

/** A rule's answer as inline style. Inline rather than a class because the
 * colours are author-chosen hex (p.105's "add your own custom color"), and a
 * stylesheet cannot enumerate those. */
function styleOf(style: PropertyStyle | null | undefined): CSSProperties | undefined {
  if (!style) return undefined;
  const out: CSSProperties = {};
  if (style.colour) out.color = style.colour;
  if (style.background) {
    out.background = style.background;
    // A background needs room to read as one rather than as a smear behind
    // the text, and p.102's screenshot is explicit about it: "colored boxes".
    out.padding = "1px 6px";
    out.borderRadius = "var(--radius)";
  }
  if (style.align) {
    out.textAlign = style.align;
    out.display = "inline-block";
    out.minWidth = "100%";
  }
  return Object.keys(out).length ? out : undefined;
}

/** The input for one editable property in an action form.
 *
 * **One renderer for both action forms as of §237, and the docstring above was
 * true of only one of them for a long time.** This was written for action forms
 * — the sentence has said so since it was added — and the *Canvas* Action Form
 * never used it: `CanvasActionForm` grew its own field, a plain `<input>` typed
 * by `pure.inputTypeFor`. Two renderers for one question, and they disagreed
 * about two types.
 *
 * The disagreement was not cosmetic. `inputTypeFor` answers `"text"` for an
 * **attachment**, and an attachment value must be the object `POST /attachments`
 * returned (`property_values._coerce_attachment` checks its four fields) — so
 * the Canvas form offered a box whose contents could essentially never be valid.
 * A control that cannot work is worse than an absent one, which is §214's rule
 * about settings and applies to inputs for the same reason. It answered `"text"`
 * for a **boolean** too, where this offers the three-state select that can say
 * "not set".
 *
 * The Canvas form was better in one respect and that is kept: `type="number"`
 * for an integer or a float, which brings a numeric keypad on a phone and the
 * browser's own stepper. The comment below explains why the *value* is still
 * not parsed here.
 */
export function PropertyInput({
  workspaceId,
  dataType,
  value,
  onChange,
  label,
  required = false,
  disabled = false,
}: {
  workspaceId: string;
  dataType: PropertyDataType | undefined;
  value: unknown;
  onChange: (next: unknown) => void;
  label: string;
  /** p.25's required parameters. Passed through to the control rather than
   * enforced here: the server refuses a missing required value, and a second
   * rule in the browser would be a second answer to one question. */
  required?: boolean;
  /** Why a caller might not want this control usable right now - the Canvas
   * form's builder preview (§237), the Object Table's row cap (`workshop`
   * p.242). **The reason stays with the caller**: this renders the control,
   * and every rule about when one may be typed into belongs to whoever knows
   * what the control is for. */
  disabled?: boolean;
}) {
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  if (dataType === "attachment") {
    const current = parseAttachment(value);
    return (
      <div>
        <input
          type="file"
          aria-label={label}
          // Required only until something is attached: the value the action
          // sends is the reference already uploaded, so re-picking a file is
          // not what "required" is asking for.
          required={required && !isAttachment(value)}
          disabled={uploading || disabled}
          onChange={async (e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            setUploading(true);
            setUploadError(null);
            try {
              // Uploaded before the action is submitted, because the value
              // the action writes *is* the reference this returns.
              onChange(await objApi.uploadAttachment(workspaceId, file));
            } catch (err) {
              setUploadError(err instanceof ApiError ? err.message : "Upload failed.");
            } finally {
              setUploading(false);
            }
          }}
        />
        {uploading && <p className="login-note">Uploading…</p>}
        {uploadError && <div className="form-error">{uploadError}</div>}
        {current && <p className="login-note">Attached: {current.filename}</p>}
      </div>
    );
  }

  if (dataType === "boolean") {
    return (
      <select
        aria-label={label}
        required={required}
        disabled={disabled}
        value={value === true ? "true" : value === false ? "false" : ""}
        onChange={(e) => onChange(e.target.value === "" ? null : e.target.value === "true")}
      >
        <option value="">Not set</option>
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    );
  }

  // Everything else goes through `inputTypeFor`, which is the Canvas form's
  // own rule and the one thing it had that this did not: a number gets a
  // numeric control, a date a date one, and the rest text — geopoint included,
  // since "lat,lon" is both what the API accepts and what a person can type.
  //
  // **The input *type* is a keyboard, not a parser.** The value still leaves
  // here as the string that was typed: the API coerces a numeric string to a
  // number against the declared type, and doing it here as well would be a
  // second rule free to disagree with the one that decides.
  return (
    <input
      type={inputTypeFor(dataType ?? "string")}
      aria-label={label}
      required={required}
      aria-required={required || undefined}
      disabled={disabled}
      placeholder={dataType === "geopoint" ? "lat,lon — e.g. 51.5074,-0.1278" : undefined}
      value={value === null || value === undefined ? "" : String(value)}
      onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
    />
  );
}
