"use client";

import { useState, useEffect } from "react";
import { useQuery } from "urql";
import { gql } from "urql";

const HEALTH_QUERY = gql`
  query Health {
    project {
      id
      name
    }
  }
`;

export function ConnectionStatus() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);

  const [{ fetching, error }] = useQuery({
    query: HEALTH_QUERY,
    requestPolicy: "network-only",
    pause: !mounted,
  });

  const color = !mounted || fetching
    ? "var(--color-amber)"
    : error
      ? "var(--color-red)"
      : "var(--color-emerald)";

  const label = !mounted || fetching ? "Connecting" : error ? "Disconnected" : "Connected";

  return (
    <div className="flex items-center gap-2">
      <div
        className="h-2 w-2 rounded-full"
        style={{ backgroundColor: color, boxShadow: `0 0 6px ${color}` }}
      />
      <span className="type-caption">{label}</span>
    </div>
  );
}
