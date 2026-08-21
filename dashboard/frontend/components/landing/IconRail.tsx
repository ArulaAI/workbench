"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/", icon: "home", label: "Home" },
  { href: "/define", icon: "layers", label: "Define" },
  { href: "/editor", icon: "edit", label: "Spec Editor" },
  { href: "/spec-alignment", icon: "doc", label: "Spec Alignment" },
  { sep: true },
  { href: "/mission-control", icon: "pulse", label: "Execute" },
  { sep: true },
  { href: "/outcome-review", icon: "check", label: "Outcome Review" },
  { href: "/analytics", icon: "chart", label: "Learning" },
];

function Icon({ name }: { name: string }) {
  const props = {
    width: 17,
    height: 17,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.5,
  };
  switch (name) {
    case "home":
      return (
        <svg {...props}>
          <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
          <polyline points="9 22 9 12 15 12 15 22" />
        </svg>
      );
    case "layers":
      return (
        <svg {...props}>
          <polygon points="12 2 2 7 12 12 22 7 12 2" />
          <polyline points="2 17 12 22 22 17" />
          <polyline points="2 12 12 17 22 12" />
        </svg>
      );
    case "explorer":
      return (
        <svg {...props}>
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <line x1="9" y1="3" x2="9" y2="21" />
        </svg>
      );
    case "edit":
      return (
        <svg {...props}>
          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
        </svg>
      );
    case "doc":
      return (
        <svg {...props}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
        </svg>
      );
    case "pulse":
      return (
        <svg {...props}>
          <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
        </svg>
      );
    case "check":
      return (
        <svg {...props}>
          <path d="M9 11l3 3L22 4" />
          <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
        </svg>
      );
    case "chart":
      return (
        <svg {...props}>
          <path d="M12 20V10M18 20V4M6 20v-4" />
        </svg>
      );
    case "settings":
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      );
    default:
      return null;
  }
}

export function IconRail({
  explorerOpen,
  onToggleExplorer,
}: {
  explorerOpen?: boolean;
  onToggleExplorer?: () => void;
} = {}) {
  const pathname = usePathname();
  const isEditor = pathname?.startsWith("/editor");

  return (
    <nav
      style={{
        width: 52,
        background: "var(--color-bg)",
        borderRight: "1px solid var(--color-border)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        padding: "14px 0",
        gap: 2,
        flexShrink: 0,
      }}
    >
      {/* Brand */}
      <div
        style={{
          width: 28,
          height: 28,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "var(--font-mono)",
          fontSize: 15,
          fontWeight: 600,
          color: "var(--color-accent)",
          marginBottom: 16,
        }}
      >
        ⚡
      </div>

      {/* Explorer toggle (editor only) */}
      {isEditor && onToggleExplorer && (
        <button
          onClick={onToggleExplorer}
          title="Toggle explorer (⌘E)"
          style={{
            width: 34,
            height: 34,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            borderRadius: 8,
            border: "none",
            color: explorerOpen
              ? "var(--color-accent)"
              : "var(--color-text-tertiary)",
            background: explorerOpen
              ? "rgba(0, 212, 170, 0.04)"
              : "transparent",
            cursor: "pointer",
            transition: "all 0.12s",
            marginBottom: 4,
          }}
        >
          <Icon name="explorer" />
        </button>
      )}

      {NAV_ITEMS.map((item, i) => {
        if ("sep" in item) {
          return (
            <div
              key={`sep-${i}`}
              style={{
                width: 18,
                height: 1,
                background: "var(--color-border)",
                margin: "6px 0",
              }}
            />
          );
        }

        const active = item.href === "/editor"
          ? isEditor
          : pathname === item.href;
        return (
          <Link
            key={item.href}
            href={item.href!}
            title={item.label}
            style={{
              width: 34,
              height: 34,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: 8,
              color: active
                ? "var(--color-accent)"
                : "var(--color-text-tertiary)",
              background: active
                ? "rgba(0, 212, 170, 0.04)"
                : "transparent",
              position: "relative",
              transition: "all 0.12s",
              textDecoration: "none",
            }}
          >
            <Icon name={item.icon!} />
            {active && (
              <span
                style={{
                  position: "absolute",
                  left: -1,
                  top: "50%",
                  transform: "translateY(-50%)",
                  width: 2,
                  height: 14,
                  background: "var(--color-accent)",
                  borderRadius: "0 1px 1px 0",
                }}
              />
            )}
          </Link>
        );
      })}

      <div style={{ marginTop: "auto" }}>
        <div
          style={{
            width: 34,
            height: 34,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            borderRadius: 8,
            color: "var(--color-text-tertiary)",
            cursor: "pointer",
          }}
        >
          <Icon name="settings" />
        </div>
      </div>
    </nav>
  );
}
