"""Authored example: Python 3.12+ / FastAPI; not a production service."""
from pathlib import Path
import sqlite3
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def create_app():
    app = FastAPI()
    db = sqlite3.connect(':memory:', isolation_level=None, check_same_thread=False)
    db.executescript(Path(__file__).with_name('orders.sql').read_text())
    app.state.db = db

    def cancel_order(tenant_id, order_id, reason):
        db.execute('BEGIN IMMEDIATE')  # PY-TX: read and write in one transaction
        try:
            row = db.execute(  # PY-READ: stored status, scoped by tenant
                'SELECT status FROM orders WHERE tenant_id = ? AND order_id = ?',
                (tenant_id, order_id),
            ).fetchone()
            if row is None:
                db.execute('ROLLBACK')
                return 404, {'code': 'ORDER_NOT_FOUND'}
            if row[0] == 'SHIPPED':  # PY-GUARD: exits before UPDATE
                db.execute('ROLLBACK')
                return 409, {'code': 'ORDER_SHIPPED'}
            if row[0] == 'CANCELLED':
                db.execute('ROLLBACK')
                return 409, {'code': 'ALREADY_CANCELLED'}
            db.execute(  # PY-WRITE: reason and state persisted together
                "UPDATE orders SET status = 'CANCELLED', cancellation_reason = ? "
                'WHERE tenant_id = ? AND order_id = ?',
                (reason, tenant_id, order_id),
            )
            db.execute('COMMIT')  # PY-OUTPUT: success only after commit
            return 200, {'orderId': order_id, 'status': 'CANCELLED'}
        except Exception:
            if db.in_transaction:
                db.execute('ROLLBACK')
            raise

    @app.post('/orders/{order_id}/cancellation')  # PY-ROUTE
    async def cancel_request(order_id: str, request: Request):
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({'code': 'INVALID_JSON'}, status_code=400)
        reason = body.get('reason') if isinstance(body, dict) else None
        if not isinstance(reason, str) or not reason.strip():  # PY-INPUT
            return JSONResponse({'code': 'REASON_REQUIRED'}, status_code=400)
        # PY-CONTEXT: fixed test context; does NOT implement authentication.
        tenant_id = 'A'
        try:
            status, payload = cancel_order(tenant_id, order_id, reason.strip())
        except sqlite3.Error:
            status, payload = 500, {'code': 'PERSISTENCE_ERROR'}
        return JSONResponse(payload, status_code=status)  # PY-RESPONSE

    return app
