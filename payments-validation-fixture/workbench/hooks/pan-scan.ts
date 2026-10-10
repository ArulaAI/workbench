/*
 * Luhn-aware PAN scanner. Plan 3.1, satisfying FR-13 and FR-14, and TR12 repository hygiene.
 *
 * Detection is Luhn-based, never length-based: a 13 to 19 digit sequence (spaces and dashes
 * allowed between digits) is reported only when it passes Luhn and starts with a card
 * network leading digit. A millisecond timestamp is 13 digits, and the leading-digit rule
 * keeps the one-in-ten that happen to pass Luhn from failing the hook.
 *
 * Usage:
 *   node workbench/hooks/pan-scan.ts [files...]   scan the given files, or tracked files
 *   node workbench/hooks/pan-scan.ts --history    also scan `git log -p` output
 *
 * Exits non-zero on any match outside ALLOWLIST. Full numbers are allowlisted, not BINs, so
 * a real card that shares a test BIN is still reported.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { type Finding, type Result, ROOT, luhn, rel, sourceFiles } from '../lib.ts';

/**
 * Published scheme test card numbers. Suppressed, and documented as suppressed.
 *
 * Sources: Visa, Mastercard, American Express and Discover test numbers from their
 * published developer and acquirer test-card documentation, plus the Stripe testing
 * guide (docs.stripe.com/testing) and the PayPal/Braintree sandbox card lists, which
 * reproduce the scheme numbers. Every number in test/fixtures/cards.ts must appear here.
 */
export const ALLOWLIST: readonly string[] = [
  '4111111111111111', // Visa
  '4242424242424242', // Visa (Stripe)
  '4000056655665556', // Visa debit (Stripe)
  '5555555555554444', // Mastercard
  '5105105105105100', // Mastercard
  '378282246310005', // American Express
  '371449635398431', // American Express
  '6011111111111117', // Discover
  '6011000990139424', // Discover
  '30569309025904', // Diners Club
  '3530111333300000', // JCB
  '4012888888881881', // Visa
];

// Digits, optionally joined by single spaces or dashes, bounded by non-digits.
const CANDIDATE = /(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)/g;

/** Card network leading digits: 2221-2720 (Mastercard), 3, 4, 5, 6. Excludes timestamps. */
const plausibleNetwork = (digits: string): boolean => {
  const lead = digits[0];
  if (lead === '2') {
    const prefix = Number(digits.slice(0, 4));
    return prefix >= 2221 && prefix <= 2720;
  }
  return '3456'.includes(lead);
};

/** Scan text, returning one finding per non-allowlisted Luhn-valid number. */
export function scanText(text: string, file: string): Finding[] {
  const findings: Finding[] = [];
  text.split('\n').forEach((line, i) => {
    for (const match of line.matchAll(CANDIDATE)) {
      const digits = match[0].replace(/[ -]/g, '');
      if (digits.length < 13 || digits.length > 19) continue;
      if (!plausibleNetwork(digits) || !luhn(digits)) continue;
      if (ALLOWLIST.includes(digits)) continue;
      findings.push({
        file,
        line: i + 1,
        summary: `Luhn-valid ${digits.length}-digit sequence, BIN ${digits.slice(0, 6)}, not an allowlisted test number`,
        severity: 'high',
      });
    }
  });
  return findings;
}

/** Scan files from disk. Unreadable, missing and binary files are skipped. */
export function scanFiles(files: string[]): Finding[] {
  const findings: Finding[] = [];
  for (const file of files) {
    if (!existsSync(file)) continue;
    let buffer: Buffer;
    try {
      buffer = readFileSync(file);
    } catch {
      continue;
    }
    if (buffer.includes(0)) continue; // binary, e.g. PDFs, whose compressed streams hold random digits
    findings.push(...scanText(buffer.toString('utf8'), rel(file) || file));
  }
  return findings;
}

/** Scan every line `git log -p` has ever shown, across all refs. */
export function scanHistory(cwd = ROOT): Finding[] {
  const log = execFileSync('git', ['log', '-p', '--all', '--no-color', '--no-ext-diff'], {
    cwd,
    encoding: 'utf8',
    maxBuffer: 1024 * 1024 * 1024,
  });
  return scanText(log, 'git-history');
}

function trackedFiles(): string[] {
  try {
    const out = execFileSync('git', ['ls-files', '-z'], { cwd: ROOT, encoding: 'utf8' });
    return out.split('\0').filter(Boolean).map(f => resolve(ROOT, f));
  } catch {
    return sourceFiles();
  }
}

export function run(files?: string[], opts: { history?: boolean } = {}): Result {
  const findings = scanFiles(files ?? trackedFiles());
  if (opts.history) findings.push(...scanHistory());
  return { findings };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const history = args.includes('--history');
  const files = args.filter(a => !a.startsWith('--')).map(a => resolve(a));
  const { findings } = run(files.length ? files : undefined, { history });
  for (const f of findings) console.error(`${f.file}:${f.line}: ${f.summary}`);
  process.exit(findings.length ? 1 : 0);
}
