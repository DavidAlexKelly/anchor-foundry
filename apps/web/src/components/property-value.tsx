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

import { useState } from "react";
import { ApiError, objects as objApi } from "@/lib/api";
import type { AttachmentRef, GeoPoint, PropertyDataType } from "@/lib/types";

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

export function PropertyValue({
  workspaceId,
  dataType,
  value,
}: {
  workspaceId: string;
  dataType: PropertyDataType | undefined;
  value: unknown;
}) {
  if (value === null || value === undefined || value === "") {
    return <span style={{ color: "var(--ink-soft)" }}>∅</span>;
  }
  if (dataType === "geopoint" && isGeoPoint(value)) {
    // Coordinates, not a map. A map needs a tile source, which means an
    // outbound request from a page that renders a customer's own data - the
    // Canvas map widget this item unblocks is where that decision belongs,
    // made once, not smuggled into a table cell.
    return (
      <span className="slug" title="latitude, longitude">
        {value.lat.toFixed(4)}, {value.lon.toFixed(4)}
      </span>
    );
  }
  if (dataType === "attachment" && isAttachment(value)) {
    return (
      <a href={objApi.attachmentUrl(workspaceId, value.key)} download={value.filename}>
        {value.filename}{" "}
        <span className="slug">({humanSize(value.size)})</span>
      </a>
    );
  }
  if ((dataType === "date" || dataType === "timestamp") && typeof value === "string") {
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) {
      return (
        <span title={value}>
          {dataType === "date" ? parsed.toLocaleDateString() : parsed.toLocaleString()}
        </span>
      );
    }
  }
  if (dataType === "json" || (typeof value === "object" && value !== null)) {
    return <span className="slug">{JSON.stringify(value)}</span>;
  }
  return <>{String(value)}</>;
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
