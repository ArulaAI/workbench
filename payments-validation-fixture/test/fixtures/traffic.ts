/*
 * Labelled synthetic traffic for the adaptive authorisation work.
 *
 * Every card number is built at runtime from a scheme test BIN, so no Luhn-valid literal
 * appears in this file. Labels are ground truth: `genuine` was the cardholder, and
 * `card_testing` was someone checking whether a stolen number works.
 */
import { TEST_CARDS, EXPIRY } from './cards.ts';
import type { GatewayRequest } from '../../src/payments/gateway.ts';

export type Label = 'genuine' | 'card_testing';
export type LabelledRequest = { scenario: string; label: Label; request: GatewayRequest };

const T0 = Date.UTC(2026, 9, 3, 14, 0, 0);
const MINUTE = 60 * 1000;

/** Complete a 15-digit body with its Luhn check digit. */
const withCheckDigit = (body: string): string => {
  let sum = 0;
  for (let i = 0; i < body.length; i += 1) {
    let d = body.charCodeAt(body.length - 1 - i) - 48;
    if (i % 2 === 0) { d *= 2; if (d > 9) d -= 9; }
    sum += d;
  }
  return body + String((10 - (sum % 10)) % 10);
};

/** A distinct test card per index, all sharing the 411111 test BIN. */
export const testingCard = (i: number): string =>
  withCheckDigit(`411111${String(100_000 + i).padStart(9, '0')}`);

/** A UK cardholder on holiday buying a television from a UK retailer, from a hotel in Japan. */
export const travellerTelevision: LabelledRequest = {
  scenario: 'high-value traveller',
  label: 'genuine',
  request: {
    pan: TEST_CARDS.visa, expiry: EXPIRY, amount: 249_900, currency: 'GBP',
    merchantId: 'm_electricals', ipCountry: 'JP', at: T0,
  },
};

/** The same cardholder buying groceries at home. */
export const domesticGroceries: LabelledRequest = {
  scenario: 'routine domestic',
  label: 'genuine',
  request: {
    pan: TEST_CARDS.visa, expiry: EXPIRY, amount: 6_420, currency: 'GBP',
    merchantId: 'm_grocer', ipCountry: 'GB', at: T0 - 3 * 24 * 60 * MINUTE,
  },
};

/**
 * A card-testing run. One script, forty stolen numbers, one small authorisation each,
 * rotated across twenty merchants and four exit countries, a few seconds apart.
 */
export const cardTestingBurst = (size = 40): LabelledRequest[] =>
  Array.from({ length: size }, (_, i) => ({
    scenario: 'card-testing burst',
    label: 'card_testing' as const,
    request: {
      pan: testingCard(i), expiry: EXPIRY, amount: 100, currency: 'GBP',
      merchantId: `m_${String(i % 20).padStart(2, '0')}`,
      ipCountry: ['GB', 'NL', 'US', 'DE'][i % 4],
      at: T0 + i * 4_000,
    },
  }));
