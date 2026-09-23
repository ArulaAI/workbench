-- Authored Oracle Database 19c / PL/SQL fixture.
-- Run as a disposable BILLING schema owner; DDL has Oracle commit semantics.
CREATE TABLE invoice (
    tenant_id NUMBER(18, 0) NOT NULL,
    invoice_number NUMBER(18, 0) NOT NULL,
    CONSTRAINT invoice_tenant_number_key
        UNIQUE (tenant_id, invoice_number) NOT DEFERRABLE -- ORA-CONSTRAINT
);

CREATE OR REPLACE PROCEDURE create_invoice(
    p_tenant_id IN invoice.tenant_id%TYPE,
    p_invoice_number IN invoice.invoice_number%TYPE,
    p_result OUT VARCHAR2
) AS
BEGIN
    INSERT INTO invoice (tenant_id, invoice_number) -- ORA-WRITE
    VALUES (p_tenant_id, p_invoice_number);
    p_result := 'CREATED'; -- ORA-OUTPUT: no COMMIT here
EXCEPTION
    WHEN DUP_VAL_ON_INDEX THEN
        p_result := 'DUPLICATE_INVOICE_NUMBER'; -- ORA-ERROR-MAP
END;
/
-- This exact fixture has one unique constraint and no triggers.
-- Adding another unique constraint or trigger requires revisiting error attribution.
-- Example in SQL*Plus/SQLcl after setup:
-- VARIABLE result VARCHAR2(30)
-- EXEC create_invoice(1, 123, :result);
-- PRINT result
-- ROLLBACK;
