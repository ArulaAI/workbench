"use client";

import type { AuthoringSession } from "@/lib/graphql/queries/authoring";

export function SourceInputPanel({
  intake,
  interview,
  expanded = false,
}: {
  intake: AuthoringSession["intake"];
  interview: NonNullable<AuthoringSession["interview"]>;
  expanded?: boolean;
}) {
  const title = intake?.feature_title?.trim();
  const description = intake?.feature_description?.trim();

  if (!title && !description && interview.length === 0) return null;

  return (
    <details
      className="surface"
      open={expanded || undefined}
      style={{ padding: 16, borderRadius: 10 }}
    >
      <summary
        style={{
          cursor: "pointer",
          color: "var(--color-text)",
          fontWeight: 600,
          fontSize: 13,
        }}
      >
        Source input &amp; interview
        <span
          className="type-caption"
          style={{ marginLeft: 8, fontWeight: 400, color: "var(--color-text-tertiary)" }}
        >
          {interview.length} answered question{interview.length === 1 ? "" : "s"}
        </span>
      </summary>

      <div style={{ marginTop: 16 }}>
        {title && (
          <div>
            <div className="type-compact-label">User-provided title</div>
            <div className="type-body" style={{ marginTop: 5, color: "var(--color-text)" }}>
              {title}
            </div>
          </div>
        )}
        {description && (
          <div style={{ marginTop: title ? 14 : 0 }}>
            <div className="type-compact-label">User-provided description</div>
            <div className="type-body" style={{ marginTop: 5, lineHeight: 1.55 }}>
              {description}
            </div>
          </div>
        )}

        {interview.length > 0 && (
          <div
            style={{
              marginTop: 16,
              paddingTop: 14,
              borderTop: "1px solid var(--color-border-light)",
            }}
          >
            <div className="type-compact-label">Questions and answers</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 12 }}>
              {interview.map((item) => (
                <div key={item.id}>
                  <div
                    className="type-caption"
                    style={{ color: "var(--color-text-tertiary)", fontFamily: "var(--font-mono)" }}
                  >
                    {item.id}
                  </div>
                  <div className="type-body" style={{ marginTop: 4, color: "var(--color-text)" }}>
                    {item.prompt}
                  </div>
                  <div
                    className="type-body"
                    style={{
                      marginTop: 7,
                      padding: "9px 10px",
                      borderLeft: "2px solid var(--color-accent)",
                      background: "var(--color-bg-elevated)",
                      lineHeight: 1.55,
                    }}
                  >
                    {item.answer || "Deferred without an answer."}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </details>
  );
}
