"use client";

import { useState } from "react";
import { useMutation, useQuery } from "urql";
import { FileText, Code2, Palette, Bug, X, Sparkles, Loader2 } from "lucide-react";
import {
  AVAILABLE_MODELS_QUERY,
  BUILD_SPEC_DRAFT_MUTATION,
  type LLMModel,
  type SpecDraftResult,
} from "@/lib/graphql/queries/editor";

const SPEC_TYPES = [
  { value: "prd", label: "Product (PRD)", icon: FileText, color: "var(--color-emerald)", desc: "Problem, users, stories, scope" },
  { value: "rfc", label: "Technical (RFC)", icon: Code2, color: "var(--color-blue)", desc: "Data model, API, testing" },
  { value: "dsn", label: "Design (DSN)", icon: Palette, color: "var(--color-violet)", desc: "Layout, components, states" },
  { value: "defect", label: "Defect", icon: Bug, color: "var(--color-red)", desc: "Bug report with severity" },
] as const;

type Mode = "blank" | "generate";

interface NewSpecDialogProps {
  open: boolean;
  onClose: () => void;
  onCreate: (name: string, specType: string, content?: string) => void;
}

export function NewSpecDialog({ open, onClose, onCreate }: NewSpecDialogProps) {
  const [mode, setMode] = useState<Mode>("blank");
  const [name, setName] = useState("");
  const [specType, setSpecType] = useState("prd");
  const [error, setError] = useState<string | null>(null);
  const [problemStatement, setProblemStatement] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [generating, setGenerating] = useState(false);
  const [draft, setDraft] = useState<SpecDraftResult | null>(null);

  const [modelsResult] = useQuery<{ availableModels: LLMModel[] }>({
    query: AVAILABLE_MODELS_QUERY,
  });
  const models = modelsResult.data?.availableModels || [];
  if (!selectedModel && models.length > 0) {
    setSelectedModel(models[0].id);
  }

  const [, buildDraft] = useMutation<
    { buildSpecDraft: SpecDraftResult },
    { problemStatement: string; specType: string; model: string }
  >(BUILD_SPEC_DRAFT_MUTATION);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Name is required");
      return;
    }
    if (!/^[a-z0-9][a-z0-9-]*$/.test(trimmed)) {
      setError("Use lowercase letters, numbers, and hyphens");
      return;
    }
    // If we have a generated draft, pass its content
    onCreate(trimmed, specType, draft?.content);
    setName("");
    setError(null);
    setDraft(null);
    setProblemStatement("");
    setMode("blank");
    onClose();
  }

  async function handleGenerate() {
    if (!problemStatement.trim() || !selectedModel) return;
    setGenerating(true);
    setDraft(null);
    const result = await buildDraft({
      problemStatement: problemStatement.trim(),
      specType,
      model: selectedModel,
    });
    if (result.data?.buildSpecDraft) {
      setDraft(result.data.buildSpecDraft);
    }
    setGenerating(false);
  }

  return (
    <div className="dialog-overlay" data-open={open ? "true" : "false"} onClick={onClose}>
      <style>{`
        .dialog-overlay {
          position: fixed;
          inset: 0;
          z-index: 200;
          background: rgba(0, 0, 0, 0.5);
          display: flex;
          align-items: flex-start;
          justify-content: center;
          padding-top: 12vh;
          transition: opacity 0.15s ease, visibility 0.15s ease;
        }
        .dialog-overlay[data-open="true"] {
          opacity: 1;
          visibility: visible;
          pointer-events: auto;
        }
        .dialog-overlay[data-open="false"] {
          opacity: 0;
          visibility: hidden;
          pointer-events: none;
        }
        .dialog-panel {
          width: 540px;
          max-height: 70vh;
          background: var(--color-bg-elevated);
          border: 1px solid var(--color-border);
          border-radius: 10px;
          box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
          overflow: hidden;
          display: flex;
          flex-direction: column;
          transition: opacity 0.15s ease, transform 0.15s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .dialog-overlay[data-open="true"] .dialog-panel {
          opacity: 1;
          transform: scale(1) translateY(0);
        }
        .dialog-overlay[data-open="false"] .dialog-panel {
          opacity: 0;
          transform: scale(0.96) translateY(-8px);
        }
        .dialog-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 14px 16px;
          border-bottom: 1px solid var(--color-border);
          flex-shrink: 0;
        }
        .dialog-title {
          font-family: var(--font-mono);
          font-size: 13px;
          font-weight: 600;
          color: var(--color-text);
        }
        .dialog-close {
          width: 24px;
          height: 24px;
          display: flex;
          align-items: center;
          justify-content: center;
          border: none;
          background: none;
          border-radius: 4px;
          color: var(--color-text-tertiary);
          cursor: pointer;
          transition: background 0.1s, color 0.1s;
        }
        .dialog-close:hover {
          background: rgba(255,255,255,0.06);
          color: var(--color-text);
        }
        .dialog-body {
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 14px;
          overflow-y: auto;
        }
        .dialog-label {
          font-family: var(--font-mono);
          font-size: 10px;
          font-weight: 500;
          color: var(--color-text-tertiary);
          text-transform: uppercase;
          letter-spacing: 0.05em;
          margin-bottom: 6px;
        }
        .dialog-input {
          width: 100%;
          padding: 8px 10px;
          background: var(--color-bg);
          border: 1px solid var(--color-border);
          border-radius: 6px;
          font-family: var(--font-sans);
          font-size: 13px;
          color: var(--color-text);
          outline: none;
          transition: border-color 0.15s, box-shadow 0.15s;
        }
        .dialog-input:focus {
          border-color: rgba(0, 212, 170, 0.3);
          box-shadow: 0 0 0 2px rgba(0, 212, 170, 0.08);
        }
        .dialog-input::placeholder {
          color: var(--color-text-tertiary);
        }
        .dialog-textarea {
          width: 100%;
          padding: 8px 10px;
          background: var(--color-bg);
          border: 1px solid var(--color-border);
          border-radius: 6px;
          font-family: var(--font-sans);
          font-size: 12px;
          line-height: 1.5;
          color: var(--color-text);
          outline: none;
          resize: vertical;
          min-height: 80px;
          transition: border-color 0.15s, box-shadow 0.15s;
        }
        .dialog-textarea:focus {
          border-color: rgba(0, 212, 170, 0.3);
          box-shadow: 0 0 0 2px rgba(0, 212, 170, 0.08);
        }
        .dialog-textarea::placeholder {
          color: var(--color-text-tertiary);
        }
        .dialog-error {
          font-family: var(--font-sans);
          font-size: 11px;
          color: var(--color-red);
          margin-top: 4px;
        }
        .dialog-type-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 8px;
        }
        .dialog-type-btn {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 10px 12px;
          border: 1px solid var(--color-border);
          border-radius: 6px;
          background: transparent;
          cursor: pointer;
          text-align: left;
          transition: border-color 0.15s, background 0.15s;
        }
        .dialog-type-btn:hover {
          background: rgba(255,255,255,0.02);
        }
        .dialog-type-btn[data-selected="true"] {
          border-color: var(--color-accent);
          background: rgba(0, 212, 170, 0.04);
        }
        .dialog-type-label {
          font-family: var(--font-sans);
          font-size: 12px;
          font-weight: 500;
          color: var(--color-text);
        }
        .dialog-type-desc {
          font-family: var(--font-sans);
          font-size: 10px;
          color: var(--color-text-tertiary);
          margin-top: 1px;
        }
        .dialog-footer {
          display: flex;
          justify-content: flex-end;
          gap: 8px;
          padding: 12px 16px;
          border-top: 1px solid var(--color-border);
          flex-shrink: 0;
        }
        .dialog-btn {
          padding: 7px 16px;
          border-radius: 6px;
          font-family: var(--font-sans);
          font-size: 12px;
          font-weight: 500;
          cursor: pointer;
          transition: background 0.12s, transform 0.1s;
          border: 1px solid var(--color-border);
        }
        .dialog-btn:active { transform: scale(0.97); }
        .dialog-btn-secondary {
          background: transparent;
          color: var(--color-text-secondary);
        }
        .dialog-btn-secondary:hover {
          background: rgba(255,255,255,0.04);
        }
        .dialog-btn-primary {
          background: var(--color-accent);
          color: var(--color-bg);
          border-color: var(--color-accent);
          display: flex;
          align-items: center;
          gap: 5px;
        }
        .dialog-btn-primary:hover {
          background: #00c49b;
        }
        .dialog-btn-primary:disabled {
          opacity: 0.4;
          cursor: not-allowed;
        }
        .dialog-mode-tabs {
          display: flex;
          gap: 2px;
          padding: 2px;
          background: var(--color-bg);
          border-radius: 6px;
          border: 1px solid var(--color-border);
        }
        .dialog-mode-tab {
          flex: 1;
          padding: 6px 12px;
          border: none;
          border-radius: 4px;
          font-family: var(--font-sans);
          font-size: 11px;
          font-weight: 500;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 5px;
          transition: background 0.12s, color 0.12s;
        }
        .dialog-mode-tab[data-active="true"] {
          background: var(--color-bg-card);
          color: var(--color-text);
        }
        .dialog-mode-tab[data-active="false"] {
          background: transparent;
          color: var(--color-text-tertiary);
        }
        .dialog-draft-preview {
          max-height: 200px;
          overflow-y: auto;
          padding: 10px 12px;
          background: var(--color-bg);
          border: 1px solid var(--color-border);
          border-radius: 6px;
          font-family: var(--font-mono);
          font-size: 11px;
          line-height: 1.6;
          color: var(--color-text-secondary);
          white-space: pre-wrap;
          scrollbar-width: thin;
        }
      `}</style>

      <div className="dialog-panel" onClick={(e) => e.stopPropagation()}>
        <div className="dialog-header">
          <span className="dialog-title">New Spec</span>
          <button className="dialog-close" onClick={onClose}>
            <X size={14} strokeWidth={1.5} />
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="dialog-body">
            {/* Mode toggle */}
            <div className="dialog-mode-tabs">
              <button
                type="button"
                className="dialog-mode-tab"
                data-active={mode === "blank" ? "true" : "false"}
                onClick={() => setMode("blank")}
              >
                <FileText size={12} /> Blank Template
              </button>
              <button
                type="button"
                className="dialog-mode-tab"
                data-active={mode === "generate" ? "true" : "false"}
                onClick={() => setMode("generate")}
              >
                <Sparkles size={12} /> Generate with AI
              </button>
            </div>

            {/* Type selector */}
            <div>
              <div className="dialog-label">Type</div>
              <div className="dialog-type-grid">
                {SPEC_TYPES.map((t) => {
                  const Icon = t.icon;
                  return (
                    <button
                      key={t.value}
                      type="button"
                      className="dialog-type-btn"
                      data-selected={specType === t.value ? "true" : "false"}
                      onClick={() => setSpecType(t.value)}
                    >
                      <Icon size={14} strokeWidth={1.5} style={{ color: t.color, flexShrink: 0 }} />
                      <div>
                        <div className="dialog-type-label">{t.label}</div>
                        <div className="dialog-type-desc">{t.desc}</div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Generate mode: problem statement + model + generate button */}
            {mode === "generate" && (
              <>
                <div>
                  <div className="dialog-label">Problem Statement</div>
                  <textarea
                    className="dialog-textarea"
                    placeholder="Describe the problem this spec should solve. Be specific about the user pain, not the solution."
                    value={problemStatement}
                    onChange={(e) => setProblemStatement(e.target.value)}
                  />
                </div>

                <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
                  <div style={{ flex: 1 }}>
                    <div className="dialog-label">Model</div>
                    <select
                      value={selectedModel}
                      onChange={(e) => setSelectedModel(e.target.value)}
                      style={{
                        width: "100%", padding: "7px 8px",
                        background: "var(--color-bg)", color: "var(--color-text)",
                        border: "1px solid var(--color-border)", borderRadius: 6,
                        fontFamily: "var(--font-sans)", fontSize: 11,
                        outline: "none",
                      }}
                    >
                      {models.map((m) => (
                        <option key={m.id} value={m.id}>{m.label}</option>
                      ))}
                    </select>
                  </div>
                  <button
                    type="button"
                    onClick={handleGenerate}
                    disabled={!problemStatement.trim() || !selectedModel || generating}
                    className="dialog-btn dialog-btn-primary"
                    style={{ flexShrink: 0 }}
                  >
                    {generating ? (
                      <><Loader2 size={12} className="animate-spin" /> Generating...</>
                    ) : (
                      <><Sparkles size={12} /> Generate</>
                    )}
                  </button>
                </div>

                {/* Draft preview */}
                {draft && (
                  <div>
                    <div className="dialog-label">Generated Draft ({draft.sectionCount} sections)</div>
                    <div className="dialog-draft-preview">
                      {draft.content}
                    </div>
                  </div>
                )}
              </>
            )}

            {/* Name input */}
            <div>
              <div className="dialog-label">File Name</div>
              <input
                className="dialog-input"
                type="text"
                placeholder="speed-feature-name"
                value={name}
                onChange={(e) => { setName(e.target.value); setError(null); }}
                autoFocus={mode === "blank"}
              />
              {error && <div className="dialog-error">{error}</div>}
            </div>
          </div>

          <div className="dialog-footer">
            <button type="button" className="dialog-btn dialog-btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button
              type="submit"
              className="dialog-btn dialog-btn-primary"
              disabled={!name.trim() || (mode === "generate" && !draft)}
            >
              {mode === "generate" ? "Create from Draft" : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
