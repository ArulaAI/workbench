/*
 * Schedules the risk narrative off the authorisation path. It subscribes through
 * queue.onHeld and defers the work, so nothing here runs inside the authorise call stack.
 * A missing narrative is the documented failure mode: the item stays held without one.
 */

import type { ReviewItem, ReviewQueue } from './queue.ts';
import { type NarrativeContext, type NarrativeWriter, assertNoCardData, buildNarrativeInput } from '../risk/narrative.ts';
import { log } from '../obs/index.ts';

const describeItem = async (
  queue: ReviewQueue,
  writer: NarrativeWriter,
  item: ReviewItem,
  ctxFor: (item: ReviewItem) => NarrativeContext,
): Promise<void> => {
  try {
    const input = buildNarrativeInput(item, ctxFor(item));
    assertNoCardData(input);
    const text = await writer.describe(input);
    if (typeof text === 'string') queue.setNarrative(item.id, text);
  } catch (error) {
    log.error(`narrative scheduling failed for ${item.id}: ${error instanceof Error ? error.message : String(error)}`);
  }
};

/** Returns a function that stops scheduling for items held after it is called. */
export const attachNarrativeWriter = (
  queue: ReviewQueue,
  writer: NarrativeWriter,
  ctxFor: (item: ReviewItem) => NarrativeContext,
): (() => void) =>
  queue.onHeld(item => {
    setImmediate(() => {
      void describeItem(queue, writer, item, ctxFor);
    });
  });
