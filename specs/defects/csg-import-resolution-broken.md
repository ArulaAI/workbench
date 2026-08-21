# Defect: CSG Layer B import resolution produces 0-12.5% accuracy across tested codebases

Severity: P0
Related Feature: context assembly, architect decomposition, cross-task analysis

## Observed Behavior

Layer B of the CSG (`csg.py:288-310`) resolves import references to file paths using substring matching (`module_as_path in fname`). Across three production codebases, resolution rates range from 0% to 12.5%. Of the imports that do resolve, roughly half are false positives from substring collisions.

| Codebase | Stack | Import refs | Resolved | Rate | False positives |
|----------|-------|-------------|----------|------|-----------------|
| travel-prod | Python/TS monorepo | 8,850 | 1,106 | 12.5% | 550 multi-match (e.g., `os` → `costs-tab.tsx`) |
| maybe | Ruby on Rails | 347 | 2 | 0.6% | N/A |
| cal.com | TypeScript monorepo | 68,791 | 0 | 0.0% | N/A |

Two compounding bugs:

1. **Quote characters in module strings.** ast-grep captures module text with surrounding quotes. `'react'` (with literal quote chars) never matches any filename. On travel-prod, `'react': 444` and `"react": 221` appear as separate dropped entries instead of a merged `react: 665`.

2. **Substring matching picks wrong files.** `module_as_path in fname` means `import os` matches any file with `os` anywhere in its path. On travel-prod, `os` resolves to `costs-tab.tsx` (4 candidates, first match wins). `schema.mutations` matches 31 files.

Downstream impact: 58-68% of files are isolated (zero edges). Layer C clustering runs on a near-empty graph. Architect decomposition, context assembly, and cross-task analysis all consume these clusters.

## Expected Behavior

Import resolution should produce correct file-to-file edges at >50% rate for projects with standard import conventions. External library imports (`react`, `typing`, `logging`) should drop silently rather than false-matching project files. Multi-match ambiguity should be resolved by directory proximity, not first-match-wins.

A precision tier using LSP servers (pyright, tsserver, gopls) should push resolution to 90%+ for projects where those tools are available, with the heuristic tier as fallback.

## Root Causes

Fully traced in `working-docs/tech-spec-csg-clustering-fix.md`, Sections 2.2 and 2.3. Summary:

| Root cause | Code location | Section |
|------------|---------------|---------|
| Substring match (`module_as_path in fname`) | `csg.py:293-299` | 2.2A |
| Only `.py` extension probed | `csg.py:295` | 2.2B |
| `@scope/` prefixes not stripped | `csg.py:293-299` | 2.2C |
| Quote chars in extracted module strings | `treesitter_extract.py:_parse_ast_grep_matches()` | 2.3 |

## Fix Approach

### Tier 1: Heuristic resolution (Fix 0b + Fix 0c)

Zero external dependencies. Pure Python. Detailed algorithm and traced examples in `working-docs/tech-spec-csg-clustering-fix.md`, Section 4 (Phase 0).

**Fix 0b** (3-line change): Strip surrounding quotes from module strings in `_parse_ast_grep_matches()`. Prerequisite for Fix 0c.

**Fix 0c** (new function + 3 modified functions): Replace substring matching with suffix-based path resolution. 6-step algorithm: normalize dots to slashes, strip `@scope/` prefixes, resolve relative paths against importing file, suffix-match against a basename file index, disambiguate by directory proximity, drop external libraries.

Expected resolution rates after Fix 0b + 0c:

| Codebase | Before | After |
|----------|--------|-------|
| travel-prod | 12.5% | >50% |
| maybe | 0.6% | >30% |
| cal.com | 0.0% | >50% |

Cases Fix 0c cannot handle: re-exports (`export { Thing } from './internal'`), type aliases, wildcard exports (`export * from`), Go implicit interface satisfaction, chained attribute access, tsconfig path aliases beyond `@/`.

### Tier 2: LSP server integration (`speed start --lsp`)

Compiler-grade resolution via language servers managed by SPEED as background processes. Requires a separate design spec covering:

- Server lifecycle management (start, health check, shutdown)
- PID/state persistence in `.speed/lsp/`
- Query interface for `textDocument/definition` during CSG build
- Resolution cache at `.speed/lsp/resolution-cache.json` consumed by `build_layer_b()`
- Graceful fallback to Tier 1 when servers unavailable

| Server | Language | Install | Resolution capability |
|--------|----------|---------|----------------------|
| pyright | Python | `pip install pyright` | Full import graph, `__init__.py`, namespace packages, re-exports |
| tsserver | TS/JS | `npm i typescript` | Path aliases from tsconfig, barrel exports, `@scope/` monorepo resolution |
| gopls | Go | `go install golang.org/x/tools/gopls@latest` | Import paths, interface satisfaction, embedded types |

Expected resolution rate: 90%+ where servers are available.

Value beyond import resolution: type-aware context assembly, cross-file rename impact (`textDocument/references`), diagnostics for validation agents.

## Reproduction Steps

1. Clone travel-prod (or any Python/TS monorepo)
2. Run `SPEED_ROOT/.venv/bin/python3 working-docs/verify_edges.py` against the project
3. Observe resolution rate, multi-match count, and dropped module list in output
4. Repeat with maybe (`git clone --depth 1 https://github.com/maybe-finance/maybe.git /tmp/maybe`) and cal.com (`git clone --depth 1 https://github.com/calcom/cal.com.git /tmp/calcom`)

## Additional Context

Audit data files in `working-docs/`: `audit-production-path.txt`, `audit-travel-prod.txt`, `audit-maybe.txt`, `audit-calcom.txt`. Verification script: `working-docs/verify_edges.py`.

The global-unique-name fallback (Section 2.6 of the tech spec) compounds this problem: with 0% import resolution on cal.com, 77% of cross-file edges are name coincidences (`seedBookingAuditLogs` → `title` in an unrelated test file). Fixing import resolution reduces dependence on this fallback. Restricting or removing it is tracked as Fix 0d in the tech spec.
