-- Authored PostgreSQL 17 / PL/pgSQL fixture; use an empty disposable database.
CREATE SCHEMA billing;
CREATE TABLE billing.invoice (
    tenant_id bigint NOT NULL,
    invoice_number bigint NOT NULL,
    CONSTRAINT invoice_tenant_number_key
        UNIQUE (tenant_id, invoice_number) NOT DEFERRABLE -- PG-CONSTRAINT
);

CREATE PROCEDURE billing.create_invoice(
    IN p_tenant_id bigint, IN p_invoice_number bigint, OUT p_result text
)
LANGUAGE plpgsql AS $$
DECLARE
    violated_constraint text;
BEGIN
    INSERT INTO billing.invoice (tenant_id, invoice_number) -- PG-WRITE
    VALUES (p_tenant_id, p_invoice_number);
    p_result := 'CREATED'; -- PG-OUTPUT: caller still owns commit
EXCEPTION
    WHEN unique_violation THEN
        GET STACKED DIAGNOSTICS violated_constraint = CONSTRAINT_NAME;
        IF violated_constraint <> 'invoice_tenant_number_key' THEN
            RAISE;
        END IF;
        p_result := 'DUPLICATE_INVOICE_NUMBER'; -- PG-ERROR-MAP
END;
$$;
-- Example call within a caller-controlled transaction:
-- BEGIN; CALL billing.create_invoice(1, 123, NULL); ROLLBACK;
