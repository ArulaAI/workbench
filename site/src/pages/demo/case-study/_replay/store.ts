import { atom, computed } from 'nanostores';
import { buildSteps, type ReplayStep, type Phase } from './steps';

/* ── Replay state ──────────────────────────── */

export const $steps = atom<ReplayStep[]>(buildSteps());
export const $currentStep = atom(0);

/* ── Derived ───────────────────────────────── */

export const $visibleSteps = computed([$steps, $currentStep], (steps, idx) =>
  steps.slice(0, idx + 1),
);

export const $activeFile = computed([$steps, $currentStep], (steps, idx) => {
  const currentPhase = steps[idx]?.phase;
  for (let i = idx; i >= 0; i--) {
    if (steps[i].phase !== currentPhase) return null;
    if (steps[i].file) return steps[i].file;
  }
  return null;
});

export const $progress = computed([$steps, $currentStep], (steps, idx) =>
  steps.length > 1 ? idx / (steps.length - 1) : 0,
);

export const $phase = computed([$steps, $currentStep], (steps, idx) =>
  steps[idx]?.phase ?? 'define',
);

export const $phaseRanges = computed([$steps], (steps) => {
  const ranges: { phase: Phase; start: number; end: number }[] = [];
  let current: Phase | null = null;
  let start = 0;
  for (let i = 0; i < steps.length; i++) {
    if (steps[i].phase !== current) {
      if (current !== null) ranges.push({ phase: current, start, end: i - 1 });
      current = steps[i].phase;
      start = i;
    }
  }
  if (current !== null) ranges.push({ phase: current, start, end: steps.length - 1 });
  return ranges;
});

/* ── Actions ───────────────────────────────── */

export function nextStep() {
  const s = $steps.get();
  const c = $currentStep.get();
  if (c < s.length - 1) $currentStep.set(c + 1);
}

export function prevStep() {
  const c = $currentStep.get();
  if (c > 0) $currentStep.set(c - 1);
}

export function goToStep(idx: number) {
  const s = $steps.get();
  $currentStep.set(Math.max(0, Math.min(idx, s.length - 1)));
}

export function playPhase(phase: Phase) {
  const ranges = $phaseRanges.get();
  const range = ranges.find(r => r.phase === phase);
  if (!range) return;
  $currentStep.set(range.end);
}
