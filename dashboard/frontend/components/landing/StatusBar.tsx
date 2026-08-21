"use client";

interface StatusBarProps {
  projectName: string;
  featureCount: number;
  runningCount: number;
  agentCount?: number;
  staleCount?: number;
  connected: boolean;
}

export function StatusBar({
  projectName,
  featureCount,
  runningCount,
  agentCount = 0,
  staleCount = 0,
  connected,
}: StatusBarProps) {
  const connectionColor = connected ? "var(--color-emerald)" : "var(--color-red)";

  return (
    <div
      style={{
        height: 26,
        background: "var(--color-bg-elevated)",
        borderTop: "1px solid var(--color-border)",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 16px 0 32px",
        fontSize: 10,
        color: "var(--color-text-tertiary)",
        flexShrink: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span
            style={{
              width: 5,
              height: 5,
              borderRadius: "50%",
              backgroundColor: connectionColor,
              display: "inline-block",
            }}
          />
          {connected ? "Connected" : "Disconnected"}
        </span>
        <span style={{ fontFamily: "var(--font-mono)" }}>{projectName}</span>
        <span>{featureCount} feature{featureCount === 1 ? "" : "s"}</span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        {staleCount > 0 && (
          <span style={{ display: "flex", alignItems: "center", gap: 4, color: "var(--color-amber)" }}>
            {staleCount} stale
          </span>
        )}
        {agentCount > 0 && (
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
            {agentCount} agent{agentCount === 1 ? "" : "s"}
          </span>
        )}
        {runningCount > 0 && (
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span
              className="animate-pulse"
              style={{
                width: 5,
                height: 5,
                borderRadius: "50%",
                backgroundColor: "var(--color-accent)",
                display: "inline-block",
              }}
            />
            {runningCount} running
          </span>
        )}
      </div>
    </div>
  );
}
