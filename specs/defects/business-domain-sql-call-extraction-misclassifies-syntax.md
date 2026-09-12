# Defect: SQL call extraction mistakes SQL syntax and built-ins for application calls

Severity: P0
Related Feature: speed-business-domain-discovery
Finding: F-05
Status: Resolved
Related Findings: F-02, F-04
Tags: extraction, adapters, sql, plsql, plpgsql, oracle, postgres, calls, tracing, language-agnostic

## Summary

The business-domain SQL adapter does not identify routine calls from a SQL or procedural-SQL syntax tree. It applies a regular expression to every word followed by an opening parenthesis and initially treats every match as a callable invocation.

That expression cannot distinguish between:

- a genuine local procedure or function invocation;
- a package-qualified call;
- a database built-in function;
- an external database package call;
- a table name followed by an `INSERT` column list;
- a join condition beginning with `ON (`;
- a PL/SQL collection subscript; or
- other SQL and procedural-language syntax that permits a word before `(`.

When the matched word does not correspond to another extracted routine in the same package, the common connection builder emits an unresolved `calls` edge. The trace walker places every such edge in its unresolved frontier. False calls therefore make real activities appear incomplete and contaminate the evidence sent to semantic synthesis.

The Grocery trial demonstrates the failure before any provider request. All 29 SQL anchors have unresolved traces, and the graph contains unresolved calls to SQL keywords, table names, built-ins, collection variables and external database packages.

This finding is the inverse of F-04:

- F-04 loses an expected edge and incorrectly reports the trace as resolved.
- F-05 invents nonexistent call edges and incorrectly reports the trace as unresolved.

Both show that trace correctness depends on trustworthy, capability-aware edge production.

## Evidence from the Grocery trial

The trial repository is `/private/tmp/speed-domain-grocery`.

Its persisted `.speed/context/business-domain-facts.json` contains:

- 29 SQL anchors;
- 29 SQL traces;
- zero resolved traces;
- 29 unresolved traces;
- 53 resolved edges; and
- 139 unresolved edges.

The unresolved call targets include:

| Extracted target | Count | Actual construct |
| --- | ---: | --- |
| `ON` | 23 | SQL join-condition keyword |
| `SUM` | 14 | SQL aggregate |
| `put_line` | 13 | External `DBMS_OUTPUT` package routine |
| `NVL` | 10 | Oracle built-in function |
| `TRUNC` | 8 | Oracle/SQL built-in function |
| `MAX` | 7 | SQL aggregate |
| `numtodsinterval` | 6 | Oracle built-in function |
| `IN` | 5 | SQL/PLSQL keyword or membership construct |
| `VARCHAR2` | 5 | Oracle type or conversion syntax |
| `to_char` | 5 | Oracle built-in function |
| `ROUND` | 4 | SQL built-in function |
| `v_all` | 4 | PL/SQL collection access |
| `v_sum` | 4 | PL/SQL collection access |
| `AS` | 3 | SQL keyword |
| `SUBSTR` | 3 | Oracle built-in function |
| `USING` | 3 | SQL keyword |
| `WHEN` | 2 | Conditional or exception syntax |
| `CEIL` | 1 | SQL built-in function |
| `TO_NUMBER` | 1 | Oracle built-in function |

It also creates unresolved calls for table names including `billed_items`, `cost_sales_tracker`, `job_posts_history`, `jta_errors`, `missing_items`, `payroll`, `purchase_order_lines`, `purchase_orders`, `sold_products` and `tax_rate_history`.

Not every record in that list is semantically identical. `DBMS_OUTPUT.PUT_LINE`, for example, is a real external package call. It is still incorrectly represented as a missing source routine rather than a known external database-package target. The defect is both false call creation and loss of the distinctions required to resolve or explain real calls honestly.

### Concrete `add_item_to_bill` example

`JTA_Packages.sql` contains this data write:

```sql
INSERT INTO billed_items (
    bill_line_id, bill_id, product_id, quantity,
    price_rate, tax_code, tax_rate
)
```

The adapter records `billed_items (` as:

```text
Call target billed_items: 0 source candidates
```

`billed_items` is the table receiving the write. The parentheses begin an `INSERT` column list. No call occurred.

The same activity reaches `lookup_barcode`, which contains:

```sql
JOIN products pr ON (inv.product_id = pr.product_id)
```

The adapter records `ON (` as:

```text
Call target ON: 0 source candidates
```

`ON` begins the join predicate. It is not a callable identifier.

That routine also contains:

```sql
IF SUBSTR(p_barcode, 1, 1) = '2' THEN
    p_price_rate := TO_NUMBER(SUBSTR(p_barcode, 7, 5) / 100);
```

