"use client";

import React, { useState } from "react";
import {
  type IntakeField,
  type IntakeInput,
} from "@/lib/graphql/queries/authoring";

export function ArtifactChoice({
  input,
  onSelect,
}: {
  input: IntakeInput;
  onSelect: (value: string) => void;
}) {
  return (
    <div className="surface" style={{ padding: "32px 24px", maxWidth: 560, width: "100%" }}>
      <div className="type-section-title">{input.prompt}</div>
      <div style={{ marginTop: 20, display: "flex", flexDirection: "column", gap: 4 }}>
        {(input.options ?? []).map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => option.value && onSelect(option.value)}
            style={{
              display: "flex",
              alignItems: "center",
              minHeight: 36,
              padding: "0 12px",
              borderRadius: 6,
              border: "1px solid var(--color-border)",
              background: "transparent",
              color: "var(--color-text)",
              fontFamily: "var(--font-sans)",
              fontSize: 13,
              textAlign: "left",
              cursor: "pointer",
            }}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export type GuidedArtifactType = "prd" | "design" | "rfc";

export function ArtifactTabs({
  value,
  onChange,
}: {
  value: GuidedArtifactType;
  onChange: (value: GuidedArtifactType) => void;
}) {
  const options: { value: GuidedArtifactType; label: string }[] = [
    { value: "prd", label: "PRD" },
    { value: "design", label: "Design" },
    { value: "rfc", label: "Technical RFC" },
  ];
  return (
    <div aria-label="Artifact type" style={{ display: "flex", gap: 4, padding: 4, borderRadius: 7, background: "var(--color-bg-elevated)", border: "1px solid var(--color-border)" }}>
      {options.map((option) => (
        <button key={option.value} type="button" aria-pressed={value === option.value} onClick={() => onChange(option.value)}
          className="type-badge" style={{ height: 30, padding: "0 14px", border: 0, borderRadius: 5, background: value === option.value ? "var(--color-accent-dim)" : "transparent", color: value === option.value ? "var(--color-accent)" : "var(--color-text-secondary)", cursor: "pointer" }}>
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function ArtifactSourceIntake({
  input,
  artifactType,
  submitting,
  serverError,
  onSelect,
}: {
  input: IntakeInput;
  artifactType: Exclude<GuidedArtifactType, "prd">;
  submitting: boolean;
  serverError: string | null;
  onSelect: (featureName: string) => void;
}) {
  const label = artifactType === "design" ? "Design" : "Technical RFC";
  return (
    <div className="surface" style={{ padding: "32px 24px", maxWidth: 560, width: "100%" }}>
      <div className="type-page-title">{input.prompt}</div>
      <div className="type-body" style={{ marginTop: 8 }}>Choose a published upstream version. The {label} agent will use that immutable snapshot as fixed context and ask only artifact-specific questions.</div>
      <div style={{ marginTop: 20, display: "flex", flexDirection: "column", gap: 8 }}>
        {(input.options ?? []).map((option) => (
          <button key={option.feature_name ?? option.value} type="button" disabled={submitting} onClick={() => onSelect(String(option.feature_name ?? option.value ?? ""))}
            style={{ minHeight: 48, padding: "10px 12px", textAlign: "left", borderRadius: 6, border: "1px solid var(--color-border)", background: "var(--color-bg-elevated)", color: "var(--color-text)", cursor: submitting ? "default" : "pointer" }}>
            <div className="type-section-title">{option.label ?? option.feature_name}</div>
            {option.path && <div className="type-caption" style={{ marginTop: 3, fontFamily: "var(--font-mono)" }}>{option.path}</div>}
          </button>
        ))}
        {(input.options ?? []).length === 0 && <div className="type-body">Create and publish a PRD first, then return here.</div>}
      </div>
      {serverError && <div role="alert" style={{ marginTop: 14, color: "var(--color-red)", fontSize: 12 }}>{serverError}</div>}
    </div>
  );
}

export function DesignBranchNotice({ onBack }: { onBack: () => void }) {
  return (
    <div className="surface" style={{ padding: "32px 24px", maxWidth: 560, width: "100%" }}>
      <div className="type-section-title">Design drafting runs in the terminal</div>
      <div className="type-body" style={{ marginTop: 8 }}>
        A design specification is pinned to its generated PRD, so it is authored through
        the CLI for now.
      </div>
      <div
        className="type-mono-value"
        style={{
          marginTop: 16,
          padding: 12,
          background: "var(--color-bg-elevated)",
          border: "1px solid var(--color-border)",
          borderRadius: 6,
          color: "var(--color-text-secondary)",
        }}
      >
        workbench draft design &lt;feature&gt;
      </div>
      <button
        type="button"
        className="type-badge"
        onClick={onBack}
        style={{
          marginTop: 16,
          background: "transparent",
          color: "var(--color-text-secondary)",
          border: "1px solid var(--color-border)",
          borderRadius: 4,
          padding: "6px 12px",
          cursor: "pointer",
        }}
      >
        Back
      </button>
    </div>
  );
}

function fieldById(fields: IntakeField[], id: string): IntakeField | undefined {
  return fields.find((field) => field.id === id);
}

export function GuidedPrdIntakeForm({
  input,
  submitting,
  serverError,
  onSubmit,
}: {
  input: IntakeInput;
  submitting: boolean;
  serverError: string | null;
  onSubmit: (description: string) => void;
}) {
  const fields = input.fields ?? [];
  const descriptionField = fieldById(fields, "feature_description");

  const [description, setDescription] = useState("");
  const ready = description.trim().length >= 10;

  const inputStyle: React.CSSProperties = {
    display: "block",
    width: "100%",
    marginTop: 8,
    padding: "10px 12px",
    background: "var(--color-bg-elevated)",
    border: "1px solid var(--color-border)",
    borderRadius: 6,
    color: "var(--color-text)",
    fontFamily: "var(--font-sans)",
  };

  return (
    <form
      className="surface"
      style={{ padding: "32px 24px", maxWidth: 560, width: "100%" }}
      onSubmit={(event) => {
        event.preventDefault();
        if (!ready || submitting) return;
        onSubmit(description.trim());
      }}
    >
      <div className="type-page-title">{input.prompt}</div>
      <div className="type-body" style={{ marginTop: 8 }}>
        Start with the idea in your own words. I’ll derive the title and ask only what the draft still needs.
      </div>

      <div style={{ marginTop: 20 }}>
        <label className="type-cell-label" htmlFor="feature_description">
          {descriptionField?.prompt ?? "What would you like to ship?"}
        </label>
        <textarea
          id="feature_description"
          value={description}
          disabled={submitting}
          autoFocus
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Describe what should change, who it helps, and why it matters…"
          style={{ ...inputStyle, fontSize: 14, minHeight: 132, lineHeight: 1.6, resize: "vertical" }}
        />
        <div className="type-caption" style={{ marginTop: 8 }}>
          {descriptionField?.description}
        </div>
      </div>

      {serverError && (
        <div
          role="alert"
          style={{ marginTop: 16, fontSize: 11, fontWeight: 500, color: "var(--color-red)" }}
        >
          {serverError}
        </div>
      )}

      <div style={{ marginTop: 20, display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button
          type="submit"
          className="type-badge"
          disabled={!ready || submitting}
          style={{
            height: 32,
            padding: "0 16px",
            borderRadius: 6,
            border: "none",
            background: "var(--color-accent)",
            color: "var(--color-bg)",
            cursor: "pointer",
            opacity: !ready || submitting ? 0.4 : 1,
          }}
        >
          {submitting ? "Starting…" : "Continue"}
        </button>
      </div>
    </form>
  );
}
