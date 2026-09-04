export function QualityWarningsTable({ warnings }: { warnings: string[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        Quality warnings
      </div>
      {warnings.length === 0 ? (
        <p className="type-body">No quality warnings were raised during the last build.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <tbody>
            {warnings.map((w, i) => (
              <tr key={i} style={{ borderTop: i > 0 ? "1px solid var(--color-border-light)" : undefined }}>
                <td style={{ padding: "10px 8px 10px 0", width: 20 }}>
                  <span style={{ color: "var(--color-amber)" }}>⚠</span>
                </td>
                <td className="type-table-cell" style={{ padding: "10px 0" }}>{w}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