`SUBSTR` and `TO_NUMBER` are Oracle built-ins. They should not become missing repository procedures. Depending on the normalized model, they may be retained as resolved dialect-built-in operations or as expression evidence, but they must not create false unresolved application-call frontiers.

The resulting `add_item_to_bill` trace contains genuine resolved package calls alongside false or misclassified unresolved calls. A consumer cannot reliably distinguish business-relevant missing behavior from parser noise.

### What this evidence proves

- The false edges exist in the persisted deterministic facts, before synthesis.
- The same broad regular expression classifies unrelated SQL constructs as calls.
- Keywords and table column lists that cannot be calls are represented as unresolved call targets.
- Known database built-ins and external packages are not distinguished from missing application routines.
- Every Grocery SQL trace is unresolved in the recorded trial.
- Existing tests do not cover the negative SQL contexts demonstrated by Grocery.

### What this evidence does not prove

- It does not prove that all 139 unresolved edges are false. Dynamic calls, unavailable package bodies and genuinely external routines may correctly remain unresolved.
- It does not prove that every one of the 29 traces would be fully resolved after removing false edges. Real external, ambiguous or unsupported behavior must remain visible.
- It does not establish that a particular third-party parser is production-ready for SPEED. Parser candidates require pinned-version corpus and conformance testing.
- It does not establish that one SQL grammar can correctly parse Oracle PL/SQL, PostgreSQL PL/pgSQL and every other database dialect.

## Expected behavior

The implementation must classify SQL and procedural-SQL constructs using dialect-aware syntax rather than punctuation alone.

At minimum, it must preserve these distinctions:

| Source construct | Required normalized behavior |
| --- | --- |
| Local procedure or function invocation | Emit a `calls` edge to the exact routine when resolvable |
| Package-qualified local call | Resolve with package/schema scope and callable signature |
| Ambiguous local overload | Retain candidates or an equivalent bounded ambiguous record and reason |
| Known database built-in | Record a known dialect/runtime operation or expression; do not report a missing repository procedure |
| External database package call | Emit an explicitly external target with implementation availability and evidence |
| Table in `FROM`, `JOIN`, `INSERT`, `UPDATE` or `DELETE` | Emit a data-resource relationship, not a call |
| `INSERT` column list | Emit column bindings when supported, not calls |
| Join `ON` predicate | Preserve predicate/condition evidence, not a call |
| Collection indexing or subscripting | Preserve collection/data access, not automatically a call |
| Dynamic SQL or dynamic invocation | Emit an explicit unresolved dynamic operation with the cause |
| Unsupported dialect syntax | Emit a capability diagnostic and partial coverage, not guessed calls |

A source file's `.sql` extension does not determine its dialect. Dialect selection must use discoverable adapter descriptors and evidenced detection. Unknown or mixed dialects remain explicit rather than silently falling through to a permissive grammar and being treated as complete.

## Actual execution path

### 1. A broad expression identifies candidate calls

`lib/context/business_domain_adapters/sql.py::calls()` scans the text of every extracted procedural operation with:

```python
r'(?i)(?<![\w])(?:(\w+)\s*\.\s*)?(\w+)\s*\('
```

The expression asks only whether an optional receiver and a word appear before `(`. It has no AST node kind or surrounding SQL grammar context.

The exclusion list contains only the current routine name plus `if`, `for`, `while`, `case`, `return` and `values`. It does not and cannot enumerate every keyword, DML form, built-in, type, collection expression or dialect extension safely.

### 2. Candidate resolution assumes an application routine

`sql.py::candidates()` accepts only extracted `declarative_operation` units in the same source language and package owner. It does not classify built-ins or external database packages. It also does not use the call's argument list, named arguments or inferred types when selecting overloaded routines.

The lookup therefore asks the wrong question for many matches:

```text
Is there a locally extracted routine named ON?
Is there a locally extracted routine named billed_items?
Is there a locally extracted routine named NVL?
```

The absence of such a routine is expected, but the implementation interprets it as an unresolved application call.

### 3. The common connection builder creates unresolved edges

`lib/context/business_domain_extract.py::_connections()` receives each regex match from `calls()`. If candidate selection returns no unique target, it creates a `calls` edge with no `to_ref` and a reason of the form:

```text
Call target <name>: 0 source candidates
```

This common behavior is appropriate for a genuine unresolved call. It cannot compensate for a source adapter that falsely classified syntax as a call.

### 4. Trace construction promotes parser noise into incompleteness

`business_domain_extract.py::_traces()` adds every non-resolved edge to the trace frontier. Any false call therefore contributes an unresolved stop reason.

