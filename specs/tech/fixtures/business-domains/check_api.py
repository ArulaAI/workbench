"""Explicit fixture checks; never run by ordinary domain discovery."""
import json
from pathlib import Path
from fastapi.testclient import TestClient
from cancel_api import create_app

app = create_app()
cases = json.loads(Path(__file__).with_name('api_cases.json').read_text())
with TestClient(app) as client:
    for case in cases:
        response = client.post('/orders/' + case['orderId'] + '/cancellation',
                               content=case['rawBody'], headers={'Content-Type': 'application/json'})
        assert response.status_code == case['status'], case
        assert response.json() == case['body'], case
        assert response.headers['content-type'].startswith('application/json')
    rows = app.state.db.execute('SELECT status, cancellation_reason FROM orders ORDER BY tenant_id, order_id').fetchall()
    assert rows == [('CANCELLED', 'changed mind'), ('SHIPPED', None), ('PLACED', None)], rows
app.state.db.close()
# A write failure must not produce success or leave a transaction/mutation behind.
app = create_app()
app.state.db.execute("CREATE TRIGGER fail_update BEFORE UPDATE ON orders BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
with TestClient(app) as client:
    response = client.post('/orders/placed/cancellation', json={'reason': 'changed mind'})
    assert response.status_code == 500 and response.json() == {'code': 'PERSISTENCE_ERROR'}
    assert not app.state.db.in_transaction
    assert app.state.db.execute("SELECT status FROM orders WHERE tenant_id='A' AND order_id='placed'").fetchone() == ('PLACED',)
app.state.db.close()
print('PASS Python: 7 shared response cases, persisted fields/tenant isolation, write-failure rollback.')
