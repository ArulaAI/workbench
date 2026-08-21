"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useSubscription } from "urql";
import {
  DECLARE_INTENT_MUTATION,
  CONTEXT_ASSEMBLY_PROGRESS_SUBSCRIPTION,
  type DeclareIntentData,
  type DeclareIntentVars,
  type ContextAssemblyProgressData,
} from "@/lib/graphql/queries/ceremony-context";
import {
  CEREMONY_MODELS_QUERY,
  type LLMModel,
} from "@/lib/graphql/queries/editor";

/* ── Constants ──────────────────────────────────────────────── */

const FEATURE_RE = /^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$/;
const CONSECUTIVE_HYPHENS_RE = /--/;
const MAX_NAME_LEN = 50;
const MIN_INTENT_LEN = 5;

/** Minimum ms between visual state changes per source row. */
const STAGGER_MS = 120;
/** How long to hold the all-complete state before navigating. */
const COMPLETE_HOLD_MS = 900;

/** Maps backend source keys to display names. Order = display order. */
const SOURCES: [key: string, label: string][] = [
  ["codebase", "Semantic graph"],
  ["learnings", "Learnings"],
  ["defects", "Defects"],
  ["project_knowledge", "Project knowledge"],
  ["vision", "Vision"],
  ["related_features", "Related features"],
  ["audit_history", "Audit history"],
];

type SourceState = "pending" | "ok" | "empty" | "error";

/* ── Validation ─────────────────────────────────────────────── */

function validateName(name: string): string | null {
  if (!name) return null;
  if (name.length > MAX_NAME_LEN) return `Max ${MAX_NAME_LEN} characters`;
  if (CONSECUTIVE_HYPHENS_RE.test(name)) return "No consecutive hyphens";
  if (name.startsWith("-") || name.endsWith("-"))
    return "Cannot start or end with hyphen";
  if (!FEATURE_RE.test(name)) return "Lowercase, numbers, and hyphens only";
  return null;
}

/* ── Component ──────────────────────────────────────────────── */

interface IntentInputProps {
  onDeclared?: (featureName: string) => void;
}

