"use client";

import { useEffect, useRef, useImperativeHandle, forwardRef } from "react";
import { EditorView, keymap, drawSelection, highlightActiveLine, lineNumbers, highlightActiveLineGutter, Decoration, type DecorationSet } from "@codemirror/view";
import { EditorState, StateField, StateEffect, Transaction } from "@codemirror/state";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { languages } from "@codemirror/language-data";
import { defaultKeymap, history, historyKeymap, indentWithTab, undo as undoCommand, redo as redoCommand } from "@codemirror/commands";
import { searchKeymap, highlightSelectionMatches } from "@codemirror/search";
import { syntaxHighlighting, HighlightStyle, bracketMatching, foldGutter, foldKeymap } from "@codemirror/language";
import { tags } from "@lezer/highlight";

/* ── Theme ──────────────────────────────────────────────────────── */

const editorTheme = EditorView.theme({
  "&": {
    backgroundColor: "transparent",
    color: "var(--color-text-secondary)",
    fontFamily: "var(--font-sans)",
    fontSize: "13px",
    lineHeight: "1.7",
    height: "100%",
  },
  "&.cm-focused": {
    outline: "none",
  },
  ".cm-content": {
    padding: "24px 0",
    maxWidth: "780px",
    margin: "0 auto",
    caretColor: "var(--color-accent)",
  },
  ".cm-cursor": {
    borderLeftColor: "var(--color-accent)",
    borderLeftWidth: "1.5px",
  },
  ".cm-activeLine": {
    backgroundColor: "rgba(255, 255, 255, 0.02)",
  },
  ".cm-activeLineGutter": {
    backgroundColor: "rgba(255, 255, 255, 0.02)",
  },
  ".cm-gutters": {
    backgroundColor: "transparent",
    color: "var(--color-text-tertiary)",
    border: "none",
    paddingRight: "8px",
  },
  ".cm-lineNumbers .cm-gutterElement": {
    fontFamily: "var(--font-mono)",
    fontSize: "10px",
    minWidth: "32px",
    opacity: "0.5",
  },
  ".cm-foldGutter .cm-gutterElement": {
    padding: "0 4px",
    cursor: "pointer",
    color: "var(--color-text-tertiary)",
  },
  ".cm-selectionBackground": {
    backgroundColor: "rgba(0, 212, 170, 0.15) !important",
  },
  "&.cm-focused .cm-selectionBackground": {
    backgroundColor: "rgba(0, 212, 170, 0.2) !important",
  },
  ".cm-searchMatch": {
    backgroundColor: "rgba(240, 178, 50, 0.2)",
    borderRadius: "2px",
  },
  ".cm-searchMatch.cm-searchMatch-selected": {
    backgroundColor: "rgba(240, 178, 50, 0.4)",
  },
  ".cm-scroller": {
    overflow: "auto",
    padding: "0 24px",
  },
  ".cm-panels": {
    backgroundColor: "var(--color-bg-elevated)",
    color: "var(--color-text)",
    borderBottom: "1px solid var(--color-border)",
  },
  ".cm-panels .cm-button": {
    backgroundImage: "none",
    backgroundColor: "var(--color-bg-card)",
    color: "var(--color-text)",
    border: "1px solid var(--color-border)",
    borderRadius: "4px",
  },
  ".cm-panels .cm-textfield": {
    backgroundColor: "var(--color-bg)",
    color: "var(--color-text)",
    border: "1px solid var(--color-border)",
    borderRadius: "4px",
  },
  // Fix highlight (green flash for applied fixes)
  ".cm-fix-highlight": {
    backgroundColor: "rgba(0, 212, 170, 0.2)",
    borderRadius: "2px",
    transition: "background-color 1.5s ease",
  },
}, { dark: true });

const autoHeightTheme = EditorView.theme({
  "&": {
    height: "auto",
    minHeight: "100%",
  },
  ".cm-scroller": {
    overflow: "visible",
  },
});

/* ── Syntax highlighting ────────────────────────────────────────── */

