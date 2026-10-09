/*
 * Issuer country by BIN. Risk rules v1.
 *
 * A static table copied from the scheme BIN file at launch and not refreshed since. It
 * holds the scheme test BINs only, because this repository never sees a live card. A BIN
 * that is not in the table resolves to null, and the rules treat an unknown issuer as
 * domestic.
 */

const ISSUER_COUNTRY: Record<string, string> = {
  '411111': 'GB',
  '400005': 'GB',
  '555555': 'GB',
  '378282': 'US',
  '601111': 'US',
};

export const issuerCountry = (bin: string): string | null => ISSUER_COUNTRY[bin] ?? null;
