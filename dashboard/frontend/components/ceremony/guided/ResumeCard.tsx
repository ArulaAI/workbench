"use client";

import Link from "next/link";

const STATUS_LABEL: Record<string, string> = {
  question: "Interview in progress",
  blocked: "Blocked by a deferred answer",
  drafted: "Drafted",
  drafted_with_open_questions: "Drafted with open questions",
};

export function ResumeCard({
  featureName,
  title,
  status,
  confirmed,
  total,
  href,
}: {
  featureName: string;
  title: string;
  status: string;
  confirmed: number;
  total: number;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="surface surface-hover"
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 16,
        padding: 20,
        textDecoration: "none",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div className="type-section-header">{title || featureName}</div>
        <div className="type-caption" style={{ marginTop: 4 }}>
          Guided PRD · {STATUS_LABEL[status] ?? status}
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
        <span className="type-mono-value" style={{ color: "var(--color-text-secondary)" }}>
          {confirmed}/{total} confirmed
        </span>
        <span className="type-badge" style={{ color: "var(--color-accent)" }}>
          Resume →
        </span>
      </div>
    </Link>
  );
}
