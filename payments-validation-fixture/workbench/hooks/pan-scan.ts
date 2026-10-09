/*
 * Luhn-aware PAN scanner. Plan 3.1, satisfying FR-13 and FR-14.
 *
 * Regex plus Luhn plus BIN range, over the whole tree. Test BINs are allowlisted, and
 * that allowlist is the documented Chapter 4 false positive: the scanner does see the
 * scheme test cards, and it suppresses them. A learner who has not read the profile card
 * will escalate a suppressed hit as a real one.
 */
import { type Finding, type Result, luhn, readLines, rel, sourceFiles } from '../lib.ts';

/** Published scheme test BINs. Suppressed, and documented as suppressed. */
export const ALLOWLIST_BINS = ['411111', '400005', '555555', '378282', '601111'];

const CANDIDATE = /\b(?:\d[ -]?){12,18}\d\b/g;

export function run(): Result {
  const findings: Finding[] = [];
  for (const file of sourceFiles()) {
    if (rel(file).startsWith('workbench/hooks/pan-scan.ts')) continue; // do not scan self
    readLines(file).forEach((text, i) => {
      for (const match of text.matchAll(CANDIDATE)) {
        const digits = match[0].replace(/[ -]/g, '');
        if (digits.length < 13 || digits.length > 19) continue;
        if (!luhn(digits)) continue;
        const bin = digits.slice(0, 6);
        if (ALLOWLIST_BINS.includes(bin)) continue; // the documented suppression
        findings.push({
          file: rel(file),
          line: i + 1,
          summary: `Luhn-valid ${digits.length}-digit sequence, BIN ${bin}, not allowlisted`,
          severity: 'high',
        });
      }
    });
  }
  return { findings };
}
