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

import { useEffect, useState, type CSSProperties } from "react";
import { ApiError, objects as objApi } from "@/lib/api";
import { mediaKind } from "@/components/media-kind";
import type {
  AttachmentRef, GeoPoint, PropertyDataType, PropertyStyle, ValueFormat,
} from "@/lib/types";
import { formatValue } from "@/lib/value-format";

function isGeoPoint(value: unknown): value is GeoPoint {
  return (
    typeof value === "object" && value !== null &&
    typeof (value as GeoPoint).lat === "number" &&
    typeof (value as GeoPoint).lon === "number"
  );
}

function isAttachment(value: unknown): value is AttachmentRef {
  return (
    typeof value === "object" && value !== null &&
    typeof (value as AttachmentRef).key === "string" &&
    typeof (value as AttachmentRef).filename === "string"
  );
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
}) {
  // Applied to the empty marker too. A rule whose whole purpose is "colour it
  // grey when the value is null" (p.106) would otherwise be invisible on
  // precisely the values it is about.
  const paint = styleOf(conditional);
  if (value === null || value === undefined || value === "") {
    return <span style={{ color: "var(--ink-soft)", ...paint }}>∅</span>;
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
  if (dataType === "attachment" && isAttachment(value)) {
    // **Shown, not just offered** (decision 0009, part 2). An attachment
    // holding an image *is* the media reference this platform can honour -
    // bytes, a MIME type, and a URL that enforces the workspace boundary - and
    // the only thing missing was that a PNG drew a download link. The filename
    // and size stay under it either way: a picture with no name is not a file
    // anybody can go and find.
    const href = objApi.attachmentUrl(workspaceId, value.key);
    const kind = mediaKind(value.content_type);
    const caption = (
      <a href={href} download={value.filename} className="slug">
        {value.filename} ({humanSize(value.size)})
      </a>
    );
    if (kind === "file") {
      return (
        <a href={href} download={value.filename}>
          {value.filename} <span className="slug">({humanSize(value.size)})</span>
        </a>
      );
    }
    return (
      <span className="media-value" data-media-kind={kind} style={paint}>
        <Media
          workspaceId={workspaceId}
          kind={kind}
          attachment={value}
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

/** The input for one editable property in an action form. */
export function PropertyInput({
  workspaceId,
  dataType,
  value,
  onChange,
  label,
}: {
  workspaceId: string;
  dataType: PropertyDataType | undefined;
  value: unknown;
  onChange: (next: unknown) => void;
  label: string;
}) {
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  if (dataType === "attachment") {
    const current = isAttachment(value) ? value : null;
    return (
      <div>
        <input
          type="file"
          aria-label={label}
          disabled={uploading}
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
        value={value === true ? "true" : value === false ? "false" : ""}
        onChange={(e) => onChange(e.target.value === "" ? null : e.target.value === "true")}
      >
        <option value="">Not set</option>
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    );
  }

  // Everything else is text, including geopoint ("lat,lon" is both what the
  // API accepts and what a person can type) and numbers: the API coerces a
  // numeric string to a number, so parsing it here would only duplicate a
  // rule that has to live server-side anyway.
  return (
    <input
      type={dataType === "date" ? "date" : "text"}
      aria-label={label}
      placeholder={dataType === "geopoint" ? "lat,lon — e.g. 51.5074,-0.1278" : undefined}
      value={value === null || value === undefined ? "" : String(value)}
      onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
    />
  );
}
