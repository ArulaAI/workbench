"use client";

import { useState, useCallback, useEffect } from "react";

export interface AuditHistoryState {
  selectedRunIndex: number;
  compareIndices: [number, number] | null;
  isComparing: boolean;
  selectRun: (index: number) => void;
  shiftSelectRun: (index: number) => void;
  exitComparison: () => void;
  resetToLatest: () => void;
}

export default function useAuditHistory(auditCount: number): AuditHistoryState {
  const [selectedRunIndex, setSelectedRunIndex] = useState(0);
  const [compareIndices, setCompareIndices] = useState<[number, number] | null>(null);

  const isComparing = compareIndices !== null;

  const selectRun = useCallback(
    (index: number) => {
      const clamped = auditCount > 0 ? Math.max(0, Math.min(index, auditCount - 1)) : 0;
      setCompareIndices(null);
      setSelectedRunIndex((prev) => (prev === clamped ? 0 : clamped));
    },
    [auditCount],
  );

  const shiftSelectRun = useCallback(
    (index: number) => {
      if (auditCount < 2) return;
      const clamped = Math.max(0, Math.min(index, auditCount - 1));

      if (compareIndices === null) {
        if (selectedRunIndex === clamped) return;
        const sorted: [number, number] =
          selectedRunIndex < clamped
            ? [selectedRunIndex, clamped]
            : [clamped, selectedRunIndex];
        setSelectedRunIndex(0);
        setCompareIndices(sorted);
        return;
      }

      if (compareIndices[0] === clamped || compareIndices[1] === clamped) {
        setCompareIndices(null);
        return;
      }

      // Keep the lower (newer) index, replace the higher (older) with clamped
      const [lower] = compareIndices;
      const newPair: [number, number] =
        clamped < lower ? [clamped, lower] : [lower, clamped];
      setCompareIndices(newPair);
    },
    [auditCount, selectedRunIndex, compareIndices],
  );

  const exitComparison = useCallback(() => {
    setCompareIndices(null);
    setSelectedRunIndex(0);
  }, []);

  const resetToLatest = useCallback(() => {
    setCompareIndices(null);
    setSelectedRunIndex(0);
  }, []);

  // Clamp state when auditCount shrinks
  useEffect(() => {
    if (auditCount === 0) {
      setSelectedRunIndex(0);
      setCompareIndices(null);
      return;
    }
    setSelectedRunIndex((prev) => {
      if (prev >= auditCount) return Math.max(0, auditCount - 1);
      return prev;
    });
    setCompareIndices((prev) => {
      if (prev === null) return null;
      if (prev[0] >= auditCount || prev[1] >= auditCount) return null;
      return prev;
    });
  }, [auditCount]);

  // Escape key handler
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      if (isComparing) {
        exitComparison();
      } else if (selectedRunIndex !== 0) {
        resetToLatest();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isComparing, selectedRunIndex, exitComparison, resetToLatest]);

  return {
    selectedRunIndex,
    compareIndices,
    isComparing,
    selectRun,
    shiftSelectRun,
    exitComparison,
    resetToLatest,
  };
}
