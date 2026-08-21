"use client";

import { useRef, useEffect } from "react";
import { X, FileText, Code2, Palette, Bug } from "lucide-react";

export type SaveState = "clean" | "dirty" | "saving" | "error";

export interface TabItem {
  path: string;
  specType: string;
  saveState: SaveState;
}

const TYPE_ICONS: Record<string, typeof FileText> = {
  prd: FileText,
  rfc: Code2,
  dsn: Palette,
  defect: Bug,
};

const TYPE_COLORS: Record<string, string> = {
  prd: "var(--color-accent)",
  rfc: "var(--color-violet)",
  dsn: "var(--color-rose)",
  defect: "var(--color-red)",
};

function getFilename(path: string): string {
  return path.split("/").pop()?.replace(".md", "") || path;
}

export function EditorTabs({
  tabs,
  activeTab,
  onSelect,
  onClose,
}: {
  tabs: TabItem[];
  activeTab: string | null;
  onSelect: (path: string) => void;
  onClose: (path: string) => void;
}) {
  const activeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
  }, [activeTab]);

  if (tabs.length === 0) {
    return <div className="editor-tabs-empty" />;
  }

  return (
    <div className="editor-tabs" role="tablist" aria-label="Open specs">
      <style>{`
        .editor-tabs-empty {
          height: 34px;
          border-bottom: 1px solid var(--color-border);
          flex-shrink: 0;
        }
        .editor-tabs {
          display: flex;
          align-items: stretch;
          border-bottom: 1px solid var(--color-border);
          background: var(--color-bg-elevated);
          overflow-x: auto;
          overflow-y: hidden;
          flex-shrink: 0;
          height: 34px;
          scrollbar-width: none;
        }
        .editor-tabs::-webkit-scrollbar { display: none; }

        .editor-tab {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 0 4px 0 12px;
          cursor: pointer;
          border-right: 1px solid var(--color-border);
          font-size: 12px;
          font-family: var(--font-sans);
          position: relative;
          min-width: 0;
          max-width: 200px;
          flex-shrink: 0;
          white-space: nowrap;
          transition: background 0.15s ease, color 0.15s ease;
          animation: tab-in 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }
        @keyframes tab-in {
          from { opacity: 0; transform: translateY(-100%); }
          to { opacity: 1; transform: translateY(0); }
        }
        .editor-tab[data-active="false"] {
          background: transparent;
          color: var(--color-text-secondary);
        }
        .editor-tab[data-active="true"] {
          background: var(--color-bg);
          color: var(--color-text);
        }
        .editor-tab:hover {
          background: var(--color-bg-card);
        }
        .editor-tab[data-active="true"]:hover {
          background: var(--color-bg);
        }
        .editor-tab-underline {
          position: absolute;
          bottom: 0;
          left: 0;
          right: 0;
          height: 1px;
          background: var(--color-accent);
          transform: scaleX(0);
          transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
        }
        .editor-tab[data-active="true"] .editor-tab-underline {
          transform: scaleX(1);
        }
        .editor-tab-name {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          flex: 1;
          min-width: 0;
        }
        .editor-tab-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          flex-shrink: 0;
          transition: background 0.2s ease, opacity 0.2s ease, transform 0.2s ease;
        }
        .editor-tab-dot[data-state="dirty"] {
          background: var(--color-accent);
        }
        .editor-tab-dot[data-state="saving"] {
          background: var(--color-amber);
          animation: tab-dot-pulse 1s ease-in-out infinite;
        }
        .editor-tab-dot[data-state="error"] {
          background: var(--color-red);
        }
        @keyframes tab-dot-pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.3; transform: scale(0.8); }
        }
        .editor-tab-close {
          width: 20px;
          height: 20px;
          display: flex;
          align-items: center;
          justify-content: center;
          border: none;
          background: none;
          border-radius: 3px;
          color: var(--color-text-tertiary);
          cursor: pointer;
          flex-shrink: 0;
          opacity: 0;
          transition: opacity 0.15s ease, background 0.1s ease, color 0.1s ease;
        }
        .editor-tab:hover .editor-tab-close {
          opacity: 0.7;
        }
        .editor-tab-close:hover {
          opacity: 1 !important;
          background: rgba(255, 255, 255, 0.06);
          color: var(--color-text);
        }
      `}</style>
      {tabs.map((tab) => {
        const active = tab.path === activeTab;
        const Icon = TYPE_ICONS[tab.specType] || FileText;
        const color = TYPE_COLORS[tab.specType] || "var(--color-text-tertiary)";

        return (
          <div
            key={tab.path}
            ref={active ? activeRef : undefined}
            onClick={() => onSelect(tab.path)}
            onMouseDown={(e) => {
              // Middle-click to close tab
              if (e.button === 1) {
                e.preventDefault();
                onClose(tab.path);
              }
            }}
            title={tab.path}
            className="editor-tab"
            role="tab"
            aria-selected={active}
            data-active={active ? "true" : "false"}
          >
            <Icon
              size={12}
              strokeWidth={1.5}
              style={{ color, flexShrink: 0, opacity: 0.7 }}
            />
            <span className="editor-tab-name">
              {getFilename(tab.path)}
            </span>
            {tab.saveState !== "clean" && (
              <span className="editor-tab-dot" data-state={tab.saveState} />
            )}
            <button
              className="editor-tab-close"
              aria-label={`Close ${getFilename(tab.path)}`}
              title="Close (⌘W)"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onClose(tab.path);
              }}
            >
              <X size={12} strokeWidth={1.5} />
            </button>
            <span className="editor-tab-underline" />
          </div>
        );
      })}
    </div>
  );
}