const markdownHighlight = HighlightStyle.define([
  { tag: tags.heading1, color: "var(--color-text)", fontSize: "20px", fontWeight: "600", fontFamily: "var(--font-mono)" },
  { tag: tags.heading2, color: "var(--color-text)", fontSize: "16px", fontWeight: "600", fontFamily: "var(--font-mono)" },
  { tag: tags.heading3, color: "var(--color-text)", fontSize: "14px", fontWeight: "600" },
  { tag: tags.heading4, color: "var(--color-text-secondary)", fontSize: "13px", fontWeight: "600" },
  { tag: tags.heading5, color: "var(--color-text-secondary)", fontSize: "13px", fontWeight: "500" },
  { tag: tags.heading6, color: "var(--color-text-tertiary)", fontSize: "13px", fontWeight: "500" },
  { tag: tags.emphasis, fontStyle: "italic", color: "var(--color-text-secondary)" },
  { tag: tags.strong, fontWeight: "600", color: "var(--color-text)" },
  { tag: tags.strikethrough, textDecoration: "line-through", color: "var(--color-text-tertiary)" },
  { tag: tags.monospace, fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--color-accent)" },
  { tag: tags.link, color: "var(--color-accent)", textDecoration: "none" },
  { tag: tags.url, color: "var(--color-accent)", opacity: "0.7" },
  { tag: tags.quote, color: "var(--color-text-tertiary)", fontStyle: "italic" },
  { tag: tags.list, color: "var(--color-text-secondary)" },
  { tag: tags.meta, color: "var(--color-text-tertiary)" },
  { tag: tags.processingInstruction, color: "var(--color-text-tertiary)" },
  { tag: tags.comment, color: "var(--color-text-tertiary)", fontStyle: "italic" },
  { tag: tags.content, color: "var(--color-text-secondary)" },
]);

/* ── Fix highlight decoration ──────────────────────────────────── */

const addHighlight = StateEffect.define<{ from: number; to: number }>();
const clearHighlight = StateEffect.define<void>();

const highlightMark = Decoration.mark({ class: "cm-fix-highlight" });

const highlightField = StateField.define<DecorationSet>({
  create() {
    return Decoration.none;
  },
  update(decos, tr) {
    decos = decos.map(tr.changes);
    for (const e of tr.effects) {
      if (e.is(addHighlight)) {
        decos = Decoration.set([highlightMark.range(e.value.from, e.value.to)]);
      } else if (e.is(clearHighlight)) {
        decos = Decoration.none;
      }
    }
    return decos;
  },
  provide: (f) => EditorView.decorations.from(f),
});

/* ── Component ──────────────────────────────────────────────────── */

export interface CursorPosition {
  line: number;
  col: number;
}

export interface SpecEditorHandle {
  /** Replace old text with new text, scroll to it, and flash-highlight. Returns false if old text not found. */
  replaceAndHighlight: (oldText: string, newText: string) => boolean;
  /** Scroll to a section heading and briefly highlight the line. Returns false if heading not found. */
  scrollToSection: (sectionName: string, line?: number | null) => boolean;
  undo: () => boolean;
  redo: () => boolean;
  applyFormat: (format: "normal" | "heading2" | "heading3" | "bold" | "italic" | "bullet" | "numbered" | "link" | "table") => void;
}

/**
 * Shape of a non-empty text selection in the editor. Exposed via
 * `onSelectionChange` so parents can render floating affordances
 * (e.g. a "Leave suggestion" popover) anchored to the selection.
 */
export interface EditorSelection {
  text: string;
  from: number;
  to: number;
  /** Heading text of the nearest preceding markdown heading, or null. */
  sectionTitle: string | null;
  /** slugified section id derived from the heading. */
  sectionId: string | null;
  /** Bounding rect of the selection in viewport coordinates. */
  rect: { top: number; left: number; right: number; bottom: number };
}

interface SpecEditorProps {
  ariaLabel?: string;
  content: string;
  specType: string;
  onChange: (content: string) => void;
  onCursorChange?: (pos: CursorPosition) => void;
  onSelectionChange?: (selection: EditorSelection | null) => void;
  readOnly?: boolean;
  showLineNumbers?: boolean;
  autoHeight?: boolean;
}

