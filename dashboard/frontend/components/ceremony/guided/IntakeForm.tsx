"use client";

import React, { useMemo, useState } from "react";
import {
  deriveSlug,
  isValidSlug,
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
  existingStatus,
  serverError,
  onSlugChange,
  onSubmit,
  onResume,
}: {
  input: IntakeInput;
  submitting: boolean;
  existingStatus: string | null;
  serverError: string | null;
  onSlugChange: (slug: string) => void;
  onSubmit: (title: string, slug: string, description: string) => void;
  onResume: (slug: string) => void;
}) {
  const fields = input.fields ?? [];
  const titleField = fieldById(fields, "feature_title");
  const slugField = fieldById(fields, "feature_slug");
  const descriptionField = fieldById(fields, "feature_description");

  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [description, setDescription] = useState("");

  const slugError = useMemo(() => {
    if (!slug) return null;
    return isValidSlug(slug)
      ? null
      : "Use lowercase letters, digits, and single hyphens, 1 to 50 characters.";
  }, [slug]);

  const collision = Boolean(existingStatus && existingStatus !== "not_started");
  const ready =
    title.trim().length > 0 &&
    slug.length > 0 &&
    !slugError &&
    description.trim().length > 0;

  const applyTitle = (value: string) => {
    setTitle(value);
    if (!slugEdited) {
      const derived = deriveSlug(value);
      setSlug(derived);
      onSlugChange(derived);
    }
  };

  const applySlug = (value: string) => {
    setSlugEdited(true);
    setSlug(value);
    onSlugChange(value);
  };

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
        if (collision) {
          onResume(slug);
          return;
        }
        onSubmit(title.trim(), slug, description.trim());
      }}
    >
      <div className="type-section-title">New PRD</div>
      <div className="type-caption" style={{ marginTop: 4 }}>
        {input.prompt}
      </div>

      <div style={{ marginTop: 20 }}>
        <label className="type-cell-label" htmlFor="feature_title">
          {titleField?.prompt ?? "Title"}
        </label>
        <input
          id="feature_title"
          value={title}
          maxLength={80}
          disabled={submitting}
          autoFocus
          onChange={(event) => applyTitle(event.target.value)}
          placeholder="Name this feature"
          style={{ ...inputStyle, fontSize: 18 }}
        />
        {titleField?.description && (
          <div className="type-caption" style={{ marginTop: 8 }}>
            {titleField.description}
          </div>
        )}
      </div>

      <div style={{ marginTop: 20 }}>
        <label className="type-cell-label" htmlFor="feature_slug">
          {slugField?.prompt ?? "Slug"}
        </label>
        <input
          id="feature_slug"
          value={slug}
          maxLength={50}
          disabled={submitting}
          onChange={(event) => applySlug(event.target.value)}
          style={{
            ...inputStyle,
            fontFamily: "var(--font-mono)",
            fontSize: 13,
            fontWeight: 500,
            borderColor: slugError ? "var(--color-red)" : "var(--color-border)",
          }}
        />
        {slugError ? (
          <div style={{ marginTop: 8, fontSize: 11, fontWeight: 500, color: "var(--color-red)" }}>
            {slugError}
          </div>
        ) : (
          <div
            className="type-caption"
            style={{ marginTop: 8, fontFamily: "var(--font-mono)" }}
          >
            {slug ? `specs/${slug}/prd.md` : "Derived from the title"}
          </div>
        )}
        {collision && (
          <div style={{ marginTop: 8, fontSize: 11, fontWeight: 500, color: "var(--color-amber)" }}>
            An interview already exists for this slug ({existingStatus}). Resume it, or use a
            different slug.
          </div>
        )}
      </div>

      <div style={{ marginTop: 20 }}>
        <label className="type-cell-label" htmlFor="feature_description">
          {descriptionField?.prompt ?? "What problem should it solve?"}
        </label>
        <textarea
          id="feature_description"
          value={description}
          maxLength={2000}
          disabled={submitting}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Who hits the problem, what happens today, and what should change"
          style={{ ...inputStyle, fontSize: 13, minHeight: 96, lineHeight: 1.5, resize: "vertical" }}
        />
        <div className="type-caption" style={{ marginTop: 8 }}>
          {descriptionField?.description ??
            "Include who experiences the problem, what happens today, and the outcome."}
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
        {collision && (
          <button
            type="button"
            className="type-badge"
            disabled={submitting}
            onClick={() => {
              setSlugEdited(true);
              setSlug("");
              onSlugChange("");
            }}
            style={{
              height: 32,
              padding: "0 16px",
              borderRadius: 6,
              background: "transparent",
              color: "var(--color-text-secondary)",
              border: "1px solid var(--color-border)",
              cursor: "pointer",
            }}
          >
            Use a different slug
          </button>
        )}
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
          {submitting ? "Starting…" : collision ? "Resume interview" : "Start interview"}
        </button>
      </div>
    </form>
  );
}
