import Link from "next/link";

/** RD-8: opens Repository Digest from the Define workflow without leaving
 * the dashboard, carrying enough state (returnTo + feature) for /digest to
 * show a return affordance back here.
 */
export function DigestEntryLink({ feature }: { feature: string }) {
  return (
    <Link
      href={`/digest?returnTo=define&feature=${encodeURIComponent(feature)}`}
      className="type-badge"
      style={{
        padding: "8px 12px",
        borderRadius: 8,
        border: "1px solid var(--color-border)",
        color: "var(--color-text-secondary)",
        textDecoration: "none",
      }}
    >
      Repository Digest
    </Link>
  );
}
