"use client";

import { useState } from "react";

interface RefMarkerProps {
  number: number;
  description: string;
}

export function RefMarker({ number, description }: RefMarkerProps) {
  const [hovered, setHovered] = useState(false);

  return (
    <div
      role="img"
      aria-label={`Cross-reference ${number}: links audit warning to gap escalation`}
      title={description}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        width: 16,
        height: 16,
        borderRadius: "50%",
        background: hovered ? "rgba(240,178,50,0.20)" : "rgba(240,178,50,0.12)",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        cursor: "default",
        flexShrink: 0,
        transition: "background 0.15s",
      }}
    >
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 9,
          fontWeight: 500,
          color: "var(--color-amber)",
          lineHeight: 1,
          userSelect: "none",
        }}
      >
        {number}
      </span>
    </div>
  );
}
