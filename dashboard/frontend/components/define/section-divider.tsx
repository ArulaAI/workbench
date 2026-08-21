"use client";

interface SectionDividerProps {
  count: number;
}

export function SectionDivider({ count }: SectionDividerProps) {
  return (
    <div
      style={{
        fontFamily: "var(--font-sans)",
        fontSize: 15,
        fontWeight: 600,
        color: "var(--color-text)",
        padding: "20px 0 12px",
      }}
    >
      Defects &middot; {count}
    </div>
  );
}
