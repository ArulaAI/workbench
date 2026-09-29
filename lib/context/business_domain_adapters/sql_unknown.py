"""Diagnostic-only adapter for SQL whose dialect cannot be established."""


def extract(source):
    return []


def diagnostics(source):
    return [{
        "code": "SQL_DIALECT_UNDETERMINED",
        "reason": "SQL dialect could not be established from trusted evidence.",
        "span": (0, len(source.text)),
    }]
