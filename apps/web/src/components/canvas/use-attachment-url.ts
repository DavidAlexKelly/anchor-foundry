"use client";

import { useEffect, useState } from "react";

import { objects as objApi } from "@/lib/api";

/**
 * An attachment as a URL an element can use, or null until it has arrived.
 *
 * **Fetched, not pointed at, and that is not a style choice.** Cookie
 * authentication here requires the `X-Anchor-Session` header - the CSRF
 * defence that makes a cookie safe to accept at all - and an `<img src>`
 * cannot set headers, so a plain URL in an element attribute is an
 * unauthenticated request and a 401. So the bytes are fetched as a Blob and
 * handed back as an object URL, which is revoked on the way out: otherwise
 * every re-render of a table of these leaks a blob for the life of the page.
 *
 * Shared since §472, when the header's logo image became the second reader;
 * it was the Media Preview's own effect until then.
 */
export function useAttachmentUrl(
  workspaceId: string,
  key: string | null | undefined,
  contentType: string,
): string | null {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!key) {
      setObjectUrl(null);
      return;
    }
    let stale = false;
    let created: string | null = null;
    objApi
      .attachmentBlob(workspaceId, key, contentType)
      .then((blob) => {
        if (stale) return;
        created = URL.createObjectURL(blob);
        setObjectUrl(created);
      })
      .catch(() => setObjectUrl(null));
    return () => {
      stale = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [workspaceId, key, contentType]);
  return objectUrl;
}
