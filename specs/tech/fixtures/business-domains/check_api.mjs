// Tests invoke the HTTP handler with Node streams; no network listener is opened.
import assert from 'node:assert/strict';
import { Readable } from 'node:stream';
import { readFileSync } from 'node:fs';
import { createFixture } from './cancel_api.mjs';
const cases = JSON.parse(readFileSync(new URL('./api_cases.json', import.meta.url), 'utf8'));
async function invoke(fixture, orderId, rawBody) {
  const req = Readable.from([rawBody]);
  req.url = `/orders/${orderId}/cancellation`;
  req.method = 'POST';
  const result = {};
  await fixture.handler(req, {
    writeHead(status, headers) { result.status = status; result.headers = headers; },
    end(body) { result.body = JSON.parse(body); },
  });
  return result;
}
const fixture = createFixture();
for (const c of cases) {
  const result = await invoke(fixture, c.orderId, c.rawBody);
  assert.equal(result.status, c.status);
  assert.deepEqual(result.body, c.body);
  assert.equal(result.headers['Content-Type'], 'application/json');
}
const rows = fixture.db.prepare('SELECT status, cancellation_reason FROM orders ORDER BY tenant_id, order_id').all();
assert.deepEqual(rows.map(r => [r.status, r.cancellation_reason]), [
  ['CANCELLED', 'changed mind'], ['SHIPPED', null], ['PLACED', null],
]);
fixture.db.close();
const failing = createFixture();
failing.db.exec("CREATE TRIGGER fail_update BEFORE UPDATE ON orders BEGIN SELECT RAISE(ABORT, 'fixture failure'); END");
const result = await invoke(failing, 'placed', '{"reason":"changed mind"}');
assert.equal(result.status, 500);
assert.deepEqual(result.body, {code: 'PERSISTENCE_ERROR'});
assert.equal(failing.db.isTransaction, false);
assert.equal(failing.db.prepare("SELECT status FROM orders WHERE tenant_id='A' AND order_id='placed'").get().status, 'PLACED');
failing.db.close();
console.log('PASS JavaScript: 7 shared response cases, persisted fields/tenant isolation, write-failure rollback.');
