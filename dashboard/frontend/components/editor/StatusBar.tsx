"use client";

import { useEffect, useState } from "react";
import { Wifi, WifiOff, FileText, Check, GitBranch } from "lucide-react";
import type { SaveState } from "./EditorTabs";
import type { CursorPosition } from "./SpecEditor";

function toDisplayPath(path: string): string {
  const idx = path.indexOf("specs/");
  return idx >= 0 ? path.slice(idx) : path;
}

const LIFECYCLE_LABELS: Record<string, { label: string; color: string }> = {
  draft: { label: "Draft", color: "var(--color-text-tertiary)" },
  ready: { label: "Ready", color: "var(--color-accent)" },
  approved: { label: "Approved", color: "var(--color-emerald)" },
  locked: { label: "Locked", color: "var(--color-amber)" },
};

export function StatusBar({
  connected,
  activeSpec,
  completeness,
  specCount,
  saveState,
  cursor,
  lifecycle,
  gitBranch,
}: {
  connected: boolean;
  activeSpec: string | null;
  completeness: number | null;
  specCount: number;
  saveState?: SaveState;
  cursor?: CursorPosition | null;
  lifecycle?: string | null;
  gitBranch?: string | null;
}) {
  // Show "Saved" briefly after save completes, then fade
  const [showSaved, setShowSaved] = useState(false);
  const [prevSaveState, setPrevSaveState] = useState<SaveState | undefined>(saveState);

  useEffect(() => {
    if (prevSaveState === "saving" && saveState === "clean") {
      setShowSaved(true);
      const timer = setTimeout(() => setShowSaved(false), 2000);
      return () => clearTimeout(timer);
    }
    setPrevSaveState(saveState);
  }, [saveState, prevSaveState]);

  return (
    <div className="editor-statusbar">
      <style>{`
        .editor-statusbar {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 0 12px;
          height: 24px;
          border-top: 1px solid var(--color-border);
          background: var(--color-bg);
          font-size: 11px;
          font-family: var(--font-mono);
          color: var(--color-text-tertiary);
          flex-shrink: 0;
          overflow: hidden;
        }
        .editor-statusbar-item {
          display: flex;
          align-items: center;
          gap: 4px;
          flex-shrink: 0;
          transition: color 0.2s ease, opacity 0.3s ease;
        }
        .editor-statusbar-path {
          display: flex;
          align-items: center;
          gap: 4px;
          color: var(--color-text-secondary);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          min-width: 0;
        }
        .editor-statusbar-sep {
          opacity: 0.15;
          flex-shrink: 0;
        }
        .editor-statusbar-saved {
          display: flex;
          align-items: center;
          gap: 3px;
          color: var(--color-emerald);
          transition: opacity 0.5s ease;
        }
      `}</style>

      {/* Connection */}
      <span className="editor-statusbar-item" style={{
        color: connected ? "var(--color-emerald)" : "var(--color-red)",
      }}>
        {connected ? <Wifi size={10} strokeWidth={1.5} /> : <WifiOff size={10} strokeWidth={1.5} />}
        {connected ? "live" : "offline"}
      </span>

      <span className="editor-statusbar-sep">|</span>

      {/* File path */}
      {activeSpec && (
        <>
          <span className="editor-statusbar-path">
            <FileText size={10} strokeWidth={1.5} style={{ flexShrink: 0 }} />
            {toDisplayPath(activeSpec)}
          </span>
          <span className="editor-statusbar-sep">|</span>
        </>
      )}

      {/* Save state */}
      {activeSpec && saveState === "saving" && (
        <>
          <span className="editor-statusbar-item" style={{ color: "var(--color-amber)" }}>
            Saving...
          </span>
          <span className="editor-statusbar-sep">|</span>
        </>
      )}
      {activeSpec && saveState === "error" && (
        <>
          <span className="editor-statusbar-item" style={{ color: "var(--color-red)" }}>
            Save failed
          </span>
          <span className="editor-statusbar-sep">|</span>
        </>
      )}
      {activeSpec && saveState === "dirty" && (
        <>
          <span className="editor-statusbar-item" style={{ color: "var(--color-text-tertiary)" }}>
            Unsaved
          </span>
          <span className="editor-statusbar-sep">|</span>
        </>
      )}
      {showSaved && (
        <>
          <span className="editor-statusbar-saved" style={{ opacity: showSaved ? 1 : 0 }}>
            <Check size={10} strokeWidth={2} />
            Saved
          </span>
          <span className="editor-statusbar-sep">|</span>
        </>
      )}

      {/* Completeness */}
      {completeness !== null && (
        <>
          <span className="editor-statusbar-item" style={{
            color: completeness >= 0.8 ? "var(--color-emerald)"
              : completeness >= 0.5 ? "var(--color-amber)"
              : "var(--color-red)",
          }}>
            {Math.round(completeness * 100)}%
          </span>
          <span className="editor-statusbar-sep">|</span>
        </>
      )}

      {/* Lifecycle state */}
      {activeSpec && lifecycle && (
        <>
          <span className="editor-statusbar-item" style={{
            color: LIFECYCLE_LABELS[lifecycle]?.color || "var(--color-text-tertiary)",
          }}>
            {LIFECYCLE_LABELS[lifecycle]?.label || lifecycle}
          </span>
          <span className="editor-statusbar-sep">|</span>
        </>
      )}

      {/* Git branch */}
      {gitBranch && (
        <>
          <span className="editor-statusbar-item" style={{ color: "var(--color-violet)" }}>
            <GitBranch size={10} strokeWidth={1.5} style={{ flexShrink: 0 }} />
            {gitBranch}
          </span>
          <span className="editor-statusbar-sep">|</span>
        </>
      )}

      {/* Cursor position */}
      {cursor && (
        <>
          <span className="editor-statusbar-item" style={{ marginLeft: "auto" }}>
            Ln {cursor.line}, Col {cursor.col}
          </span>
          <span className="editor-statusbar-sep">|</span>
        </>
      )}

      {/* Spec count */}
      <span style={{ marginLeft: cursor ? undefined : "auto", flexShrink: 0 }}>
        {specCount} specs
      </span>
    </div>
  );
}
