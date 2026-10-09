/* Shared plumbing for checks. No dependencies, per NFR-3 and NFR-9. */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

export type Finding = {
  file: string;
  line: number;
  summary: string;
  severity: 'low' | 'medium' | 'high';
};

export type Result = {
  findings: Finding[];
  /** Set when the check could not run. Produces evidence `silence` per FR-24/NFR-10. */
  skipped?: string;
};

export const ROOT = new URL('..', import.meta.url).pathname.replace(/\/$/, '');

const SKIP = new Set(['node_modules', '.git', '.speed', 'bundles', 'dist', '.github']);

export function walk(dir = ROOT, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (SKIP.has(name)) continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

export const sourceFiles = (): string[] =>
  walk().filter(f => /\.(ts|mts|js|mjs|json|md|ya?ml)$/.test(f));

export const rel = (file: string): string => relative(ROOT, file);

export const readLines = (file: string): string[] => readFileSync(file, 'utf8').split('\n');

export const luhn = (digits: string): boolean => {
  let sum = 0;
  let alt = false;
  for (let i = digits.length - 1; i >= 0; i -= 1) {
    let d = digits.charCodeAt(i) - 48;
    if (d < 0 || d > 9) return false;
    if (alt) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    sum += d;
    alt = !alt;
  }
  return digits.length > 0 && sum % 10 === 0;
};
