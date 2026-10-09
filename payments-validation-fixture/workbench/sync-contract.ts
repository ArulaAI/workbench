/*
 * Refresh the vendored course contract.
 *
 * The course is the standard. This repository adheres to it and never redefines it.
 * Run this when the course changes, then fix whatever `npm run verify` complains about.
 *
 *   node workbench/sync-contract.ts                      from the sibling checkout
 *   node workbench/sync-contract.ts https://host/contract.json
 *
 * This is the one script allowed to touch the network or leave the repository, and it is
 * never needed to run anything else. NFR-9 still holds for every other command.
 */
import { copyFileSync, existsSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { ROOT } from './lib.ts';

const DEST = join(ROOT, 'corpus', 'course-contract.json');
const SIBLING = join(ROOT, '..', 'validation-workbench-website', 'public', 'contract.json');
const source = process.argv[2];

if (source?.startsWith('http')) {
  const res = await fetch(source);
  if (!res.ok) { console.error(`fetch failed: ${res.status}`); process.exit(1); }
  writeFileSync(DEST, `${JSON.stringify(await res.json(), null, 2)}\n`);
  console.log(`contract synced from ${source}`);
} else if (existsSync(SIBLING)) {
  copyFileSync(SIBLING, DEST);
  console.log('contract synced from the sibling course checkout');
} else {
  console.error('no contract source. Pass a URL, or check out the course beside this repository.');
  process.exit(1);
}
console.log('now run: npm run verify');
