import type { DigestCommand } from "@/lib/graphql/queries/repository-digest";

export function CommandList({ commands }: { commands: DigestCommand[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        Entrypoints and commands
      </div>
      {commands.length === 0 ? (
        <p className="type-body">No commands discovered in CLAUDE.md, AGENTS.md, or project manifests.</p>
      ) : (
        <div className="digest-table-scroll">
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {commands.map((c, i) => (
                <tr key={i} style={{ borderTop: i > 0 ? "1px solid var(--color-border-light)" : undefined }}>
                  <td className="type-table-header" style={{ padding: "8px 8px 8px 0", textTransform: "uppercase", whiteSpace: "nowrap" }}>
                    {c.purpose}
                  </td>
                  <td className="type-mono-value" style={{ padding: "8px 12px 8px 0", whiteSpace: "nowrap" }}>
                    {c.command}
                  </td>
                  <td className="type-caption" style={{ padding: "8px 0", textAlign: "right", whiteSpace: "nowrap", color: "var(--color-text-secondary)" }}>
                    {c.workingDirectory}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
