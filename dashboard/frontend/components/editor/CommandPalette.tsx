"use client";

import { useEffect, useState } from "react";
import { Command } from "cmdk";
import {
  FileText,
  Code2,
  Palette,
  Bug,
  Eye,
  Pencil,
  PanelLeft,
  Save,
  Plus,
  X,
} from "lucide-react";
import type { DefineFeature, DefectData } from "@/lib/graphql/queries/define";

function toRelativePath(absPath: string): string {
  const idx = absPath.indexOf("specs/");
  return idx >= 0 ? absPath.slice(idx) : absPath;
}

const TYPE_ICONS: Record<string, typeof FileText> = {
  prd: FileText,
  rfc: Code2,
  dsn: Palette,
  defect: Bug,
};

const TYPE_COLORS: Record<string, string> = {
  prd: "var(--color-emerald)",
  rfc: "var(--color-blue)",
  dsn: "var(--color-violet)",
  defect: "var(--color-red)",
};

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  features: DefineFeature[];
  defects: DefectData[];
  onOpenSpec: (path: string) => void;
  onToggleExplorer: () => void;
  onSetMode: (mode: "preview" | "edit") => void;
  onNewSpec: () => void;
  onForceSave: () => void;
  onCloseTab: () => void;
}

export function CommandPalette({
  open,
  onClose,
  features,
  defects,
  onOpenSpec,
  onToggleExplorer,
  onSetMode,
  onNewSpec,
  onForceSave,
  onCloseTab,
}: CommandPaletteProps) {
  const [search, setSearch] = useState("");

  // Reset search when opening
  useEffect(() => {
    if (open) setSearch("");
  }, [open]);

  // Build spec items from features
  const specItems: { path: string; type: string; feature: string; label: string }[] = [];
  for (const f of features) {
    if (f.specified.productSpec.exists && f.specified.productSpec.path) {
      specItems.push({
        path: toRelativePath(f.specified.productSpec.path),
        type: "prd",
        feature: f.name,
        label: `${f.name} — PRD`,
      });
    }
    if (f.specified.technicalSpec.exists && f.specified.technicalSpec.path) {
      specItems.push({
        path: toRelativePath(f.specified.technicalSpec.path),
        type: "rfc",
        feature: f.name,
        label: `${f.name} — RFC`,
      });
    }
    if (f.specified.designSpec.exists && f.specified.designSpec.path) {
      specItems.push({
        path: toRelativePath(f.specified.designSpec.path),
        type: "dsn",
        feature: f.name,
        label: `${f.name} — DSN`,
      });
    }
  }

  return (
    <div className="cmd-overlay" data-open={open ? "true" : "false"} onClick={onClose}>
      <style>{`
        .cmd-overlay {
          position: fixed;
          inset: 0;
          z-index: 200;
          background: rgba(0, 0, 0, 0.5);
          display: flex;
          align-items: flex-start;
          justify-content: center;
          padding-top: 20vh;
          transition: opacity 0.15s ease, visibility 0.15s ease;
        }
        .cmd-overlay[data-open="true"] {
          opacity: 1;
          visibility: visible;
          pointer-events: auto;
        }
        .cmd-overlay[data-open="false"] {
          opacity: 0;
          visibility: hidden;
          pointer-events: none;
        }
        .cmd-dialog {
          width: 520px;
          max-height: 400px;
          background: var(--color-bg-elevated);
          border: 1px solid var(--color-border);
          border-radius: 10px;
          box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
          overflow: hidden;
          display: flex;
          flex-direction: column;
          transition: opacity 0.15s ease, transform 0.15s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .cmd-overlay[data-open="true"] .cmd-dialog {
          opacity: 1;
          transform: scale(1) translateY(0);
        }
        .cmd-overlay[data-open="false"] .cmd-dialog {
          opacity: 0;
          transform: scale(0.96) translateY(-8px);
        }
        .cmd-input {
          font-family: var(--font-sans);
          font-size: 14px;
          color: var(--color-text);
          background: transparent;
          border: none;
          outline: none;
          padding: 14px 16px;
          width: 100%;
          border-bottom: 1px solid var(--color-border);
        }
        .cmd-input::placeholder {
          color: var(--color-text-tertiary);
        }
        .cmd-list {
          overflow-y: auto;
          padding: 6px;
          scrollbar-width: thin;
          scrollbar-color: rgba(255,255,255,0.06) transparent;
        }
        .cmd-list::-webkit-scrollbar { width: 4px; }
        .cmd-list::-webkit-scrollbar-thumb {
          background: rgba(255,255,255,0.08);
          border-radius: 2px;
        }
        .cmd-empty {
          padding: 24px 16px;
          text-align: center;
          font-family: var(--font-sans);
          font-size: 12px;
          color: var(--color-text-tertiary);
        }
        .cmd-group-label {
          padding: 8px 10px 4px;
          font-family: var(--font-mono);
          font-size: 9px;
          font-weight: 500;
          color: var(--color-text-tertiary);
          text-transform: uppercase;
          letter-spacing: 0.05em;
        }
        .cmd-item {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 8px 10px;
          border-radius: 6px;
          cursor: pointer;
          font-family: var(--font-sans);
          font-size: 13px;
          color: var(--color-text-secondary);
          transition: background 0.1s ease, color 0.1s ease;
        }
        .cmd-item[data-selected="true"] {
          background: rgba(0, 212, 170, 0.08);
          color: var(--color-text);
        }
        .cmd-item-shortcut {
          margin-left: auto;
          font-family: var(--font-mono);
          font-size: 10px;
          color: var(--color-text-tertiary);
          display: flex;
          gap: 3px;
        }
        .cmd-item-shortcut kbd {
          padding: 1px 5px;
          border-radius: 3px;
          background: var(--color-bg-card);
          border: 1px solid var(--color-border);
        }
      `}</style>

      <div className="cmd-dialog" onClick={(e) => e.stopPropagation()}>
        <Command shouldFilter={true} loop>
          <Command.Input
            className="cmd-input"
            placeholder="Search specs, actions..."
            value={search}
            onValueChange={setSearch}
          />
          <Command.List className="cmd-list">
            <Command.Empty className="cmd-empty">No results</Command.Empty>

            {/* Actions */}
            <Command.Group heading={<span className="cmd-group-label">Actions</span>}>
              <Command.Item
                className="cmd-item"
                onSelect={() => { onNewSpec(); onClose(); }}
              >
                <Plus size={14} strokeWidth={1.5} style={{ color: "var(--color-accent)" }} />
                New spec
              </Command.Item>
              <Command.Item
                className="cmd-item"
                onSelect={() => { onForceSave(); onClose(); }}
              >
                <Save size={14} strokeWidth={1.5} style={{ color: "var(--color-text-tertiary)" }} />
                Save
                <span className="cmd-item-shortcut"><kbd>⌘</kbd><kbd>S</kbd></span>
              </Command.Item>
              <Command.Item
                className="cmd-item"
                onSelect={() => { onToggleExplorer(); onClose(); }}
              >
                <PanelLeft size={14} strokeWidth={1.5} style={{ color: "var(--color-text-tertiary)" }} />
                Toggle explorer
                <span className="cmd-item-shortcut"><kbd>⌘</kbd><kbd>E</kbd></span>
              </Command.Item>
              <Command.Item
                className="cmd-item"
                onSelect={() => { onSetMode("preview"); onClose(); }}
              >
                <Eye size={14} strokeWidth={1.5} style={{ color: "var(--color-text-tertiary)" }} />
                Preview mode
                <span className="cmd-item-shortcut"><kbd>⌘</kbd><kbd>⇧</kbd><kbd>P</kbd></span>
              </Command.Item>
              <Command.Item
                className="cmd-item"
                onSelect={() => { onSetMode("edit"); onClose(); }}
              >
                <Pencil size={14} strokeWidth={1.5} style={{ color: "var(--color-text-tertiary)" }} />
                Edit mode
                <span className="cmd-item-shortcut"><kbd>⌘</kbd><kbd>⇧</kbd><kbd>E</kbd></span>
              </Command.Item>
              <Command.Item
                className="cmd-item"
                onSelect={() => { onCloseTab(); onClose(); }}
              >
                <X size={14} strokeWidth={1.5} style={{ color: "var(--color-text-tertiary)" }} />
                Close tab
              </Command.Item>
            </Command.Group>

            {/* Specs */}
            <Command.Group heading={<span className="cmd-group-label">Specs</span>}>
              {specItems.map((item) => {
                const Icon = TYPE_ICONS[item.type] || FileText;
                const color = TYPE_COLORS[item.type] || "var(--color-text-tertiary)";
                return (
                  <Command.Item
                    key={item.path}
                    className="cmd-item"
                    value={item.label}
                    onSelect={() => { onOpenSpec(item.path); onClose(); }}
                  >
                    <Icon size={14} strokeWidth={1.5} style={{ color }} />
                    {item.label}
                  </Command.Item>
                );
              })}
            </Command.Group>

            {/* Defects */}
            {defects.length > 0 && (
              <Command.Group heading={<span className="cmd-group-label">Defects</span>}>
                {defects.map((d) => (
                  <Command.Item
                    key={d.name}
                    className="cmd-item"
                    value={`${d.name} ${d.severity} defect`}
                    onSelect={() => { onOpenSpec(`specs/defects/${d.name}.md`); onClose(); }}
                  >
                    <Bug size={14} strokeWidth={1.5} style={{ color: "var(--color-red)" }} />
                    <span style={{
                      fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 600,
                      color: d.severity <= "P1" ? "var(--color-red)" : "var(--color-amber)",
                    }}>
                      {d.severity}
                    </span>
                    {d.name}
                  </Command.Item>
                ))}
              </Command.Group>
            )}
          </Command.List>
        </Command>
      </div>
    </div>
  );
}
