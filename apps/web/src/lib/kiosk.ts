/**
 * Where a tab keeps its kiosk credential (§684; `workshop` p.610).
 *
 * **Session storage**: the tab's own, gone when the tab closes, never sent
 * anywhere by the browser on its own, and never in a URL where history,
 * referrers and logs would keep it after the session ended.
 */
export const KIOSK_STORAGE_KEY = "anchor-kiosk-session";

/** The credential this tab holds, or null. */
export function storedKioskToken(): string | null {
  try {
    const token = sessionStorage.getItem(KIOSK_STORAGE_KEY);
    return token && token.startsWith("kiosk_") ? token : null;
  } catch {
    return null;
  }
}

export function forgetKioskToken(): void {
  try {
    sessionStorage.removeItem(KIOSK_STORAGE_KEY);
  } catch {
    /* nothing held */
  }
}
