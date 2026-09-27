/** The viewer's time zone, as the browser names it (§596).
 *
 * Sent with each variable resolve so a cast set to p.138-139's "the user's
 * local timezone" reads the viewer's, which the server evaluating variables
 * could not otherwise know. Undefined when the browser will not say, which the
 * server reads as UTC. */
export function viewerZone(
  resolve: () => string | undefined = () => Intl.DateTimeFormat().resolvedOptions().timeZone,
): string | undefined {
  try {
    const zone = resolve();
    return typeof zone === "string" && zone ? zone : undefined;
  } catch {
    return undefined;
  }
}
