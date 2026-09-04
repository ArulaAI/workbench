import type { DigestCommand } from "@/lib/graphql/queries/repository-digest";
import { ConfidenceBadge } from "./ConfidenceBadge";

// Detected directly from the command's own text — a label, not a claim
// about coverage or file counts we have no data for. Order matters:
// checked top to bottom, first match wins.
const FRAMEWORK_PATTERNS: [RegExp, string][] = [
  [/\bpytest\b/i, "pytest"],
  [/\bjest\b/i, "Jest"],
  [/\bvitest\b/i, "Vitest"],
  [/\bmvn(w)?\b/i, "Maven"],
  [/\bgradle(w)?\b/i, "Gradle"],
  [/\bgo\s+test\b/i, "go test"],
  [/\bcargo\s+test\b/i, "Cargo"],
  [/\brspec\b/i, "RSpec"],
  [/\bphpunit\b/i, "PHPUnit"],
  [/\bdotnet\s+test\b/i, "dotnet test"],
];

function detectFramework(command: string): string | null {
  for (const [pattern, label] of FRAMEWORK_PATTERNS) {
    if (pattern.test(command)) return label;
  }
  return null;
}

/**
 * Test-suite aggregation, derived entirely from the existing `commands`
 * array (purpose === "TEST") grouped by workingDirectory — no new
 * discovery. Deliberately has no "files" or "coverage" column: that data
 * doesn't reach the frontend today (project-map isn't exposed via
 * GraphQL), and fabricating a count here would be exactly the kind of
 * invented production data this phase rules out.
 */
export function TestSuiteTable({ commands }: { commands: DigestCommand[] }) {
  const testCommands = commands.filter((c) => c.purpose === "TEST");

  if (testCommands.length === 0) {
    return (
      <div className="surface" style={{ padding: 20 }}>
        <div className="type-section-title" style={{ marginBottom: 8 }}>
          Discovered test suites
        </div>
        <p className="type-body">No test commands discovered in CLAUDE.md, AGENTS.md, or project manifests.</p>
      </div>
    );
  }

  const byDirectory = new Map<string, DigestCommand[]>();
  for (const c of testCommands) {
    const group = byDirectory.get(c.workingDirectory) ?? [];
    group.push(c);
    byDirectory.set(c.workingDirectory, group);
  }

  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        Discovered test suites
      </div>
      <div className="digest-table-scroll">
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th className="type-table-header" style={{ textAlign: "left", padding: "0 8px 8px 0" }}>Working directory</th>
              <th className="type-table-header" style={{ textAlign: "left", padding: "0 8px 8px 0" }}>Command</th>
              <th className="type-table-header" style={{ textAlign: "left", padding: "0 8px 8px 0" }}>Framework</th>
              <th className="type-table-header" style={{ textAlign: "left", padding: "0 0 8px 0" }}>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {[...byDirectory.entries()].map(([dir, group]) =>
              group.map((c, i) => (
                <tr key={`${dir}:${i}`} style={{ borderTop: "1px solid var(--color-border-light)" }}>
                  <td className="type-mono-value" style={{ padding: "8px 8px 8px 0", whiteSpace: "nowrap" }}>
                    {i === 0 ? dir : ""}
                  </td>
                  <td className="type-mono-value" style={{ padding: "8px 8px 8px 0", whiteSpace: "nowrap" }}>
                    {c.command}
                  </td>
                  <td className="type-caption" style={{ padding: "8px 8px 8px 0", color: "var(--color-text-secondary)" }}>
                    {detectFramework(c.command) ?? "—"}
                  </td>
                  <td style={{ padding: "8px 0" }}>
                    <ConfidenceBadge confidence={c.confidence} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
