-- Authored SQLite fixture; used independently by each API implementation.
CREATE TABLE orders (
    tenant_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PLACED', 'SHIPPED', 'CANCELLED')),
    cancellation_reason TEXT,
    PRIMARY KEY (tenant_id, order_id)
);
INSERT INTO orders VALUES ('A', 'placed', 'PLACED', NULL);
INSERT INTO orders VALUES ('A', 'shipped', 'SHIPPED', NULL);
INSERT INTO orders VALUES ('B', 'other-tenant', 'PLACED', NULL);
