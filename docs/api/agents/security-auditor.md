---
title: Security Auditor
description: The Security Auditor scans feature code for OWASP vulnerabilities across SAST, SCA, and secrets dimensions.
---

## Mission

The Security Auditor is a security engineer that reviews source code for vulnerabilities. It reads all files in scope, evaluates each against OWASP Top 10 categories, and reports findings in structured JSON with enough detail for a developer to act. It does not fix vulnerabilities.

## Invocation

| Property | Value |
|----------|-------|
| Command | `speed security [--create-defects]` |
| Assembly function | `context_assemble_security_auditor` |
| Model tier | `support_model` (Sonnet) |
| Tools | Read, Glob, Grep (read-only) |
| Trigger | Manual |

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Feature name | CLI argument or auto-detected | Identifies the feature under audit |
| Files in scope | Task file lists and code diffs | Full content of each file, presented under path headings |
| Product spec | `specs/product/<feature>.md` | Intended behavior context |
| Tech spec | `specs/tech/<feature>.md` | Intended data flows and auth model |
| Project conventions | `CLAUDE.md` | Naming, architecture, and patterns |

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Security audit report | `.speed/features/<feature>/security-audit.json` | Findings with OWASP categories, severity, file locations, recommendations |
| Defect specs (optional) | `specs/defects/` | Generated when `--create-defects` flag is used, for findings above severity threshold |

## Process

1. **Work through each file in scope.** For every file, check against each OWASP category below. Flag a finding only when direct evidence exists in the code.

2. **Exclude test files.** Do not flag test fixtures, test helpers, or files under `tests/`, `test/`, or `__tests__/` directories. Do not flag example files or intentional security test cases.

3. **Report findings.** Each finding includes a sequential ID (`SEC-NNN`), severity, OWASP category, file path, line number, code snippet (max 200 chars), and a concrete recommendation naming the specific function, library, or pattern to use.

## OWASP Categories Checked

| Category | ID | Focus |
|----------|----|-------|
| Broken Access Control | A01 | Missing auth on route handlers, authorization gaps, direct object references without ownership checks |
| Cryptographic Failures | A02 | MD5/SHA1 for security purposes, hardcoded keys/secrets, unencrypted sensitive data, deprecated ciphers (ECB, RC4, DES) |
| Injection | A03 | SQL via string concatenation, OS commands via user input to subprocess/exec/eval, NoSQL injection, LDAP injection |
| Security Misconfiguration | A05 | Debug mode in production paths, wildcard CORS on authenticated routes, default credentials, verbose error responses leaking internals |
| Auth Failures | A07 | Passwords without slow hash (bcrypt/argon2/scrypt), session fixation, missing rate limiting on login/reset, JWT `alg: none` |
| SSRF | A10 | User-controlled URLs passed to HTTP clients, redirect endpoints following caller-supplied URLs, server-side URL fetchers |

## Severity Mapping

| Severity | Criteria | Priority |
|----------|----------|----------|
| critical | Remote code execution, auth bypass with no preconditions, secrets in public code | P0 |
| high | SQL injection, missing auth on sensitive ops, hardcoded credentials, SSRF with no filtering | P1 |
| medium | Weak crypto for security purposes, verbose error disclosure, missing rate limiting on auth | P2 |
| low | Debug flags in non-production paths, permissive CORS on non-sensitive routes | P3 |
| info | Best-practice deviations with negligible exploitability | Informational |

## How It Works

The security audit pipeline collects all feature files, presents them with full source content, and runs the agent with a structured output template.

```
speed security [--create-defects]
    │
    ├─ 1. Resolve feature name
    ├─ 2. Assemble audit context
    │      ├─ Collect files_touched from all task JSON files
    │      ├─ Load full file contents from worktree
    │      ├─ Load product spec + tech spec
    │      └─ Load CLAUDE.md conventions
    ├─ 3. Send to Security Auditor agent (Sonnet, read-only)
    │      └─ Uses structured output template
    ├─ 4. Parse JSON findings
    │      └─ Save to .speed/features/<feature>/logs/security-audit.json
    └─ 5. (Optional) Generate defect specs
           └─ For findings above severity threshold
```

### Phase 1: Feature resolution

`security_audit_run` (`lib/security.sh:333-380`) takes the feature name as argument. The feature's task directory must exist at `.speed/features/<feature>/tasks/`.

### Phase 2: Context assembly

`context_assemble_security_auditor` (`lib/context_bridge.sh:672-750`) runs a Python script that:

