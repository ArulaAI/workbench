/* Secrets and high-entropy strings. Plan 3.2, satisfying FR-13. */
import { type Finding, type Result, readLines, rel, sourceFiles } from '../lib.ts';

const PATTERNS: [RegExp, string][] = [
  [/\bsk_live_[A-Za-z0-9]{16,}/, 'live secret key'],
  [/\bAKIA[0-9A-Z]{16}\b/, 'AWS access key id'],
  [/-----BEGIN (?:RSA |EC )?PRIVATE KEY-----/, 'private key block'],
  [/\bghp_[A-Za-z0-9]{30,}/, 'GitHub personal access token'],
];

const entropy = (s: string): number => {
  const freq = new Map<string, number>();
  for (const ch of s) freq.set(ch, (freq.get(ch) ?? 0) + 1);
  return [...freq.values()].reduce((h, n) => {
    const p = n / s.length;
    return h - p * Math.log2(p);
  }, 0);
};

export function run(): Result {
  const findings: Finding[] = [];
  for (const file of sourceFiles()) {
    if (rel(file).startsWith('workbench/hooks/secret-scan.ts')) continue;
    readLines(file).forEach((text, i) => {
      for (const [pattern, label] of PATTERNS) {
        if (pattern.test(text)) {
          findings.push({ file: rel(file), line: i + 1, summary: `${label} in source`, severity: 'high' });
        }
      }
      for (const token of text.match(/[A-Za-z0-9+/=_-]{32,}/g) ?? []) {
        if (entropy(token) > 4.6) {
          findings.push({
            file: rel(file),
            line: i + 1,
            summary: `high-entropy string, ${token.length} chars`,
            severity: 'medium',
          });
        }
      }
    });
  }
  return { findings };
}
