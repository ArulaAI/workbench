/*
 * Import resolution check. Plan 3.6, satisfying FR-13, NFR-9 and NFR-10.
 *
 * A full typecheck needs tsc, which needs an install, which NFR-9 forbids. So this hook
 * does the part of the job that catches F1 with no dependency: it resolves every relative
 * import and verifies that each named import actually exists in the target module.
 *
 * That catches a hallucinated method, a renamed export and a moved file. It does not
 * catch a type error, and the profile card must say so. If tsc happens to be installed,
 * the workflow gains a deeper check. If not, the shallow one still runs.
 */
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { type Finding, type Result, readLines, rel, sourceFiles } from '../lib.ts';

const IMPORT = /^\s*import\s+(type\s+)?\{([^}]+)\}\s+from\s+'([^']+)'/;
const BARE = /^\s*import\s+(?:type\s+)?(\w+)\s+from\s+'([^']+)'/;

export async function run(): Promise<Result> {
  const findings: Finding[] = [];
  for (const file of sourceFiles()) {
    if (!/\.ts$/.test(file)) continue;
    const lines = readLines(file);
    for (const [i, text] of lines.entries()) {
      const named = text.match(IMPORT);
      // `import type { ... }` is erased at runtime, so its names are not module exports.
      const typeOnly = Boolean(named?.[1]);
      const spec = named?.[3] ?? text.match(BARE)?.[2];
      if (!spec || !spec.startsWith('.')) continue;

      const target = resolve(dirname(file), spec);
      if (!existsSync(target)) {
        findings.push({
          file: rel(file),
          line: i + 1,
          summary: `import target does not exist: ${spec}`,
          severity: 'high',
        });
        continue;
      }
      if (!named || typeOnly) continue;

      let exports: string[];
      try {
        exports = Object.keys(await import(target));
      } catch (error) {
        findings.push({
          file: rel(file),
          line: i + 1,
          summary: `import target failed to load: ${(error as Error).message.split('\n')[0]}`,
          severity: 'high',
        });
        continue;
      }
      for (const raw of named[2].split(',')) {
        const name = raw.trim().replace(/^type\s+/, '').split(/\s+as\s+/)[0].trim();
        if (!name) continue;
        // Type-only exports are erased at runtime, so an absent name may be a type.
        if (/^type\s/.test(raw.trim())) continue;
        if (!exports.includes(name)) {
          findings.push({
            file: rel(file),
            line: i + 1,
            summary: `'${name}' is not exported by ${spec}`,
            severity: 'high',
          });
        }
      }
    }
  }
  return { findings };
}
