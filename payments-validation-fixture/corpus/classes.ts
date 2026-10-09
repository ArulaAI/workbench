/*
 * The failure classes. Derived from the course contract, never restated here.
 *
 * The course is the standard. This file reads corpus/course-contract.json, which is a
 * vendored copy of what the course publishes. Refresh it with `npm run sync-contract`
 * and let `npm run verify` tell you what stopped conforming.
 *
 * It used to declare its own copy of the eight classes. Within a day, F4's title said
 * one thing here and another on the course site, and nothing noticed.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export type ClassId = 'F1' | 'F2' | 'F3' | 'F4' | 'F5' | 'F6' | 'F7' | 'F8';

export type FailureClass = { id: ClassId; title: string; humanReserved: boolean };

export type Contract = {
  version: number;
  vocabulary: {
    composedThing: string;
    composedFile: string;
    kinds: Record<string, string>;
    kindLabels: Record<string, string>;
    banned: string[];
  };
  failureClasses: FailureClass[];
  evidenceTypes: { key: string; name: string }[];
  units: { slug: string; label: string; title: string; artifact: string | null }[];
  artifacts: { name: string; unit: string | null }[];
};

export const contract: Contract = JSON.parse(
  readFileSync(fileURLToPath(new URL('./course-contract.json', import.meta.url)), 'utf8'),
);

export const failureClasses: FailureClass[] = contract.failureClasses;
export const classById = new Map(failureClasses.map(c => [c.id, c]));
export const allClassIds: ClassId[] = failureClasses.map(c => c.id);
