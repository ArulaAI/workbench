"use client";

import { useState } from "react";
import type {
  ExecutePanel as ExecutePanelData,
  RunningFeature as RunningFeatureData,
  RecentFeature as RecentFeatureData,
  Escalation,
} from "@/lib/graphql/queries/landing";
import { PanelLabel, SurfaceLink } from "./PanelLabel";

interface ExecutePanelProps {
  execute: ExecutePanelData;
  onRespondToEscalation: (feature: string, taskId: string, response: string) => Promise<void>;
}

function formatDate(isoString: string | null): string {
  if (!isoString) return "";
  return new Date(isoString).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

function RunningFeatureRow({ feature }: { feature: RunningFeatureData }) {
  const hasBlocked = feature.blockedCount > 0;
  const dotColor = hasBlocked ? "var(--color-amber)" : "var(--color-accent)";
  const barColor = hasBlocked ? "var(--color-amber)" : "var(--color-accent)";
  const pctColor = hasBlocked ? "var(--color-amber)" : "var(--color-accent)";
  const remaining = feature.tasksTotal - feature.tasksCompleted;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderBottom: "1px solid rgba(255,255,255,0.025)" }}>
      <div className="animate-pulse" style={{ width: 6, height: 6, borderRadius: "50%", background: dotColor, flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text)" }}>{feature.name}</div>
        <div style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
          {hasBlocked
            ? `${feature.blockedCount} task${feature.blockedCount === 1 ? "" : "s"} awaiting input`
            : `${remaining} task${remaining === 1 ? "" : "s"} remaining`}
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <div style={{ width: 64, height: 3, background: "rgba(255,255,255,0.04)", borderRadius: 2, overflow: "hidden" }}>
          <div style={{ height: "100%", width: `${feature.progressPct}%`, background: barColor, borderRadius: 2 }} />
        </div>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 500, minWidth: 32, textAlign: "right", color: pctColor }}>
          {Math.round(feature.progressPct)}%
        </div>
      </div>
    </div>
  );
}

function RecentFeatureRow({ feature }: { feature: RecentFeatureData }) {
  const dateStr = formatDate(feature.completedAt);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderBottom: "1px solid rgba(255,255,255,0.025)" }}>
      <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="var(--color-text-tertiary)" strokeWidth={2} style={{ flexShrink: 0 }}>
        <path d="M20 6L9 17l-5-5" />
      </svg>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 400, color: "var(--color-text-secondary)" }}>{feature.name}</div>
      </div>
      <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", flexShrink: 0 }}>
        {dateStr || `${feature.tasksCompleted}/${feature.tasksTotal}`}
      </div>
    </div>
  );
}

function EscalationCard({
  escalation,
  onRespond,
}: {
  escalation: Escalation;
  onRespond: (feature: string, taskId: string, response: string) => Promise<void>;
}) {
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);

  async function handleSend() {
    if (!input.trim() || sending) return;
    setSending(true);
    try {
      await onRespond(escalation.feature, escalation.taskId, input.trim());
      setInput("");
      setSent(true);
      setTimeout(() => setSent(false), 2000);
    } finally {
      setSending(false);
    }
  }

  return (
    <div
      style={{
        marginTop: 12,
        padding: "12px 14px",
        background: "var(--color-bg-elevated)",
        borderRadius: 8,
        border: "1px solid rgba(240, 178, 50, 0.08)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 8, fontWeight: 600, padding: "2px 5px", borderRadius: 3, background: "rgba(240, 178, 50, 0.05)", color: "var(--color-amber)" }}>INPUT</span>
        <span style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>
          {escalation.feature} · {escalation.taskTitle || `Task ${escalation.taskId}`}
        </span>
      </div>
      <div style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6, marginBottom: 8 }}>
        {escalation.question}
      </div>
      <div style={{ display: "flex", gap: 5 }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder="Your answer…"
          disabled={sending}
          style={{
            flex: 1,
            padding: "7px 11px",
            background: "var(--color-bg)",
            border: "1px solid var(--color-border)",
            borderRadius: 6,
            fontFamily: "var(--font-sans)",
            fontSize: 12,
            color: "var(--color-text)",
            outline: "none",
          }}
        />
        <button
          onClick={handleSend}
          disabled={sending || !input.trim()}
          style={{
            padding: "7px 14px",
            background: sent ? "rgba(68,204,119,0.12)" : "var(--color-accent)",
            color: sent ? "var(--color-emerald)" : "var(--color-bg)",
            border: "none",
            borderRadius: 6,
            fontSize: 11,
            fontWeight: 600,
            cursor: sending || !input.trim() ? "not-allowed" : "pointer",
            fontFamily: "var(--font-sans)",
            opacity: sending || !input.trim() ? 0.5 : 1,
          }}
        >
          {sent ? "Sent" : sending ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}

export function ExecutePanel({ execute, onRespondToEscalation }: ExecutePanelProps) {
  const { runningFeatures, recentFeatures, escalations } = execute;
  const runningCount = runningFeatures.length;

  const subtitle = runningCount > 0
    ? `${runningCount} Feature${runningCount === 1 ? "" : "s"} Running`
    : "No Features Running";

  return (
    <>
      <PanelLabel name="Execute" subtitle={subtitle} color="var(--color-accent)" />

      {runningFeatures.map((feature) => (
        <RunningFeatureRow key={feature.name} feature={feature} />
      ))}

      {escalations.map((escalation) => (
        <EscalationCard
          key={`${escalation.feature}-${escalation.taskId}`}
          escalation={escalation}
          onRespond={onRespondToEscalation}
        />
      ))}

      {recentFeatures.length > 0 && runningFeatures.length === 0 && (
        <div style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 8 }}>
          No features running.
        </div>
      )}

      {recentFeatures.map((feature) => (
        <RecentFeatureRow key={feature.name} feature={feature} />
      ))}

      <SurfaceLink href="/mission-control" label="Open Execute Surface" color="var(--color-accent)" />
    </>
  );
}
