"use client";

import { useEffect, useRef } from "react";
import { MessageCirclePlus } from "lucide-react";

/**
 * SuggestionPopover — floating affordance anchored to a text selection.
 *
 * Rendered when a non-claimant selects text in the read-only editor.
 * Offers a single "Leave suggestion" button (plus a keyboard hint)
 * that opens the existing SuggestionComposer flow with the selected
 * section pre-filled.
 *
 * Dismisses on Escape, click-outside, or scroll (the latter handled by
 * the parent via a scroll listener since selection rects go stale on
 * scroll anyway).
 *
 * Per the Design spec:
 * - Positioned 8px below the selection end
 * - Rounded, bg-card surface, accent hover on the button
 * - aria role "dialog" for screen readers
 */

interface SuggestionPopoverProps {
  anchorRect: { top: number; left: number; right: number; bottom: number };
  onLeaveSuggestion: () => void;
  onDismiss: () => void;
}

export function SuggestionPopover({
  anchorRect,
  onLeaveSuggestion,
  onDismiss,
}: SuggestionPopoverProps) {
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onDismiss();
      } else if ((e.metaKey || e.ctrlKey) && e.shiftKey && (e.key === "m" || e.key === "M")) {
        e.preventDefault();
        onLeaveSuggestion();
      }
    };
    const clickHandler = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        onDismiss();
      }
    };
    window.addEventListener("keydown", handler);
    // Defer the click listener so the selection event that triggered
    // this popover doesn't immediately dismiss it.
    const t = setTimeout(() => window.addEventListener("mousedown", clickHandler), 0);
    return () => {
      window.removeEventListener("keydown", handler);
      window.removeEventListener("mousedown", clickHandler);
      clearTimeout(t);
    };
  }, [onLeaveSuggestion, onDismiss]);

  // Anchor 8px below the selection. Keep left-aligned with the start
  // so the popover reads naturally with the selected text.
  const style: React.CSSProperties = {
    position: "fixed",
    top: anchorRect.bottom + 8,
    left: anchorRect.left,
    zIndex: 1000,
  };

  return (
    <div
      ref={popoverRef}
      role="dialog"
      aria-label="Suggestion actions"
      className="suggestion-popover"
      style={style}
    >
      <style>{STYLES}</style>
      <button
        className="suggestion-popover-btn"
        onClick={onLeaveSuggestion}
        autoFocus
      >
        <MessageCirclePlus size={12} strokeWidth={2} />
        Leave suggestion
      </button>
      <span className="suggestion-popover-hint">⌘⇧M</span>
    </div>
  );
}

const STYLES = `
  .suggestion-popover {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 10px;
    background: var(--color-bg-card);
    border: 1px solid var(--color-border-strong, var(--color-text-tertiary));
    border-radius: 6px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
    animation: popover-enter 150ms ease-out;
  }
  @keyframes popover-enter {
    from { opacity: 0; transform: translateY(-2px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .suggestion-popover-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: var(--color-accent);
    color: var(--color-bg);
    border: none;
    border-radius: 4px;
    padding: 5px 10px;
    font-family: var(--font-mono);
    font-size: 10px;
    font-weight: 600;
    cursor: pointer;
    transition: background 150ms ease;
  }
  .suggestion-popover-btn:hover {
    background: rgba(0, 212, 170, 0.9);
  }
  .suggestion-popover-btn:focus-visible {
    outline: 2px solid var(--color-accent);
    outline-offset: 2px;
  }
  .suggestion-popover-hint {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--color-text-tertiary);
  }
`;
