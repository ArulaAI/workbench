// Authored example: Node.js 26 / built-in HTTP and SQLite; no web framework.
import { createServer } from 'node:http';
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';

export function createFixture() {
  const db = new DatabaseSync(':memory:');
  db.exec(readFileSync(new URL('./orders.sql', import.meta.url), 'utf8'));

  function cancelOrder(tenantId, orderId, reason) {
    db.exec('BEGIN IMMEDIATE'); // JS-TX
    try {
      const row = db.prepare( // JS-READ
        'SELECT status FROM orders WHERE tenant_id = ? AND order_id = ?'
      ).get(tenantId, orderId);
      if (!row) {
        db.exec('ROLLBACK');
        return [404, {code: 'ORDER_NOT_FOUND'}];
      }
      if (row.status === 'SHIPPED') { // JS-GUARD: no UPDATE on this path
        db.exec('ROLLBACK');
        return [409, {code: 'ORDER_SHIPPED'}];
      }
      if (row.status === 'CANCELLED') {
        db.exec('ROLLBACK');
        return [409, {code: 'ALREADY_CANCELLED'}];
      }
      db.prepare( // JS-WRITE
        "UPDATE orders SET status = 'CANCELLED', cancellation_reason = ? " +
        'WHERE tenant_id = ? AND order_id = ?'
      ).run(reason, tenantId, orderId);
      db.exec('COMMIT'); // JS-OUTPUT
      return [200, {orderId, status: 'CANCELLED'}];
    } catch (error) {
      if (db.isTransaction) db.exec('ROLLBACK');
      throw error;
    }
  }

  async function handler(req, res) {
    function reply(status, payload) { // JS-RESPONSE
      res.writeHead(status, {'Content-Type': 'application/json'});
      res.end(JSON.stringify(payload));
    }
    const path = new URL(req.url, 'http://fixture.invalid').pathname;
    const match = /^\/orders\/([^/]+)\/cancellation$/.exec(path); // JS-ROUTE
    if (req.method !== 'POST' || !match) return reply(404, {code: 'ROUTE_NOT_FOUND'});
    let body;
    try {
      const chunks = [];
      for await (const chunk of req) chunks.push(Buffer.from(chunk));
      body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    } catch {
      return reply(400, {code: 'INVALID_JSON'});
    }
    if (typeof body?.reason !== 'string' || !body.reason.trim()) { // JS-INPUT
      return reply(400, {code: 'REASON_REQUIRED'});
    }
    // JS-CONTEXT: fixed test context; not authentication or authorization.
    const tenantId = 'A';
    try {
      const [status, payload] = cancelOrder(tenantId, decodeURIComponent(match[1]), body.reason.trim());
      return reply(status, payload);
    } catch {
      return reply(500, {code: 'PERSISTENCE_ERROR'});
    }
  }
  // No listener starts on import; tests can invoke the real HTTP handler directly.
  return {db, handler, server: createServer(handler)};
}
