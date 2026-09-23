# Authored business-domain discovery fixtures

These source files support the API and SQL examples in the [RFC](../../speed-business-domain-discovery.md). They are deliberately small examples, not production implementations or existing PetClinic code. Ordinary discovery reads their source; it must not execute them.

## API implementations

- [cancel_api.py](cancel_api.py): Python/FastAPI route, local operation, SQLite reads/writes and HTTP response mapping.
- [cancel_api.mjs](cancel_api.mjs): JavaScript/Node HTTP handler implementing the same shared cancellation cases.
- [orders.sql](orders.sql): independent in-memory SQLite database for each implementation.
- [api_cases.json](api_cases.json): seven ordered request/response cases shared by both checks.

Tenant A is fixed test context. The queries filter by tenant; no authentication or record-level caller authorization is implemented. No remote service call, dynamic loader, message publication or production connection pool exists. The synchronous database operation is intended for a single-process fixture. Request-size protection, full protocol error normalization and production server configuration are outside its scope. The JavaScript factory returns an unbound HTTP server and never listens automatically.

From the repository root, explicit checks used on 2026-09-06:

```sh
.venv/bin/python specs/tech/fixtures/business-domains/check_api.py
node specs/tech/fixtures/business-domains/check_api.mjs
```

Verified locally with Python 3.12, FastAPI 0.141.1, Starlette 1.6.0, HTTPX 0.28.1 and Node.js 26.5.0. No dependencies were installed or lockfiles changed. Python's test client emitted a deprecation warning about its HTTPX integration; the checks passed.

Both checks passed seven response cases: malformed JSON, missing/blank reason, shipped rejection, another tenant's order, missing order, successful cancellation and repeat cancellation. They also verified persisted state/reason, unchanged shipped/other-tenant rows, JSON content type and rollback plus HTTP 500 after an injected database write failure. Python exercises the ASGI app with TestClient. JavaScript exercises the real HTTP handler with streams and a response recorder; it does not test network transport. Neither suite establishes concurrency behavior or full equivalence for arbitrary inputs.

These checks validate authored fixture behavior, not the proposed domain extractor. The RFC's expected finding tables define future extraction assertions. PY-/JS- marker comments aid review; the extractor must establish findings from executable statements and bindings, not comment labels.

## SQL procedure alternatives

- [invoice_postgresql.sql](invoice_postgresql.sql): PostgreSQL 17, PL/pgSQL, named-constraint diagnostics and OUT result.
- [invoice_oracle.sql](invoice_oracle.sql): Oracle Database 19c, PL/SQL, DUP_VAL_ON_INDEX and OUT result.

Status: documentation-reviewed, **not executed**. PostgreSQL/Oracle tools and engines are unavailable in this workspace. Compilation, database-driver output bindings and dialect runtime conformance remain pending. Use a fresh disposable database/schema when performing those checks; Oracle's script assumes the BILLING owner. Oracle DDL commit effects mean setup must be separate from call/rollback checks. Neither procedure commits its successful DML.

After setup, the intended sequence is:

| Call / action | Expected result |
| --- | --- |
| Create `(1, 123)` | `CREATED` |
| Create `(1, 123)` again | `DUPLICATE_INVOICE_NUMBER`; first row remains, no second row |
| Create `(2, 123)` | `CREATED`; same number across tenants allowed |
| Roll back caller transaction | Both successful inserts disappear |
| Create with a null tenant/number | NOT NULL error propagates |

Check null cases separately because unhandled error transaction behavior is dialect-specific. The Oracle duplicate handler is deliberately scoped to the supplied table's single unique constraint and absence of triggers; changes to that schema can invalidate the error attribution. The PostgreSQL procedure checks the diagnostic constraint name. Numeric ranges differ between the dialects; no universal behavioral equivalence is asserted.
