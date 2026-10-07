import Link from "next/link";

/** An address that is no page (§908), said in the platform's words rather
 * than the framework's default. */
export default function NotFound() {
  return (
    <div className="state" data-testid="not-found">
      <p style={{ fontWeight: 600, marginBottom: 6 }}>There is no page at this address.</p>
      <p style={{ marginTop: 0 }}>It may have moved, or the link may be incomplete.</p>
      <Link className="btn" href="/home">Go home</Link>
    </div>
  );
}