```text
PL/SQL source
      |
      v
Regex finds WORD "("
      |
      v
Everything becomes a call candidate
      |
      +--> genuine local procedure --> possibly resolved
      |
      +--> SQL keyword
      |
      +--> table column list
      |
      +--> built-in function
      |
      +--> collection subscript
                    |
                    v
          no matching local routine
                    |
                    v
          unresolved `calls` edge
                    |
                    v
          added to trace frontier
                    |
                    v
              trace unresolved
```

### 5. Synthesis receives the contaminated trace

Activity packets include the trace's selected edges and stop reasons. The semantic provider must spend its bounded request interpreting false gaps and cannot recover implementation evidence that deterministic extraction mislabeled or omitted.

## Root cause

This is not primarily the parallel-decoder DRY failure recorded as F-01. The SQL adapter is a separate source adapter, but its implementation substitutes a broad textual heuristic for the dialect-aware syntax and resolution capability required by its contract.

The deeper architectural issue overlaps F-02: `sql` is treated as one source language despite materially different grammars and runtime namespaces, including:

- standard or permissive generic SQL;
- Oracle SQL and PL/SQL;
- PostgreSQL SQL and PL/pgSQL;
- SQL Server T-SQL; and
- other vendor dialects.

The common core should remain language-independent, but that does not mean every dialect should share a regex parser. It means dialect-specific parsers and resolvers must implement the same normalized fact and capability contracts.

The current selection mechanism also hardcodes generic `sql` to this Oracle-style module in `business_domain_adapters/catalog.json`. Because `.sql` does not identify a dialect, that mapping is not a valid capability decision. The correction must not add Oracle, PostgreSQL or other dialect checks to core extraction or tracing. Trusted dialect adapters must be discovered from descriptors and activated from source/configuration evidence; unknown dialects must remain explicit.

## Violated requirements

- **Language-independent service tracing contract:** Adapters must provide source-specific facts while accurately declaring their capabilities and gaps.
- **Extraction contract:** Unresolved targets must remain unresolved, but syntax that is not a target must not be fabricated as one.
- **SQL/ORM operations:** Queries, mappings, data reads/writes, parameters and mutation outcomes must be represented according to their actual roles.
- **Rule and trace evidence:** Missing or unsupported behavior must reduce coverage explicitly rather than being confused with parser noise.
- **Bounded tracing:** Trace limits and frontiers describe real omitted or unresolved behavior; they are not a sink for false lexical matches.
- **No invented implementation:** A missing source candidate is meaningful only after the adapter has established that the source construct is a genuine call.
- **Initial SQL conformance examples:** Oracle package routines, DML, constraints, transaction behavior and procedural control flow require source-faithful interpretation.

## User and system impact

- Every Grocery SQL trace appears unresolved before provider synthesis.
- Real procedure-to-procedure calls are mixed with false keyword, table and collection calls.
- Data writes such as `INSERT INTO billed_items` acquire an unrelated missing-call diagnostic.
- Built-in calculations appear to depend on nonexistent repository implementations.
- External database packages cannot be distinguished from local missing source.
- Coverage and trace-frontier counts overstate unresolved application behavior.
- Activity packets spend evidence and token budget on parser artifacts.
- Users cannot tell whether a trace is genuinely incomplete or merely misparsed.
- Removing all unresolved edges to make coverage look better would be equally wrong because genuine dynamic and external gaps must remain.

## Reproduction

1. Open `/private/tmp/speed-domain-grocery/.speed/context/business-domain-facts.json`.
2. Confirm that all 29 traces have `resolution: unresolved`.
3. Group unresolved `calls` edges by their reason or extracted target.
4. Observe unresolved targets including `ON`, `IN`, `AS`, `USING`, `WHEN`, `billed_items`, `SUM`, `NVL`, `SUBSTR`, `v_all` and `v_sum`.
5. Inspect `JTA_Packages.sql` at the corresponding evidence spans.
6. Confirm that `ON (` is a join condition and `billed_items (` follows `INSERT INTO`.
7. Confirm that `NVL`, `SUM`, `TRUNC`, `SUBSTR` and `TO_NUMBER` are database built-ins rather than repository routines.
8. Inspect `lib/context/business_domain_adapters/sql.py::calls()` and confirm that these records all originate from the broad word-before-parenthesis expression.
9. Inspect `sql.py::candidates()` and confirm that lookup recognizes only extracted routines in a matching package owner.
10. Follow each failed lookup through `_connections()` and `_traces()` to the unresolved trace frontier.

## Possible correction

