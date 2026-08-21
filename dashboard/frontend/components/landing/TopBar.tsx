"use client";

interface TopBarProps {
  projectName: string;
  branch: string;
  greeting?: string;
}

function getGreeting(hour: number): string {
  if (hour >= 5 && hour < 12) return "Good morning";
  if (hour >= 12 && hour < 18) return "Good afternoon";
  return "Good evening";
}

export function TopBar({ projectName, branch, greeting: backendGreeting }: TopBarProps) {
  const greeting = backendGreeting ?? getGreeting(new Date().getHours());

  return (
    <div
      style={{
        padding: "16px 32px 14px",
        borderBottom: "1px solid var(--color-border)",
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}
    >
      <div
        style={{
          fontSize: 20,
          fontWeight: 600,
          color: "var(--color-text)",
          letterSpacing: "-0.02em",
        }}
      >
        {greeting}, Sanjay
      </div>

      <div style={{ display: "flex", alignItems: "baseline", gap: 16 }}>
        <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
          {projectName} · {branch}
        </span>
      </div>
    </div>
  );
}
