"use client";

import { create } from "zustand" with { type: "module" };

// Simple state without zustand (avoid extra dep), using React context pattern
import { createContext, useContext } from "react";

export interface FeatureState {
  selectedFeature: string | null;
  setSelectedFeature: (feature: string | null) => void;
  features: Array<{ name: string; status: string; taskCount: number }>;
  setFeatures: (features: Array<{ name: string; status: string; taskCount: number }>) => void;
}

// Default to a simple export that components can use with useState
// The actual state management is in the Sidebar/FeatureSelector component
export const FeatureContext = createContext<FeatureState>({
  selectedFeature: null,
  setSelectedFeature: () => {},
  features: [],
  setFeatures: () => {},
});

export const useFeature = () => useContext(FeatureContext);