1. Scans all task JSON files under the feature's `tasks/` directory
2. Collects the union of `files_touched` from every task
3. Reads full file contents from the project root (skips files that don't exist)
4. Loads product spec from `specs/product/<feature>.md`
5. Loads tech spec from `specs/tech/<feature>.md`
6. Loads project conventions from `CLAUDE.md`

The assembled prompt presents each file's full content under path headings:

```
# Security Audit: <feature>

## Files in scope
<N> file(s) in scope.

### src/backend/services/borrow.py
\```
<full file content>
\```

## Product spec
<product spec content>

## Tech spec
<tech spec content>

## Project conventions
<CLAUDE.md content>
```

### Phase 3: Agent execution

Lines 356-365 call `provider_run_json` with the security-auditor agent definition, Sonnet model, a structured output template (`templates/security-audit-output.json`), a maximum of 10 turns, and a 900-second timeout. The agent has read-only tools (Read, Glob, Grep) for additional investigation.

### Phase 4: Parse and persist

Lines 370-379 parse the agent output via `parse_agent_json` and write the result to `security-audit.json` in the feature's logs directory.

### Phase 5: Defect generation

When `--create-defects` is passed, findings above the configured severity threshold are converted to defect spec files in `specs/defects/`, formatted for the defect pipeline.

## Worked Example

A `user-auth` feature with 4 tasks producing 6 files. The Borrowing service contains a SQL query built with string concatenation.

### What the context includes

```
# Security Audit: user-auth

## Files in scope
6 file(s) in scope.

### src/backend/services/auth.py

def authenticate(username, password):
    query = f"SELECT * FROM users WHERE username = '{username}' AND password = '{password}'"
    result = db.execute(query)
    ...

### src/backend/routes/login.py

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']
    user = authenticate(username, password)
    ...
```

### What the agent returns

```json
{
  "feature": "user-auth",
  "timestamp": "2024-01-15T10:30:00Z",
  "agent_model": "sonnet",
  "findings": [
    {
      "id": "SEC-001",
      "severity": "high",
      "category": "injection",
      "title": "SQL injection via string concatenation in authenticate()",
      "description": "User-supplied username and password are interpolated directly into a SQL query string using f-string formatting. An attacker can inject arbitrary SQL.",
      "file": "src/backend/services/auth.py",
      "line": 3,
      "snippet": "query = f\"SELECT * FROM users WHERE username = '{username}' AND password = '{password}'\"",
      "recommendation": "Use parameterized queries: db.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, password))"
    },
    {
      "id": "SEC-002",
      "severity": "medium",
      "category": "auth",
      "title": "Plain-text password comparison",
      "description": "Password is compared directly against the database value without hashing. Passwords should be hashed with bcrypt or argon2.",
      "file": "src/backend/services/auth.py",
      "line": 3,
      "snippet": "AND password = '{password}'",
      "recommendation": "Store password hashes using bcrypt.hashpw(). Compare with bcrypt.checkpw() instead of SQL equality."
    }
  ],
  "summary": {
    "total": 2,
    "by_severity": {"critical": 0, "high": 1, "medium": 1, "low": 0, "info": 0}
  }
}
```

### What the user sees

```
  Running Security Auditor agent on feature 'user-auth'...

  Security Audit: 2 finding(s)
    HIGH   SEC-001  SQL injection via string concatenation in authenticate()
                    src/backend/services/auth.py:3
    MEDIUM SEC-002  Plain-text password comparison
                    src/backend/services/auth.py:3

  Report saved to .speed/features/user-auth/logs/security-audit.json
```

## Constraints

- Read-only access. No writes, no shell commands, no code execution, no network requests.
- Investigation only. Every action must be a file read (Read, Glob, or Grep).
- Flag only when direct evidence exists in the code. Do not flag suspected issues elsewhere.
- When in doubt about whether something is a test fixture, read surrounding code for context.

## Output Schema

```json
{
  "feature": "feature-name",
  "timestamp": "ISO 8601",
  "agent_model": "sonnet",
  "findings": [
    {
      "id": "SEC-001",
      "severity": "critical | high | medium | low | info",
      "category": "injection | auth | secrets | crypto | config | xss | path-traversal | info-disclosure",
      "title": "Short description",
      "description": "Detailed explanation",
      "file": "relative/path/to/file.py",
      "line": 42,
      "snippet": "vulnerable code (max 200 chars)",
      "recommendation": "Concrete fix naming the function/library/pattern to use"
    }
  ],
  "summary": {
    "total": 0,
    "by_severity": { "critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0 }
  }
}
```