export const SpecEditor = forwardRef<SpecEditorHandle, SpecEditorProps>(
  function SpecEditor({ content, specType, onChange, onCursorChange, onSelectionChange, readOnly = false, showLineNumbers = true, autoHeight = false, ariaLabel = "Markdown editor" }, ref) {
    const containerRef = useRef<HTMLDivElement>(null);
    const viewRef = useRef<EditorView | null>(null);
    const onChangeRef = useRef(onChange);
    const onCursorRef = useRef(onCursorChange);
    const onSelectionRef = useRef(onSelectionChange);
    onChangeRef.current = onChange;
    onCursorRef.current = onCursorChange;
    onSelectionRef.current = onSelectionChange;

    useImperativeHandle(ref, () => ({
      replaceAndHighlight(oldText: string, newText: string): boolean {
        const view = viewRef.current;
        if (!view) return false;

        const doc = view.state.doc.toString();
        const idx = doc.indexOf(oldText);
        if (idx < 0) return false;

        // Replace text in the editor
        view.dispatch({
          changes: { from: idx, to: idx + oldText.length, insert: newText },
        });

        // Highlight the replacement
        const from = idx;
        const to = idx + newText.length;
        view.dispatch({
          effects: addHighlight.of({ from, to }),
        });

        // Scroll to center
        view.dispatch({
          effects: EditorView.scrollIntoView(from, { y: "center" }),
        });

        // Fade highlight after 2s
        setTimeout(() => {
          viewRef.current?.dispatch({ effects: clearHighlight.of() });
        }, 2000);

        return true;
      },
      scrollToSection(sectionName: string, line?: number | null): boolean {
        const view = viewRef.current;
        if (!view) return false;

        const doc = view.state.doc.toString();
        let targetPos = -1;

        if (line && line > 0) {
          // Jump to specific line number
          const lineCount = view.state.doc.lines;
          if (line <= lineCount) {
            targetPos = view.state.doc.line(line).from;
          }
        }

        if (targetPos < 0 && sectionName) {
          // Search for a markdown heading matching the section name
          const pattern = new RegExp(`^#{1,6}\\s+${sectionName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`, "im");
          const match = pattern.exec(doc);
          if (match) {
            targetPos = match.index;
          } else {
            // Fallback: case-insensitive substring search for the heading text
            const lower = doc.toLowerCase();
            const idx = lower.indexOf(sectionName.toLowerCase());
            if (idx >= 0) targetPos = idx;
          }
        }

        if (targetPos < 0) return false;

        // Find line boundaries for highlight
        const targetLine = view.state.doc.lineAt(targetPos);

        // Scroll to center
        view.dispatch({
          effects: EditorView.scrollIntoView(targetPos, { y: "center" }),
        });

        // Flash highlight
        view.dispatch({
          effects: addHighlight.of({ from: targetLine.from, to: targetLine.to }),
        });
        setTimeout(() => {
          viewRef.current?.dispatch({ effects: clearHighlight.of() });
        }, 2000);

        return true;
      },
      undo: () => Boolean(viewRef.current && undoCommand(viewRef.current)),
      redo: () => Boolean(viewRef.current && redoCommand(viewRef.current)),
      applyFormat(format) {
        const view = viewRef.current;
        if (!view) return;
        const selection = view.state.selection.main;
        const selected = view.state.doc.sliceString(selection.from, selection.to);
        const wrap = (before: string, after = before, fallback = "text") => {
          const value = selected || fallback;
          view.dispatch({
            changes: { from: selection.from, to: selection.to, insert: `${before}${value}${after}` },
            selection: { anchor: selection.from + before.length, head: selection.from + before.length + value.length },
          });
          view.focus();
        };
        if (format === "bold") return wrap("**");
        if (format === "italic") return wrap("_");
        if (format === "link") return wrap("[", "](https://)", "link text");
        if (format === "table") {
          view.dispatch({ changes: { from: selection.from, to: selection.to, insert: "| Column | Column |\n|---|---|\n| Value | Value |" } });
          view.focus();
          return;
        }
        const fromLine = view.state.doc.lineAt(selection.from);
        const toLine = view.state.doc.lineAt(selection.to);
        const source = view.state.doc.sliceString(fromLine.from, toLine.to);
        const transformed = source.split("\n").map((line, index) => {
          const clean = line.replace(/^(?:#{1,6}\s+|[-*]\s+|\d+\.\s+)/, "");
          if (format === "heading2") return `## ${clean}`;
          if (format === "heading3") return `### ${clean}`;
          if (format === "bullet") return `- ${clean}`;
          if (format === "numbered") return `${index + 1}. ${clean}`;
          return clean;
        }).join("\n");
        view.dispatch({ changes: { from: fromLine.from, to: toLine.to, insert: transformed } });
        view.focus();
      },
    }));

    useEffect(() => {
      if (!containerRef.current) return;

      const updateListener = EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          onChangeRef.current(update.state.doc.toString());
        }
        if (update.selectionSet || update.docChanged) {
          const sel = update.state.selection.main;
          const line = update.state.doc.lineAt(sel.head);
          onCursorRef.current?.({
            line: line.number,
            col: sel.head - line.from + 1,
          });

          // Selection change — notify parent if a non-empty range is
          // selected so it can render floating affordances (e.g. the
          // "Leave suggestion" popover in read-only mode).
          if (onSelectionRef.current) {
            if (sel.empty) {
              onSelectionRef.current(null);
            } else {
              const doc = update.state.doc;
              const text = doc.sliceString(sel.from, sel.to);

              // Walk backward from the selection to find the nearest
              // preceding markdown heading, so the suggestion can be
              // tagged with the section it lives under.
              const docString = doc.toString();
              const before = docString.slice(0, sel.from);
              let sectionTitle: string | null = null;
              const headingMatches = [...before.matchAll(/^#{1,6}\s+(.+)$/gm)];
              if (headingMatches.length > 0) {
                sectionTitle = headingMatches[headingMatches.length - 1][1].trim();
              }
              const sectionId = sectionTitle
                ? sectionTitle.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "")
                : null;

              // Anchor the popover to the end of the selection in
              // viewport coordinates. CodeMirror's coordsAtPos returns
              // the DOM rect for a position in the document.
              try {
                const coordsEnd = update.view.coordsAtPos(sel.to);
                const coordsStart = update.view.coordsAtPos(sel.from);
                if (coordsEnd && coordsStart) {
                  onSelectionRef.current({
                    text,
                    from: sel.from,
                    to: sel.to,
                    sectionTitle,
                    sectionId,
                    rect: {
                      top: Math.min(coordsStart.top, coordsEnd.top),
                      left: coordsStart.left,
                      right: coordsEnd.right,
                      bottom: Math.max(coordsStart.bottom, coordsEnd.bottom),
                    },
                  });
                }
              } catch {
                onSelectionRef.current(null);
              }
            }
          }
        }
      });

      const state = EditorState.create({
        doc: content,
        extensions: [
          EditorView.contentAttributes.of({"aria-label": ariaLabel}),
          history(),
          drawSelection(),
          EditorState.allowMultipleSelections.of(true),
          bracketMatching(),
          highlightActiveLine(),
          highlightActiveLineGutter(),
          highlightSelectionMatches(),
          ...(showLineNumbers ? [lineNumbers(), foldGutter()] : []),
          markdown({ base: markdownLanguage, codeLanguages: languages }),
          syntaxHighlighting(markdownHighlight),
          highlightField,
          editorTheme,
          ...(autoHeight ? [autoHeightTheme] : []),
          keymap.of([
            ...defaultKeymap,
            ...historyKeymap,
            ...searchKeymap,
            ...foldKeymap,
            indentWithTab,
          ]),
          EditorView.lineWrapping,
          ...(readOnly ? [EditorState.readOnly.of(true)] : []),
          updateListener,
        ],
      });

      const view = new EditorView({ state, parent: containerRef.current });
      viewRef.current = view;

      return () => {
        view.destroy();
        viewRef.current = null;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
      const view = viewRef.current;
      if (!view || view.state.doc.toString() === content) return;
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: content },
        annotations: Transaction.addToHistory.of(false),
      });
    }, [content]);

    return (
      <div
        ref={containerRef}
        data-readonly={readOnly ? "true" : "false"}
        style={{
          flex: autoHeight ? "none" : 1,
          height: autoHeight ? "auto" : "100%",
          minHeight: autoHeight ? "100%" : undefined,
          overflow: autoHeight ? "visible" : "hidden",
          // Ambient visual cue for read-only mode: a subtle diagonal
          // stripe pattern so the user knows they can't type without
          // needing to read the banner. The gradient is nearly
          // invisible (0.8% opacity white) so it doesn't fight with
          // the editor content.
          backgroundColor: "var(--color-bg)",
          backgroundImage: readOnly
            ? "repeating-linear-gradient(135deg, transparent 0 60px, rgba(255,255,255,0.008) 60px 61px)"
            : undefined,
        }}
      />
    );
  }
);
