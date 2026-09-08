"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function SpecPreview({
  content,
  scrollable = true,
}: {
  content: string;
  scrollable?: boolean;
}) {
  return (
    <div
      className="spec-preview"
      style={{
        flex: scrollable ? 1 : "none",
        height: scrollable ? "100%" : "auto",
        overflow: scrollable ? "auto" : "visible",
        padding: "24px",
      }}
    >
      <div style={{ maxWidth: 780, margin: "0 auto" }}>
        <style>{`
          .spec-preview {
            color: var(--color-text-secondary);
            font-family: var(--font-sans);
            font-size: 13px;
            line-height: 1.7;
          }
          .spec-preview h1 {
            color: var(--color-text);
            font-family: var(--font-mono);
            font-size: 20px;
            font-weight: 600;
            margin: 0 0 16px 0;
          }
          .spec-preview h2 {
            color: var(--color-text);
            font-family: var(--font-mono);
            font-size: 15px;
            font-weight: 600;
            margin: 32px 0 12px 0;
            padding-bottom: 6px;
            border-bottom: 1px solid var(--color-border);
          }
          .spec-preview h3 {
            color: var(--color-text);
            font-size: 13px;
            font-weight: 600;
            margin: 24px 0 8px 0;
          }
          .spec-preview h4, .spec-preview h5, .spec-preview h6 {
            color: var(--color-text-secondary);
            font-size: 13px;
            font-weight: 600;
            margin: 20px 0 8px 0;
          }
          .spec-preview p {
            margin: 0 0 12px 0;
          }
          .spec-preview blockquote {
            border-left: 2px solid var(--color-accent);
            padding-left: 12px;
            margin: 0 0 12px 0;
            color: var(--color-text-tertiary);
            font-style: italic;
          }
          .spec-preview code {
            font-family: var(--font-mono);
            font-size: 12px;
            background: var(--color-bg-card);
            padding: 1px 5px;
            border-radius: 3px;
            color: var(--color-accent);
          }
          .spec-preview pre {
            background: var(--color-bg-card);
            border: 1px solid var(--color-border);
            border-radius: 6px;
            padding: 14px;
            overflow-x: auto;
            margin: 0 0 12px 0;
          }
          .spec-preview pre code {
            background: none;
            padding: 0;
            color: var(--color-text-secondary);
          }
          .spec-preview table {
            border-collapse: collapse;
            width: 100%;
            font-size: 12px;
            margin: 0 0 12px 0;
          }
          .spec-preview th, .spec-preview td {
            border: 1px solid var(--color-border);
            padding: 6px 10px;
            text-align: left;
          }
          .spec-preview th {
            font-family: var(--font-mono);
            font-weight: 500;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            color: var(--color-text-secondary);
            background: var(--color-bg-elevated);
          }
          .spec-preview ul, .spec-preview ol {
            margin: 0 0 12px 0;
            padding-left: 20px;
          }
          .spec-preview li {
            margin: 2px 0;
          }
          .spec-preview li input[type="checkbox"] {
            margin-right: 6px;
          }
          .spec-preview a {
            color: var(--color-accent);
            text-decoration: none;
          }
          .spec-preview a:hover {
            text-decoration: underline;
          }
          .spec-preview hr {
            border: none;
            border-top: 1px solid var(--color-border);
            margin: 24px 0;
          }
          .spec-preview img {
            max-width: 100%;
            border-radius: 6px;
          }
        `}</style>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {content}
        </ReactMarkdown>
      </div>
    </div>
  );
}