Do not fix this by extending the regex exclusion list with `ON`, `NVL`, `SUM` or the other currently observed names. SQL dialects contain large, versioned keyword and built-in sets, and valid applications can use context-dependent identifiers. An exclusion list would continue producing both false positives and false negatives.

Do not put Oracle, PostgreSQL or other dialect branches into common inventory, connection, tracing or grouping code. Implement the fix through discoverable, trusted dialect adapters that emit the shared normalized contract.

### 1. Add a discoverable dialect capability

Installed adapter descriptors should declare:

- dialect and supported versions;
- recognized extensions;
- syntax and configuration detection evidence;
- parser identity and pinned version;
- supported declaration, call, data, rule and control-flow capabilities;
- unsupported constructs and diagnostic codes; and
- the normalized record contract version they emit.

The analyzed repository may supply source and declarative configuration evidence, but it must not supply executable parser or adapter code.

### 2. Select dialects from evidence

The `.sql` extension alone is ambiguous. Adapter selection should consider evidence such as:

- Oracle `PACKAGE BODY`, `VARCHAR2`, `DBMS_OUTPUT`, `%TYPE` and Oracle-specific syntax;
- PostgreSQL `LANGUAGE plpgsql`, dollar-quoted bodies, `PERFORM`, `RETURN QUERY` and PostgreSQL-specific syntax;
- explicit project configuration or snapshot metadata; and
- bounded parser results, including material `ERROR` and `MISSING` nodes.

If several dialects remain plausible, report dialect ambiguity or retain bounded alternatives. Do not silently select whichever permissive parser returns some nodes.

### 3. Replace regex call discovery with syntax-node queries

For Oracle PL/SQL, evaluate a pinned `tree-sitter-plsql` grammar against the Grocery corpus. `njank/tree-sitter-plsql` is a candidate because it includes packages, function/procedure declarations and definitions, embedded DML, cursors, collection syntax and Oracle-specific constructs. It is new and must pass SPEED's conformance corpus before adoption.

For PostgreSQL and PL/pgSQL, evaluate `gmr/tree-sitter-postgres`, which provides separate PostgreSQL and PL/pgSQL grammars with SQL injection into procedural bodies. Where parser fidelity outweighs ast-grep rule reuse, `libpg_query` is an alternative behind the same adapter protocol and exposes PostgreSQL's parser plus PL/pgSQL parsing.

The existing `DerekStride/tree-sitter-sql` grammar can remain a generic SQL fallback only with explicitly partial capabilities. It must not be presented as complete Oracle PL/SQL or PostgreSQL PL/pgSQL support.

Ast-grep supports Tree-sitter custom languages through compiled dynamic libraries and `customLanguages`. SPEED already uses that packaging pattern for other custom grammars. SQL dialect parser libraries must be built, pinned, checksummed and loaded only from SPEED-controlled locations.

AST queries must select actual grammar nodes for routine invocation, DML targets, table references, predicates, built-ins and collection access. A text shape such as `WORD(` is not a sufficient node contract.

### 4. Resolve genuine calls using dialect scope

Parsing determines whether a construct is a call; it does not by itself establish the target. After classification, the dialect adapter should resolve genuine calls using available evidence such as:

- database/schema identity;
- package identity;
- routine name;
- positional and named argument count;
- parameter modes;
- declared or inferable argument types;
- overload signatures;
- local declarations and imports/synonyms where supported; and
- explicit external-package catalogs.

Insufficient information produces `ambiguous` or `unresolved`, never a guessed resolved edge.

### 5. Preserve built-in and external boundaries

Known dialect built-ins should be classified separately from repository routines. They can remain expression or transformation evidence or point to a trusted dialect-runtime resource, depending on the common contract.

Calls such as `DBMS_OUTPUT.PUT_LINE` and `UTL_MAIL.SEND` should retain their package and operation identity as external database-package calls. Their external implementation need not be fabricated, but “known external package” is materially different from “no source candidate named put_line.”

### 6. Make parse gaps explicit

If the selected parser produces material `ERROR` or `MISSING` nodes, record affected spans and reduce the adapter's declared coverage. Do not silently fall back to the broad regex and do not discard all successfully parsed facts.

## Acceptance tests

The defect is fixed only when all of the following pass:

