"use client";

import { useCallback, useEffect, useRef, useState, useMemo } from "react";
import { useMutation, useQuery, useSubscription } from "urql";
import { Toaster, toast } from "sonner";
import { DEFINE_VIEW_QUERY } from "@/lib/graphql/queries/define";
import type { DefineViewData, DefineFeature, DefectData } from "@/lib/graphql/queries/define";
import { Eye, Pencil } from "lucide-react";
import { IconRail } from "@/components/landing/IconRail";
import { SpecEditor, type SpecEditorHandle } from "@/components/editor/SpecEditor";
import { SpecPreview } from "@/components/editor/SpecPreview";
import { EditorTabs, type TabItem } from "@/components/editor/EditorTabs";
import { StatusBar } from "@/components/editor/StatusBar";
import { CommandPalette } from "@/components/editor/CommandPalette";
import { NewSpecDialog } from "@/components/editor/NewSpecDialog";
import { IntelPanel } from "@/components/editor/IntelPanel";
import {
  SPEC_QUERY,
  UPDATE_SPEC_CONTENT_MUTATION,
  CREATE_SPEC_MUTATION,
  SPEC_CHANGED_SUBSCRIPTION,
  GIT_BRANCH_QUERY,
  type SpecData,
  type SpecMutationResult,
} from "@/lib/graphql/queries/editor";

/* ── Inline Navigator ──────────────────────────────────────────── */

function specCount(f: DefineFeature): { have: number; total: number } {
  let have = 0;
  if (f.specified.productSpec.exists) have++;
  if (f.specified.technicalSpec.exists) have++;
  if (f.specified.designSpec.exists) have++;
  const extra = f.specified.additionalSpecs?.length ?? 0;
  have += extra;
  return { have, total: 3 + extra };
}

const STATE_PRIORITY: Record<string, number> = {
  running: 0, executing: 0, writing: 1, idle: 2,
  completed: 3, complete: 3, done: 3, unplanned: 4,
};

/** Convert absolute path to relative (specs/...) for the spec editor API. */
function toRelativePath(absPath: string): string {
  const idx = absPath.indexOf("specs/");
  return idx >= 0 ? absPath.slice(idx) : absPath;
}

function SpecRow({
  label,
  path,
  exists,
  active,
  color,
  onSelect,
}: {
  label: string;
  path: string | null;
  exists: boolean;
  active: boolean;
  color: string;
  onSelect: (path: string) => void;
}) {
  const relPath = path ? toRelativePath(path) : null;

  if (!exists || !relPath) {
    return (
      <div className="nav-spec-ghost">
        <span className="nav-spec-dot" style={{ border: "1px dashed var(--color-text-tertiary)" }} />
        <span className="nav-spec-label" style={{ color: "var(--color-text-tertiary)" }}>{label}</span>
        <span className="nav-spec-name" style={{ fontStyle: "italic", color: "var(--color-text-tertiary)" }}>missing</span>
      </div>
    );
  }

  return (
    <button
      className="nav-spec-row"
      onClick={() => onSelect(relPath)}
      data-active={active ? "true" : "false"}
    >
      <span className="nav-spec-dot" style={{ background: color }} />
      <span className="nav-spec-label" style={{ color }}>{label}</span>
      <span className="nav-spec-name">
        {relPath.split("/").pop()?.replace(".md", "")}
      </span>
    </button>
  );
}

