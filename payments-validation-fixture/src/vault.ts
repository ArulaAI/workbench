/*
 * Tokenisation. Plan 2.6, satisfying FR-9 (NO_PAN_AT_REST).
 *
 * The vault is the only place a PAN is allowed to exist, and even here it is held as a
 * last-four plus a token. Everything downstream carries the token. That is what makes
 * "no PAN at rest" an invariant a command can assert rather than a slogan.
 */

export type Token = string & { readonly __brand: 'token' };

export type Card = {
  token: Token;
  last4: string;
  bin: string;
  expiry: string;
};

const store = new Map<Token, { last4: string; bin: string; expiry: string }>();
let counter = 0;

export const isLuhnValid = (digits: string): boolean => {
  if (!/^\d+$/.test(digits)) return false;
  let sum = 0;
  let alt = false;
  for (let i = digits.length - 1; i >= 0; i -= 1) {
    let d = digits.charCodeAt(i) - 48;
    if (alt) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    sum += d;
    alt = !alt;
  }
  return sum % 10 === 0;
};

/** Runs of 13 to 19 digits (spaces and dashes allowed between digits) that pass Luhn. */
export const findLuhnCandidates = (text: string): string[] => {
  const out: string[] = [];
  for (const match of text.matchAll(/\d(?:[ -]?\d){12,18}/g)) {
    const digits = match[0].replace(/\D/g, '');
    if (isLuhnValid(digits)) out.push(match[0]);
  }
  return out;
};

/*
 * Luhn candidates in the string values of a record, walking arrays and objects.
 * Numbers are skipped on purpose: a millisecond timestamp is 13 digits and passes
 * Luhn about one time in ten, so scanning a serialised record reports `at` fields.
 */
export const findLuhnCandidatesIn = (value: unknown): string[] => {
  if (typeof value === 'string') return findLuhnCandidates(value);
  if (Array.isArray(value)) return value.flatMap(findLuhnCandidatesIn);
  if (value && typeof value === 'object') return Object.values(value).flatMap(findLuhnCandidatesIn);
  return [];
};

export const tokenise = (pan: string, expiry: string): Card => {
  const digits = pan.replace(/[ -]/g, '');
  if (!/^\d{13,19}$/.test(digits) || !isLuhnValid(digits)) {
    throw new RangeError('invalid card number');
  }
  const token = `tok_${(++counter).toString(36).padStart(8, '0')}` as Token;
  const record = { last4: digits.slice(-4), bin: digits.slice(0, 6), expiry };
  store.set(token, record);
  return { token, ...record };
};

export const describe = (token: Token): Card | undefined => {
  const r = store.get(token);
  return r ? { token, ...r } : undefined;
};

export const maskedFor = (token: Token): string => {
  const r = store.get(token);
  if (!r) throw new RangeError('unknown token');
  return `${r.bin}******${r.last4}`;
};

/** The stored records, for asserting that no PAN is held at rest. */
export const records = (): Array<{ token: Token; last4: string; bin: string; expiry: string }> =>
  [...store].map(([token, r]) => ({ token, ...r }));

export const reset = (): void => {
  store.clear();
  counter = 0;
};