1. **Join predicate:** Grocery's `ON (...)` clauses produce predicate evidence and no `calls` edges to `ON`.
2. **Insert column list:** `INSERT INTO billed_items (...)` produces a table write and supported column bindings, not a call to `billed_items`.
3. **Oracle built-ins:** `NVL`, `SUM`, `MAX`, `TRUNC`, `ROUND`, `SUBSTR`, `TO_NUMBER`, `TO_CHAR`, `CEIL` and `NUMTODSINTERVAL` do not become missing repository procedures.
4. **Keywords:** `IN`, `AS`, `USING` and `WHEN` do not become calls merely because they precede parentheses in valid syntax.
5. **Collection access:** PL/SQL collection indexing such as `v_sum(indx)` is classified as collection/data access unless source evidence establishes a callable object.
6. **External package:** `DBMS_OUTPUT.PUT_LINE` is represented as an evidenced external database-package call, not an unqualified missing `put_line` routine.
7. **Local unqualified call:** A call to a uniquely matching routine in the same package resolves case-insensitively to that exact declaration or implementation.
8. **Package-qualified call:** `jta_error.log_error(...)` resolves to the correct package member when its body is available.
9. **Overload identity:** Overloaded routines use package/schema, argument count, named arguments and available types. Insufficient evidence remains ambiguous.
10. **Dynamic call:** Dynamic SQL or dynamically selected routines remain explicitly unresolved with a reason and are not dropped to improve coverage.
11. **Oracle discovery:** An Oracle package-body fixture selects the Oracle PL/SQL adapter through descriptor evidence without edits to common tracing code.
12. **PostgreSQL discovery:** A PL/pgSQL fixture selects the PostgreSQL adapter through descriptor evidence without edits to common tracing code.
13. **Ambiguous `.sql`:** A file whose dialect cannot be determined receives an explicit dialect/capability diagnostic rather than an arbitrary parser selection.
14. **Mixed repository:** Oracle, PostgreSQL and generic SQL sources in one repository retain separate adapter identities and feed the same normalized fact contract.
15. **Material parser errors:** `ERROR` or `MISSING` nodes covering material statements reduce reported coverage and identify affected spans.
16. **No regex fallback:** Unsupported parser syntax cannot fall back to the broad `WORD(` application-call heuristic.
17. **Exact evidence:** Every emitted call, data-resource relationship and parser diagnostic retains its exact source-span evidence and parser provenance.
18. **Frontier integrity:** Keywords, table names, built-ins and collection access cannot create false unresolved trace frontiers.
19. **Grocery regression:** Grocery no longer has all 29 traces marked unresolved because of SQL keywords, table names, built-ins, types or collection access.
20. **Honest remaining gaps:** Genuine external, ambiguous, dynamic and unsupported calls remain visible after false edges are removed.
21. **Trusted parser loading:** Parser binaries are pinned, checksummed, cross-platform and loaded only from SPEED-controlled locations; repository-supplied libraries cannot execute.
22. **Capability reporting:** Each dialect adapter reports declaration, call, overload, data-access, rule and control-flow capability independently rather than claiming complete SQL support from parse success alone.
23. **No core dialect branches:** Supporting another SQL dialect requires only a trusted adapter, descriptor and conformance fixtures; core inventory, tracing, synthesis and verification contain no SQL/Oracle/PostgreSQL conditionals.

## Parser candidates requiring conformance evaluation

- Oracle PL/SQL Tree-sitter candidate: <https://github.com/njank/tree-sitter-plsql>
- Oracle PL/SQL upstream alternative, explicitly incomplete: <https://github.com/andreasmaierde/tree-sitter-plsql>
- PostgreSQL and PL/pgSQL Tree-sitter candidate: <https://github.com/gmr/tree-sitter-postgres>
- PostgreSQL native-parser extraction alternative: <https://github.com/pganalyze/libpg_query>
- Generic SQL Tree-sitter fallback: <https://github.com/DerekStride/tree-sitter-sql>
- Ast-grep custom-language integration: <https://ast-grep.github.io/advanced/custom-language>

## Resolution

- Oracle and PostgreSQL adapters now use pinned SQLGlot dialect tokenizers and syntax parsing; generic SQL remains explicitly unsupported when dialect evidence is insufficient.
- Calls, built-ins, predicates, collections, DML targets, column bindings, external packages, dynamic SQL and material parse gaps are classified separately with exact spans and parser provenance.
- Local/package/schema resolution is case-insensitive and uses receiver scope, arity, named arguments and available types; ambiguity and unavailable behavior remain explicit.
- The parser is pinned to a checksummed cross-platform wheel, its installed RECORD hashes and import location are verified before import, and repository shadow modules are rejected.
- The shared capability contract reports declaration, call, overload, data, rule and control-flow dimensions independently; core inventory and tracing contain no dialect branches.
- Verification passed: 249 Discover tests, all 23 valid/14 invalid contract specimens, compilation and diff checks. The live Grocery corpus produced 53 resolved and 13 explicit external calls, zero false keyword/table/built-in/collection calls, and two resolved traces instead of none.
