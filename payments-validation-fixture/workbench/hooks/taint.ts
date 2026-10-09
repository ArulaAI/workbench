/*
 * Taint analysis. Plan 3.3, satisfying FR-13 and FR-7.
 *
 * Follows PAN-typed sources to observability sinks. This is the hook that catches sink 5,
 * where the PAN is never written literally and so a regex finds nothing. It is a shallow
 * intraprocedural pass on purpose: it is a teaching tool, and its limits are part of the
 * lesson. Its profile card should record that it does not follow values across modules.
 */
import { type Finding, type Result, readLines, rel, sourceFiles } from '../lib.ts';

/** Identifiers that hold, or may hold, raw card data. */
const SOURCES = ['pan', 'cardNumber', 'primaryAccountNumber', 'req', 'request', 'body'];

/*
 * Sanitisers. A tainted value wrapped in one of these is considered clean.
 *
 * This is where the hook's honesty lives. It matches on the sanitiser's *name*, so a
 * rename, a wrapper or an inlined copy defeats it. Record that on the profile card:
 * the hook proves absence within its ruleset, and the ruleset is the boundary.
 */
const SANITISERS = ['redact', 'maskedFor', 'tokenise'];

/** Calls that carry a value out of the process. */
const SINKS = [
  { pattern: /\blog\.(debug|info|error|warn)\s*\(/, name: 'application log' },
  { pattern: /\bwebhook\s*\(/, name: 'webhook body' },
  { pattern: /\bspan\s*\(/, name: 'telemetry attributes' },
  { pattern: /\bserialiseFailure\s*\(/, name: 'serialised exception' },
  { pattern: /\bconsole\.(log|error|warn)\s*\(/, name: 'stdout' },
];

export function run(): Result {
  const findings: Finding[] = [];
  for (const file of sourceFiles()) {
    if (!/\.ts$/.test(file)) continue;
    if (rel(file).startsWith('workbench/')) continue;
    const lines = readLines(file);
    lines.forEach((text, i) => {
      for (const sink of SINKS) {
        if (!sink.pattern.test(text)) continue;
        const args = text.slice(text.indexOf('(') + 1);
        const tainted = SOURCES.find(s => new RegExp(`\\b${s}\\b`).test(args));
        const sanitised = SANITISERS.some(fn =>
          new RegExp(`\\b${fn}\\s*\\([^)]*\\b(${SOURCES.join('|')})\\b`).test(args),
        );
        if (tainted && !sanitised) {
          findings.push({
            file: rel(file),
            line: i + 1,
            summary: `${tainted} reaches ${sink.name}`,
            severity: 'high',
          });
        }
      }
    });
  }
  // One line can match two sink patterns. Report the line once.
  const seen = new Set<string>();
  return {
    findings: findings.filter(f => {
      const key = `${f.file}:${f.line}:${f.summary.split(' reaches ')[0]}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }),
  };
}
