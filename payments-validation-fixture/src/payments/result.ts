import type { Payment } from './service.ts';

export type GatewayResult =
  | { status: 'approved'; payment: Payment }
  | { status: 'step_up'; challengeId: string; reason?: undefined }
  | { status: 'held'; payment: Payment; reviewId: string }
  | { status: 'declined'; code: 'do_not_honour'; reason?: string };
