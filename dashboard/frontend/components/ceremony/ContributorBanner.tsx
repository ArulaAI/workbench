"use client";

import React from "react";
import { Eye } from "lucide-react";

interface ContributorBannerProps {
  authorName: string;
  status: string;
}

export function ContributorBanner({ authorName, status }: ContributorBannerProps) {
  return (
    <div
      style={{
        height: 40,
        padding: "8px 20px",
        display: "flex",
        alignItems: "center",
        gap: 8,
        fontSize: 11,
        flexShrink: 0,
        borderBottom: "1px solid var(--color-border)",
      }}
    >
      <Eye size={13} style={{ color: "var(--color-amber)" }} />
      <span style={{ fontWeight: 500, color: "var(--color-amber)" }}>Read-only</span>
      <span style={{ color: "var(--color-text-secondary)" }}>
        authored by{" "}
        <span style={{ fontWeight: 500, color: "var(--color-text)" }}>{authorName}</span>
      </span>
      <span
        style={{
          marginLeft: "auto",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          color: "var(--color-text-tertiary)",
          textTransform: "uppercase",
          letterSpacing: "0.04em",
        }}
      >
        {status}
      </span>
    </div>
  );
}
