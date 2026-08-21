import { atom, computed } from 'nanostores';

export type ActId = 'spec-authoring' | 'understanding' | 'pipeline' | 'learning' | 'result';

export const ACTS: { id: ActId; number: number; label: string; subtitle: string }[] = [
  { id: 'spec-authoring', number: 1, label: 'Spec Authoring', subtitle: 'Product + Design + Tech, all with AI' },
  { id: 'understanding', number: 2, label: 'Understanding', subtitle: 'CSG, context pipeline, spec alignment' },
  { id: 'pipeline', number: 3, label: 'Pipeline', subtitle: 'Plan, run, review, integrate' },
  { id: 'learning', number: 4, label: 'Learning', subtitle: 'Observations, patterns, injections' },
  { id: 'result', number: 5, label: 'Result', subtitle: 'Shipped feature with full provenance' },
];

export const $currentAct = atom<ActId>('spec-authoring');
export const $expandedPanel = atom<string | null>(null);
export const $costOverlay = atom(false);
export const $specSidebar = atom(false);

export const $currentActIndex = computed($currentAct, (act) =>
  ACTS.findIndex((a) => a.id === act)
);

export function nextAct() {
  const idx = ACTS.findIndex((a) => a.id === $currentAct.get());
  if (idx < ACTS.length - 1) $currentAct.set(ACTS[idx + 1].id);
}

export function prevAct() {
  const idx = ACTS.findIndex((a) => a.id === $currentAct.get());
  if (idx > 0) $currentAct.set(ACTS[idx - 1].id);
}

export function goToAct(id: ActId) {
  $currentAct.set(id);
}