export function IntentInput({ onDeclared }: IntentInputProps) {
  const router = useRouter();
  const [featureName, setFeatureName] = useState("");
  const [intentText, setIntentText] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sourceStates, setSourceStates] = useState<Record<string, SourceState>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [exiting, setExiting] = useState(false);
  const intentRef = useRef<HTMLTextAreaElement>(null);
  const navigatedRef = useRef(false);

  /* ── Staggered playback queue ── */
  const eventQueue = useRef<{ source: string; status: SourceState }[]>([]);
  const drainTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastFlush = useRef(0);

  const flushNext = useCallback(() => {
    const next = eventQueue.current.shift();
    if (!next) {
      drainTimer.current = null;
      return;
    }
    lastFlush.current = Date.now();
    setSourceStates((prev) => ({ ...prev, [next.source]: next.status }));

    if (eventQueue.current.length > 0) {
      drainTimer.current = setTimeout(flushNext, STAGGER_MS);
    } else {
      drainTimer.current = null;
    }
  }, []);

  const enqueueEvent = useCallback(
    (source: string, status: SourceState) => {
      eventQueue.current.push({ source, status });

      // If nothing is draining, start immediately or after remaining stagger
      if (!drainTimer.current) {
        const elapsed = Date.now() - lastFlush.current;
        const wait = Math.max(0, STAGGER_MS - elapsed);
        drainTimer.current = setTimeout(flushNext, wait);
      }
    },
    [flushNext]
  );

  // Cleanup timers on unmount
  useEffect(() => {
    return () => {
      if (drainTimer.current) clearTimeout(drainTimer.current);
    };
  }, []);

  const [, executeDeclare] = useMutation<DeclareIntentData, DeclareIntentVars>(
    DECLARE_INTENT_MUTATION
  );

  /* ── Model selector ── */
  const [modelsResult] = useQuery<{ ceremonyModels: LLMModel[] }>({
    query: CEREMONY_MODELS_QUERY,
  });
  const [selectedModel, setSelectedModel] = useState("");
  const models = modelsResult.data?.ceremonyModels || [];
  if (!selectedModel && models.length > 0) setSelectedModel(models[0].id);

  /* ── Assembly progress subscription (connected on mount) ── */
  useSubscription<ContextAssemblyProgressData>(
    {
      query: CONTEXT_ASSEMBLY_PROGRESS_SUBSCRIPTION,
      variables: { feature: featureName },
      pause: featureName.length === 0,
    },
    (_prev, data) => {
      const event = data?.contextAssemblyProgress;
      if (!event) return data;

      if (event.source === "complete") {
        if (!navigatedRef.current) {
          navigatedRef.current = true;
          const waitForDrain = () => {
            if (eventQueue.current.length > 0 || drainTimer.current) {
              setTimeout(waitForDrain, 60);
              return;
            }
            setTimeout(() => {
              setExiting(true);
              setTimeout(() => {
                onDeclared?.(featureName);
                router.push(`/define/${featureName}`);
              }, 350);
            }, COMPLETE_HOLD_MS);
          };
          waitForDrain();
        }
      } else {
        enqueueEvent(event.source, event.status as SourceState);
      }
      return data;
    }
  );

  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const raf = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  const canSubmit =
    featureName.length > 0 &&
    intentText.trim().length >= MIN_INTENT_LEN &&
    !validateName(featureName) &&
    !submitting;

  useEffect(() => {
    const el = intentRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = el.scrollHeight + "px";
    }
  }, [intentText]);

  const handleNameChange = useCallback((val: string) => {
    const cleaned = val.toLowerCase().replace(/[^a-z0-9-]/g, "");
    setFeatureName(cleaned);
    setNameError(validateName(cleaned));
    setSubmitError(null);
  }, []);

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setSubmitError(null);
    setExiting(false);
    navigatedRef.current = false;
    eventQueue.current = [];
    lastFlush.current = 0;

    // Initialize all sources as pending
    setSourceStates(
      Object.fromEntries(SOURCES.map(([key]) => [key, "pending" as SourceState]))
    );

    try {
      const result = await executeDeclare({
        text: intentText.trim(),
        featureName,
        ...(selectedModel ? { model: selectedModel } : {}),
      });

      if (result.error) {
        const msg = result.error.message;
        if (msg.includes("collision") || msg.includes("already owned")) {
          setNameError(msg);
        } else {
          setSubmitError(msg);
        }
        setSubmitting(false);
        setSourceStates({});
        return;
      }

      // Mutation returned — ceremony created, assembly running in background.
      // Subscription delivers per-source progress and triggers navigation on "complete".
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Unknown error");
      setSubmitting(false);
      setSourceStates({});
    }
  }, [canSubmit, featureName, intentText, selectedModel, executeDeclare, router, onDeclared]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey && canSubmit) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [canSubmit, handleSubmit]
  );

  const showProgress = submitting && Object.keys(sourceStates).length > 0;

  return (
    <>
      <style>{keyframes}</style>
      <div className="surface" style={{
        ...styles.card,
        opacity: mounted && !exiting ? 1 : 0,
        transform: mounted && !exiting ? "translateY(0)" : "translateY(8px)",
        transition: "opacity 0.35s ease-out, transform 0.35s ease-out",
      }}>
        {/* Feature name field */}
        <div style={styles.nameRow}>
          <input
            type="text"
            value={featureName}
            onChange={(e) => handleNameChange(e.target.value)}
            placeholder="feature-name"
            maxLength={MAX_NAME_LEN}
            disabled={submitting}
            style={{
              ...styles.nameInput,
              ...(nameError ? styles.nameInputError : {}),
              ...(submitting ? styles.disabled : {}),
            }}
            aria-label="Feature name"
          />
          {nameError && <span style={styles.nameErrorText}>{nameError}</span>}
        </div>

        {/* Intent text field */}
        <textarea
          ref={intentRef}
          value={intentText}
          onChange={(e) => {
            setIntentText(e.target.value);
            setSubmitError(null);
          }}
          onKeyDown={handleKeyDown}
          placeholder="What do you want to build?"
          disabled={submitting}
          rows={2}
          style={{
            ...styles.intentInput,
            ...(submitting ? styles.disabled : {}),
          }}
          aria-label="Declare what you want to build"
        />

        {/* Assembly progress or caption */}
        {showProgress ? (
          <div style={styles.sources}>
            {SOURCES.map(([key, label], idx) => {
              const status = sourceStates[key] || "pending";
              const pending = status === "pending";
              const done = status === "ok" || status === "empty";
              const errored = status === "error";
              return (
                <div
                  key={key}
                  className={done ? "source-done" : errored ? "source-error" : "source-pending"}
                  style={{
                    ...styles.sourceItem,
                    animationDelay: `${idx * 40}ms`,
                  }}
                >
                  <span
                    className={pending ? "dot-pulse" : undefined}
                    style={{
                      ...styles.sourceDot,
                      background: done
                        ? "var(--color-accent)"
                        : errored
                        ? "var(--color-red)"
                        : "var(--color-text-tertiary)",
                    }}
                  />
                  <span style={{
                    color: done
                      ? "var(--color-accent)"
                      : errored
                      ? "var(--color-red)"
                      : "var(--color-text-tertiary)",
                    transition: "color 0.3s ease",
                  }}>
                    {label}
                  </span>
                  {done && (
                    <span className="check-enter" style={styles.checkmark}>&#x2713;</span>
                  )}
                  {errored && (
                    <span style={styles.errorMark}>&#x2715;</span>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <div style={styles.caption}>
            {submitError ? (
              <span style={styles.errorText}>{submitError}</span>
            ) : (
              "Name your feature and describe your intent. SPEED will deliver context from your codebase."
            )}
          </div>
        )}

        {/* Actions row: model selector + submit */}
        {!submitting && (
          <div style={styles.actions}>
            {models.length > 0 && (
              <select
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                style={styles.modelSelect}
                aria-label="LLM model for scoping"
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))}
              </select>
            )}
            <button
              onClick={handleSubmit}
              disabled={!canSubmit}
              style={{
                ...styles.button,
                ...(!canSubmit ? styles.buttonDisabled : {}),
              }}
            >
              Deliver Context
            </button>
          </div>
        )}
      </div>
    </>
  );
}

/* ── Keyframe animations ──────────────────────────────────────── */

const keyframes = `
  @keyframes dot-pulse {
    0%, 100% { opacity: 0.3; transform: scale(1); }
    50% { opacity: 1; transform: scale(1.4); }
  }
  @keyframes source-row-enter {
    from { opacity: 0; transform: translateX(-6px); }
    to   { opacity: 1; transform: translateX(0); }
  }
  @keyframes check-pop {
    0%   { opacity: 0; transform: scale(0.4); }
    60%  { opacity: 1; transform: scale(1.15); }
    100% { opacity: 1; transform: scale(1); }
  }
  .dot-pulse {
    animation: dot-pulse 1.2s ease-in-out infinite;
  }
  .source-pending, .source-done, .source-error {
    animation: source-row-enter 0.25s ease-out both;
  }
  .check-enter {
    animation: check-pop 0.3s ease-out both;
  }
`;

/* ── Styles ─────────────────────────────────────────────────── */

const styles: Record<string, React.CSSProperties> = {
  card: {
    maxWidth: 720,
    width: "100%",
    padding: "32px 24px",
  },
  nameRow: {
    marginBottom: 12,
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  nameInput: {
    fontFamily: "var(--font-mono)",
    fontSize: 13,
    fontWeight: 500,
    color: "var(--color-text)",
    background: "var(--color-bg-elevated)",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: "var(--color-border)",
    borderRadius: 6,
    padding: "6px 10px",
    outline: "none",
    width: 240,
    transition: "border-color 0.15s",
  },
  nameInputError: {
    borderColor: "var(--color-red)",
  },
  nameErrorText: {
    fontSize: 11,
    color: "var(--color-red)",
  },
  intentInput: {
    width: "100%",
    fontFamily: "var(--font-sans)",
    fontSize: 18,
    fontWeight: 400,
    color: "var(--color-text)",
    background: "var(--color-bg-elevated)",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: "var(--color-border)",
    borderRadius: 8,
    padding: 16,
    outline: "none",
    resize: "none" as const,
    lineHeight: 1.5,
    minHeight: 60,
    transition: "border-color 0.15s",
  },
  disabled: {
    opacity: 0.5,
    cursor: "not-allowed",
  },
  caption: {
    fontSize: 13,
    color: "var(--color-text-tertiary)",
    marginTop: 16,
  },
  errorText: {
    color: "var(--color-red)",
  },
  sources: {
    marginTop: 16,
    display: "flex",
    flexDirection: "column" as const,
    gap: 6,
  },
  sourceItem: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    fontSize: 12,
  },
  sourceDot: {
    width: 6,
    height: 6,
    borderRadius: "50%",
    transition: "background 0.3s ease",
    flexShrink: 0,
  },
  checkmark: {
    marginLeft: 4,
    fontSize: 10,
    color: "var(--color-accent)",
  },
  errorMark: {
    marginLeft: 4,
    fontSize: 10,
    color: "var(--color-red)",
  },
  actions: {
    display: "flex",
    justifyContent: "flex-end",
    alignItems: "center",
    gap: 8,
    marginTop: 12,
  },
  modelSelect: {
    padding: "6px 8px",
    background: "var(--color-bg)",
    color: "var(--color-text-tertiary)",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: "var(--color-border)",
    borderRadius: 6,
    fontFamily: "var(--font-mono)",
    fontSize: 11,
    outline: "none",
  },
  button: {
    fontFamily: "var(--font-sans)",
    fontSize: 13,
    fontWeight: 600,
    background: "var(--color-accent)",
    color: "var(--color-bg)",
    border: "none",
    borderRadius: 8,
    padding: "8px 20px",
    cursor: "pointer",
    transition: "opacity 0.15s",
  },
  buttonDisabled: {
    background: "var(--color-text-tertiary)",
    cursor: "not-allowed",
  },
};