function FeatureGroup({
  feature,
  activeSpec,
  onSelectSpec,
  defaultOpen,
}: {
  feature: DefineFeature;
  activeSpec: string | null;
  onSelectSpec: (path: string) => void;
  defaultOpen?: boolean;
}) {
  const { have, total } = specCount(feature);

  const typeColors: Record<string, string> = {
    product: "var(--color-emerald)", tech: "var(--color-blue)", design: "var(--color-violet)",
  };
  const typeLabels: Record<string, string> = {
    product: "PRD", tech: "RFC", design: "DSN",
  };

  const specs = [
    { label: "PRD", path: feature.specified.productSpec.path, exists: feature.specified.productSpec.exists, color: "var(--color-emerald)" },
    { label: "RFC", path: feature.specified.technicalSpec.path, exists: feature.specified.technicalSpec.exists, color: "var(--color-blue)" },
    { label: "DSN", path: feature.specified.designSpec.path, exists: feature.specified.designSpec.exists, color: "var(--color-violet)" },
    ...(feature.specified.additionalSpecs || []).map((s) => ({
      label: typeLabels[s.specType] || s.specType.toUpperCase(),
      path: s.path,
      exists: true,
      color: typeColors[s.specType] || "var(--color-text-tertiary)",
    })),
  ];

  const isActive = specs.some((s) => s.path && activeSpec === toRelativePath(s.path));
  const [expanded, setExpanded] = useState(defaultOpen ?? isActive);

  // Auto-expand when a spec inside this group becomes active
  useEffect(() => {
    if (isActive) setExpanded(true);
  }, [isActive]);

  return (
    <div>
      <button className="nav-feature-btn" onClick={() => setExpanded(!expanded)}>
        <svg
          width={10} height={10} viewBox="0 0 10 10" fill="none"
          stroke="currentColor" strokeWidth={1.5}
          className="nav-feature-chevron"
          data-open={expanded ? "true" : "false"}
        >
          <path d="M3 1l4 4-4 4" />
        </svg>
        <span className="nav-feature-name">{feature.name.replace(/^speed-/, "")}</span>
        <span className="nav-feature-count" style={{
          color: have === total ? "var(--color-emerald)" : "var(--color-amber)",
        }}>
          {have}/{total}
        </span>
      </button>
      <div className="nav-feature-children" data-open={expanded ? "true" : "false"}>
        <div style={{ overflow: "hidden" }}>
          <div style={{ padding: "2px 0 4px" }}>
            {specs.map((s, i) => (
              <SpecRow
                key={s.path || `${s.label}-${i}`}
                label={s.label}
                path={s.path}
                exists={s.exists}
                active={activeSpec === (s.path ? toRelativePath(s.path) : null)}
                color={s.color}
                onSelect={onSelectSpec}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function severityColor(sev: string): string {
  if (sev === "P0" || sev === "P1") return "var(--color-red)";
  if (sev === "P2") return "var(--color-amber)";
  return "var(--color-text-tertiary)";
}

function Navigator({
  features,
  defects,
  activeSpec,
  onSelectSpec,
  open = true,
}: {
  features: DefineFeature[];
  defects: DefectData[];
  activeSpec: string | null;
  onSelectSpec: (path: string) => void;
  open?: boolean;
}) {
  const [search, setSearch] = useState("");

  const sorted = useMemo(
    () => [...features].sort((a, b) =>
      (STATE_PRIORITY[a.state] ?? 4) - (STATE_PRIORITY[b.state] ?? 4)
    ),
    [features]
  );

  const filtered = useMemo(() => {
    if (!search) return sorted;
    const q = search.toLowerCase();
    return sorted.filter((f) => f.name.toLowerCase().includes(q));
  }, [sorted, search]);

  const filteredDefects = useMemo(() => {
    if (!search) return defects;
    const q = search.toLowerCase();
    return defects.filter((d) => d.name.toLowerCase().includes(q) || d.description.toLowerCase().includes(q));
  }, [defects, search]);

  const activeFeature = activeSpec
    ? features.find((f) =>
        [f.specified.productSpec.path, f.specified.technicalSpec.path, f.specified.designSpec.path]
          .filter(Boolean)
          .map((p) => toRelativePath(p!))
          .includes(activeSpec)
      )
    : null;

  return (
    <div className="nav-panel" data-open={open ? "true" : "false"}>
      <style>{`
        .nav-panel {
          flex-shrink: 0;
          display: flex;
          flex-direction: column;
          background: var(--color-bg-elevated);
          border-right: 1px solid var(--color-border);
          height: 100%;
          overflow: hidden;
          transition: width 0.25s cubic-bezier(0.4, 0, 0.2, 1),
                      opacity 0.2s ease;
        }
        .nav-panel[data-open="true"] {
          width: 280px;
          opacity: 1;
        }
        .nav-panel[data-open="false"] {
          width: 0;
          opacity: 0;
          border-right: none;
        }
        .nav-header {
          padding: 12px 16px 0;
          flex-shrink: 0;
        }
        .nav-title {
          font-family: var(--font-mono);
          font-size: 11px;
          font-weight: 600;
          color: var(--color-text-secondary);
          text-transform: uppercase;
          letter-spacing: 0.05em;
          margin-bottom: 8px;
        }
        .nav-search-wrap {
          position: relative;
          margin-bottom: 8px;
        }
        .nav-search-icon {
          position: absolute;
          left: 8px;
          top: 50%;
          transform: translateY(-50%);
        }
        .nav-search {
          width: 100%;
          padding: 6px 8px 6px 26px;
          background: var(--color-bg);
          border: 1px solid var(--color-border);
          border-radius: 5px;
          font-family: var(--font-sans);
          font-size: 11px;
          color: var(--color-text);
          outline: none;
          transition: border-color 0.15s ease, box-shadow 0.15s ease;
        }
        .nav-search:focus {
          border-color: rgba(0, 212, 170, 0.3);
          box-shadow: 0 0 0 2px rgba(0, 212, 170, 0.08);
        }
        .nav-divider {
          height: 1px;
          background: var(--color-border);
        }
        .nav-list {
          flex: 1;
          overflow-y: auto;
          padding: 4px 0 8px;
          scrollbar-width: thin;
          scrollbar-color: rgba(255,255,255,0.06) transparent;
        }
        .nav-list::-webkit-scrollbar { width: 4px; }
        .nav-list::-webkit-scrollbar-track { background: transparent; }
        .nav-list::-webkit-scrollbar-thumb {
          background: rgba(255,255,255,0.08);
          border-radius: 2px;
        }
        .nav-empty {
          padding: 16px;
          font-family: var(--font-sans);
          font-size: 11px;
          color: var(--color-text-tertiary);
        }

        /* Feature group */
        .nav-feature-btn {
          display: flex;
          align-items: center;
          width: 100%;
          padding: 6px 16px;
          background: none;
          border: none;
          cursor: pointer;
          gap: 6px;
          text-align: left;
          color: var(--color-text-tertiary);
          min-width: 0;
          transition: background 0.12s ease;
        }
        .nav-feature-btn:hover {
          background: rgba(255, 255, 255, 0.02);
        }
        .nav-feature-chevron {
          flex-shrink: 0;
          transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
        }
        .nav-feature-chevron[data-open="true"] {
          transform: rotate(90deg);
        }
        .nav-feature-name {
          flex: 1;
          font-family: var(--font-sans);
          font-size: 12px;
          font-weight: 500;
          color: var(--color-text);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .nav-feature-count {
          font-family: var(--font-mono);
          font-size: 10px;
          font-weight: 500;
          flex-shrink: 0;
          transition: color 0.15s ease;
        }
        .nav-feature-children {
          display: grid;
          grid-template-rows: 0fr;
          transition: grid-template-rows 0.2s ease;
        }
        .nav-feature-children[data-open="true"] {
          grid-template-rows: 1fr;
        }
        .nav-feature-children > div {
          overflow: hidden;
          min-height: 0;
        }

        /* Spec rows */
        .nav-spec-row {
          display: flex;
          align-items: center;
          gap: 8px;
          width: 100%;
          padding: 4px 16px 4px 32px;
          background: transparent;
          border: none;
          border-radius: 3px;
          cursor: pointer;
          text-align: left;
          position: relative;
          transition: background 0.12s ease;
        }
        .nav-spec-row:hover {
          background: rgba(255, 255, 255, 0.03);
        }
        .nav-spec-row[data-active="true"] {
          background: var(--color-bg-card-hover);
        }
        .nav-spec-row[data-active="true"]:hover {
          background: var(--color-bg-card-hover);
        }
        .nav-spec-row[data-active="true"]::before {
          content: "";
          position: absolute;
          left: 16px;
          top: 50%;
          transform: translateY(-50%);
          width: 2px;
          height: 12px;
          border-radius: 1px;
          background: var(--color-accent);
        }
        .nav-spec-ghost {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 4px 16px 4px 32px;
          opacity: 0.6;
          transition: opacity 0.15s ease;
        }
        .nav-spec-ghost:hover {
          opacity: 0.8;
        }
        .nav-spec-dot {
          width: 5px;
          height: 5px;
          border-radius: 50%;
          flex-shrink: 0;
        }
        .nav-spec-label {
          font-family: var(--font-mono);
          font-size: 9px;
          font-weight: 500;
          min-width: 22px;
          flex-shrink: 0;
        }
        .nav-spec-name {
          flex: 1;
          font-family: var(--font-sans);
          font-size: 11px;
          color: var(--color-text-secondary);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          transition: color 0.12s ease;
        }
        .nav-spec-row[data-active="true"] .nav-spec-name {
          color: var(--color-text);
        }

        /* Section label */
        .nav-section-label {
          padding: 16px 16px 6px;
          font-family: var(--font-mono);
          font-size: 9px;
          font-weight: 500;
          color: var(--color-text-tertiary);
          text-transform: uppercase;
          letter-spacing: 0.06em;
        }

        /* Defect rows */
        .nav-defect-row {
          display: flex;
          align-items: center;
          gap: 8px;
          width: 100%;
          padding: 4px 16px;
          border: none;
          border-radius: 3px;
          cursor: pointer;
          text-align: left;
          background: transparent;
          position: relative;
          min-width: 0;
          transition: background 0.12s ease;
        }
        .nav-defect-row:hover {
          background: rgba(255, 255, 255, 0.03);
        }
        .nav-defect-row[data-active="true"] {
          background: var(--color-bg-card-hover);
        }
        .nav-defect-row[data-active="true"]::before {
          content: "";
          position: absolute;
          left: 4px;
          top: 50%;
          transform: translateY(-50%);
          width: 2px;
          height: 12px;
          border-radius: 1px;
          background: var(--color-red);
        }
        .nav-defect-severity {
          font-family: var(--font-mono);
          font-size: 9px;
          font-weight: 600;
          min-width: 20px;
          flex-shrink: 0;
        }
        .nav-defect-name {
          font-family: var(--font-sans);
          font-size: 11px;
          color: var(--color-text-secondary);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          flex: 1;
        }
        .nav-defect-status {
          font-family: var(--font-mono);
          font-size: 9px;
          color: var(--color-text-tertiary);
          flex-shrink: 0;
          text-transform: uppercase;
        }

        /* Spinner */
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
        .animate-spin {
          animation: spin 1s linear infinite;
        }

        /* Content transitions */
        @keyframes content-fade-in {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }

        /* Intel panel */
        .intel-panel-wrapper {
          flex-shrink: 0;
          overflow: hidden;
          transition: width 0.25s cubic-bezier(0.4, 0, 0.2, 1),
                      opacity 0.2s ease,
                      border-color 0.2s ease;
        }
        .intel-panel-wrapper[data-open="true"] {
          width: 280px;
          opacity: 1;
          border-left: 1px solid var(--color-border);
        }
        .intel-panel-wrapper[data-open="false"] {
          width: 0;
          opacity: 0;
          border-left: 1px solid transparent;
        }

        /* Mode toggle */
        .mode-toggle {
          display: flex;
          align-items: center;
          gap: 2px;
          padding: 0 8px;
          flex-shrink: 0;
          border-bottom: 1px solid var(--color-border);
          background: var(--color-bg-elevated);
        }
        .mode-btn {
          width: 28px;
          height: 24px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 4px;
          border: none;
          cursor: pointer;
          transition: color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease, transform 0.1s ease;
        }
        .mode-btn:hover {
          transform: scale(1.08);
        }
        .mode-btn:active {
          transform: scale(0.92);
        }
        .mode-btn[data-active="true"] {
          color: var(--color-accent);
          background: rgba(0, 212, 170, 0.08);
          box-shadow: 0 0 0 1px rgba(0, 212, 170, 0.15);
        }
        .mode-btn[data-active="false"] {
          color: var(--color-text-tertiary);
          background: transparent;
          box-shadow: none;
        }
      `}</style>

      <div className="nav-header">
        <div className="nav-title">Specs</div>
        <div className="nav-search-wrap">
          <svg className="nav-search-icon" width={12} height={12} viewBox="0 0 24 24" fill="none"
            stroke="var(--color-text-tertiary)" strokeWidth={1.5}>
            <circle cx={11} cy={11} r={8} /><line x1={21} y1={21} x2={16.65} y2={16.65} />
          </svg>
          <input
            className="nav-search"
            type="text" placeholder="Search features..."
            value={search} onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Escape" && search) { e.stopPropagation(); setSearch(""); } }}
          />
        </div>
        <div className="nav-divider" />
      </div>

      <div className="nav-list">
        {filtered.length === 0 && filteredDefects.length === 0 ? (
          <div className="nav-empty">{search ? "No matches" : "No specs"}</div>
        ) : (
          <>
            {filtered.length > 0 && filtered.map((f) => (
              <FeatureGroup
                key={f.name}
                feature={f}
                activeSpec={activeSpec}
                onSelectSpec={onSelectSpec}
                defaultOpen={f.name === activeFeature?.name}
              />
            ))}

            {filteredDefects.length > 0 && (
              <>
                <div className="nav-section-label">Defects · {filteredDefects.length}</div>
                {filteredDefects.map((d) => (
                  <button
                    key={d.name}
                    className="nav-defect-row"
                    onClick={() => onSelectSpec(`specs/defects/${d.name}.md`)}
                    data-active={activeSpec === `specs/defects/${d.name}.md` ? "true" : "false"}
                  >
                    <span className="nav-defect-severity" style={{ color: severityColor(d.severity) }}>
                      {d.severity}
                    </span>
                    <span className="nav-defect-name">{d.name.replace(/-/g, " ")}</span>
                    <span className="nav-defect-status">{d.status}</span>
                  </button>
                ))}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/* ── Empty State ────────────────────────────────────────────────── */

function EmptyState() {
  return (
    <div style={{
      flex: 1, display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center", gap: 12,
      color: "var(--color-text-tertiary)",
    }}>
      <span style={{
        fontFamily: "var(--font-mono)", fontSize: 12, letterSpacing: "0.02em",
        opacity: 0.6,
      }}>
        Select a spec to edit
      </span>
    </div>
  );
}

/* ── Editor Page ────────────────────────────────────────────────── */

const SESSION_KEY = "speed_editor_session";

interface EditorSession {
  openTabs: { path: string; specType: string }[];
  activeTab: string | null;
  explorerOpen: boolean;
  mode: "preview" | "edit";
}

function readSession(): EditorSession | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as EditorSession;
  } catch {
    return null;
  }
}

function writeSession(session: EditorSession): void {
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } catch {}
}

export default function EditorPage() {
  const [activeSpec, setActiveSpec] = useState<string | null>(null);
  const [tabs, setTabs] = useState<TabItem[]>([]);
  const [explorerOpen, setExplorerOpen] = useState(true);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [newSpecOpen, setNewSpecOpen] = useState(false);
  const [mode, setMode] = useState<"preview" | "edit">("preview");
  const hydrated = useRef(false);

  // Restore session from localStorage after hydration (SSR-safe)
  useEffect(() => {
    const session = readSession();
    if (session) {
      const openTabs = Array.isArray(session.openTabs) ? session.openTabs : [];
      if (openTabs.length > 0) {
        setTabs(openTabs.map(t => ({
          path: t.path,
          specType: t.specType,
          saveState: "clean" as const,
        })));
      }
      if (session.activeTab) setActiveSpec(session.activeTab);
      if (typeof session.explorerOpen === "boolean") setExplorerOpen(session.explorerOpen);
      if (session.mode === "preview" || session.mode === "edit") setMode(session.mode);
    }
    hydrated.current = true;
  }, []);

  // Persist session to localStorage on state changes
  useEffect(() => {
    if (!hydrated.current) return;
    writeSession({
      openTabs: tabs.map(t => ({ path: t.path, specType: t.specType })),
      activeTab: activeSpec,
      explorerOpen,
      mode,
    });
  }, [tabs, activeSpec, explorerOpen, mode]);

  // Ref that always holds the current activeSpec for use in event handlers
  const activeSpecRef = useRef<string | null>(null);
  const editorRef = useRef<SpecEditorHandle>(null);
  activeSpecRef.current = activeSpec;

  // Per-path pending content for flush-save
  const pendingContentRef = useRef<Map<string, string>>(new Map());
  const saveTimeoutRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const savingRef = useRef<Set<string>>(new Set());

  const [defineResult, reexecuteDefine] = useQuery<DefineViewData>({ query: DEFINE_VIEW_QUERY });
  const [gitResult] = useQuery<{ gitBranch: string | null }>({ query: GIT_BRANCH_QUERY });

  const [specResult, reexecuteSpec] = useQuery<SpecData>({
    query: SPEC_QUERY,
    variables: { path: activeSpec || "" },
    pause: !activeSpec,
  });

  const [, updateContent] = useMutation<
    { updateSpecContent: SpecMutationResult },
    { path: string; content: string }
  >(UPDATE_SPEC_CONTENT_MUTATION);

  const [, createSpec] = useMutation<
    { createSpec: SpecMutationResult },
    { name: string; specType: string; feature?: string }
  >(CREATE_SPEC_MUTATION);

  // Ignore our own save events from the watcher
  useSubscription({ query: SPEC_CHANGED_SUBSCRIPTION }, (_prev, data) => {
    if (data?.specChanged) {
      const changedPath = data.specChanged.path;
      if (savingRef.current.has(changedPath)) {
        savingRef.current.delete(changedPath);
        return data;
      }
      if (changedPath === activeSpec) {
        reexecuteSpec({ requestPolicy: "network-only" });
      }
    }
    return data;
  });

  const view = defineResult.data?.defineView;

  // ── Tab helpers ──

  const setTabState = useCallback((path: string, saveState: TabItem["saveState"]) => {
    setTabs((prev) => prev.map((t) => t.path === path ? { ...t, saveState } : t));
  }, []);

  // ── Save logic ──

  const executeSave = useCallback(async (path: string, content: string) => {
    setTabState(path, "saving");
    savingRef.current.add(path);
    const result = await updateContent({ path, content });
    if (result.data?.updateSpecContent?.success) {
      pendingContentRef.current.delete(path);
      setTabState(path, "clean");
    } else {
      setTabState(path, "error");
      toast.error(`Save failed: ${result.data?.updateSpecContent?.error || "Unknown error"}`);
    }
  }, [updateContent, setTabState]);

  const flushSave = useCallback(async (path: string) => {
    // Cancel any pending debounce
    const timeout = saveTimeoutRef.current.get(path);
    if (timeout) {
      clearTimeout(timeout);
      saveTimeoutRef.current.delete(path);
    }
    const content = pendingContentRef.current.get(path);
    if (content !== undefined) {
      await executeSave(path, content);
    }
  }, [executeSave]);

  // ── Tab management ──

  const openSpec = useCallback((path: string) => {
    setActiveSpec(path);
    setTabs((prev) => {
      if (prev.some((t) => t.path === path)) return prev;
      let specType = "prd";
      if (path.includes("/tech/")) specType = "rfc";
      else if (path.includes("/design/")) specType = "dsn";
      else if (path.includes("/defects/")) specType = "defect";
      return [...prev, { path, specType, saveState: "clean" }];
    });
  }, []);

  const closeTab = useCallback(async (closePath: string) => {
    // Flush any pending save before closing
    await flushSave(closePath);
    pendingContentRef.current.delete(closePath);

    setTabs((prev) => {
      const next = prev.filter((t) => t.path !== closePath);
      setActiveSpec((current) => {
        if (current !== closePath) return current;
        return next.length > 0 ? next[next.length - 1].path : null;
      });
      return next;
    });
  }, [flushSave]);

  // ── Content change handler (debounced auto-save) ──

  const handleCreateSpec = useCallback(async (name: string, specType: string, content?: string) => {
    const result = await createSpec({ name, specType });
    if (result.data?.createSpec?.success && result.data.createSpec.path) {
      const path = result.data.createSpec.path;
      if (content) {
        await updateContent({ path, content });
      }
      openSpec(path);
      setMode("edit");
      toast.success(`Created ${path}`);
      // Refresh navigator so new spec appears immediately
      reexecuteDefine({ requestPolicy: "network-only" });
    } else {
      toast.error(result.data?.createSpec?.error || "Failed to create spec");
    }
  }, [createSpec, updateContent, openSpec, reexecuteDefine]);

  const handleContentChange = useCallback((markdown: string) => {
    if (!activeSpec) return;

    pendingContentRef.current.set(activeSpec, markdown);
    setTabState(activeSpec, "dirty");

    const existing = saveTimeoutRef.current.get(activeSpec);
    if (existing) clearTimeout(existing);

    const path = activeSpec;
    const timeout = setTimeout(() => {
      const content = pendingContentRef.current.get(path);
      if (content !== undefined) {
        executeSave(path, content);
      }
    }, 1500);
    saveTimeoutRef.current.set(activeSpec, timeout);
  }, [activeSpec, executeSave, setTabState]);

  // ── Keyboard shortcuts ──

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const mod = e.metaKey || e.ctrlKey;
      if (!mod) return;

      // Mod+Shift combos
      if (e.shiftKey) {
        switch (e.key.toLowerCase()) {
          case "p": // Preview mode
            e.preventDefault();
            setMode("preview");
            return;
          case "e": // Edit mode
            e.preventDefault();
            setMode("edit");
            return;
        }
      }

      // Mod combos (only keys that don't conflict with Safari/browser defaults)
      switch (e.key) {
        case "e": // Toggle explorer
          e.preventDefault();
          setExplorerOpen((v) => !v);
          return;

        case "k": // Command palette
          e.preventDefault();
          setCmdOpen((v) => !v);
          return;

        case "s": { // Force save
          e.preventDefault();
          const path = activeSpecRef.current;
          if (path) flushSave(path);
          return;
        }
        // Note: ⌘W and ⌘N omitted — Safari intercepts them at OS level
      }

      // Ctrl+Tab / Ctrl+Shift+Tab to cycle tabs
      if (e.key === "Tab" && e.ctrlKey) {
        e.preventDefault();
        setTabs((currentTabs) => {
          if (currentTabs.length < 2) return currentTabs;
          const currentPath = activeSpecRef.current;
          const idx = currentTabs.findIndex((t) => t.path === currentPath);
          const next = e.shiftKey
            ? (idx - 1 + currentTabs.length) % currentTabs.length
            : (idx + 1) % currentTabs.length;
          setActiveSpec(currentTabs[next].path);
          return currentTabs;
        });
      }
    }
    // Capture phase to intercept before browser defaults (⌘N, ⌘W)
    document.addEventListener("keydown", handleKeyDown, true);
    return () => document.removeEventListener("keydown", handleKeyDown, true);
  }, [flushSave, closeTab]);

  // ── Beforeunload guard ──

  const hasDirtyTabs = tabs.some((t) => t.saveState === "dirty" || t.saveState === "saving");

  useEffect(() => {
    if (!hasDirtyTabs) return;
    function handleBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [hasDirtyTabs]);

  const [cursor, setCursor] = useState<{ line: number; col: number } | null>(null);
  const spec = specResult.data?.spec;

  // Browser tab title
  useEffect(() => {
    const dirty = tabs.some((t) => t.saveState !== "clean");
    const name = activeSpec?.split("/").pop()?.replace(".md", "");
    document.title = [dirty ? "●" : "", name || "Editor", "— SPEED"].filter(Boolean).join(" ");
    return () => { document.title = "SPEED Dashboard"; };
  }, [activeSpec, tabs]);
  const activeTabState = tabs.find((t) => t.path === activeSpec)?.saveState;
  const connected = !specResult.error;

  return (
    <>
      <Toaster
        position="bottom-right"
        toastOptions={{
          style: {
            background: "var(--color-bg-card)",
            border: "1px solid var(--color-border)",
            color: "var(--color-text)",
            fontFamily: "var(--font-sans)",
            fontSize: 12,
          },
        }}
      />

      {view && (
        <CommandPalette
          open={cmdOpen}
          onClose={() => setCmdOpen(false)}
          features={view.features}
          defects={view.defects}
          onOpenSpec={openSpec}
          onToggleExplorer={() => setExplorerOpen((v) => !v)}
          onSetMode={setMode}
          onNewSpec={() => { setCmdOpen(false); setNewSpecOpen(true); }}
          onForceSave={() => { const p = activeSpecRef.current; if (p) flushSave(p); }}
          onCloseTab={() => { const p = activeSpecRef.current; if (p) closeTab(p); }}
        />
      )}

      <NewSpecDialog
        open={newSpecOpen}
        onClose={() => setNewSpecOpen(false)}
        onCreate={handleCreateSpec}
      />

      <div style={{
        display: "flex", height: "100vh", overflow: "hidden",
        background: "var(--color-bg)",
      }}>
        <IconRail
          explorerOpen={explorerOpen}
          onToggleExplorer={() => setExplorerOpen((v) => !v)}
        />

        {view ? (
          <Navigator
            features={view.features}
            defects={view.defects}
            activeSpec={activeSpec}
            onSelectSpec={openSpec}
            open={explorerOpen}
          />
        ) : (
          <div className="nav-panel" data-open={explorerOpen ? "true" : "false"}>
            <div style={{
              flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
              color: "var(--color-text-tertiary)", fontSize: 11, fontFamily: "var(--font-sans)",
              whiteSpace: "nowrap",
            }}>
              {defineResult.fetching ? "Loading..." : defineResult.error ? "Connection error" : "No data"}
            </div>
          </div>
        )}

        <div style={{
          flex: 1, display: "flex", flexDirection: "column", overflow: "hidden",
        }}>
          {/* Tab bar + mode toggle */}
          <div style={{
            display: "flex", alignItems: "stretch",
            borderBottom: tabs.length > 0 ? "none" : "1px solid var(--color-border)",
          }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <EditorTabs
                tabs={tabs}
                activeTab={activeSpec}
                onSelect={setActiveSpec}
                onClose={closeTab}
              />
            </div>
            {activeSpec && spec && (
              <div className="mode-toggle">
                <button
                  className="mode-btn"
                  onClick={() => setMode("preview")}
                  title="Preview (⌘⇧P)"
                  data-active={mode === "preview" ? "true" : "false"}
                >
                  <Eye size={13} strokeWidth={1.5} />
                </button>
                <button
                  className="mode-btn"
                  onClick={() => setMode("edit")}
                  title="Edit (⌘⇧E)"
                  data-active={mode === "edit" ? "true" : "false"}
                >
                  <Pencil size={13} strokeWidth={1.5} />
                </button>
              </div>
            )}
          </div>

          {activeSpec && spec ? (
            <div key={`${activeSpec}-${mode}`} style={{
              flex: 1, display: "flex", flexDirection: "column",
              overflow: "hidden",
              animation: "content-fade-in 0.15s ease",
            }}>
              {mode === "edit" ? (
                <SpecEditor
                  ref={editorRef}
                  key={activeSpec}
                  content={spec.content}
                  specType={spec.specType}
                  onChange={handleContentChange}
                  onCursorChange={setCursor}
                />
              ) : (
                <SpecPreview content={spec.content} />
              )}
            </div>
          ) : activeSpec && specResult.fetching ? (
            <div style={{
              flex: 1, display: "flex", alignItems: "center",
              justifyContent: "center", color: "var(--color-text-tertiary)",
              fontSize: 12, fontFamily: "var(--font-mono)",
            }}>
              Loading...
            </div>
          ) : activeSpec && specResult.error ? (
            <div style={{
              flex: 1, display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center", gap: 8,
              color: "var(--color-red)", fontSize: 12, fontFamily: "var(--font-mono)",
            }}>
              <span>Failed to load spec</span>
              <span style={{ color: "var(--color-text-tertiary)", fontSize: 11 }}>
                {specResult.error.message}
              </span>
            </div>
          ) : (
            <EmptyState />
          )}

          <StatusBar
            connected={connected}
            activeSpec={activeSpec}
            completeness={spec?.completeness ?? null}
            specCount={view ? view.features.length : 0}
            saveState={activeTabState}
            cursor={mode === "edit" ? cursor : null}
            lifecycle={spec?.lifecycleState}
            gitBranch={gitResult.data?.gitBranch}
          />
        </div>

        {/* Intelligence panel */}
        <div className="intel-panel-wrapper" data-open={activeSpec && spec ? "true" : "false"}>
          {activeSpec && spec && (
            <IntelPanel
              specPath={activeSpec}
              onOpenSpec={openSpec}
              onApplyFix={(oldText, newText) => {
                if (!activeSpec || !spec) return false;
                if (!spec.content.includes(oldText)) return false;
                // Switch to edit mode so the user sees the scroll + highlight
                if (mode !== "edit") {
                  setMode("edit");
                  // Need a tick for CodeMirror to mount before we can call replaceAndHighlight
                  setTimeout(() => {
                    editorRef.current?.replaceAndHighlight(oldText, newText);
                  }, 100);
                  return true;
                }
                if (editorRef.current) {
                  return editorRef.current.replaceAndHighlight(oldText, newText);
                }
                return false;
              }}
            />
          )}
        </div>
      </div>
    </>
  );
}
