# Spec Construction Guide

Three phases: preparation, drafting, and verification. The preparation phase prevents the most expensive bugs (writing about code you haven't read). The drafting phase produces specs that agents can execute without guessing. The verification phase catches internal inconsistencies that no amount of good intentions prevents.

---

## Phase 1: Preparation

Do this before writing a single line of the spec.

### Read the code

- [ ] **Read every file the spec will reference or modify.** Not skim. Read. If the spec touches `lib/context/assembly.py`, open it, read the function signatures, understand what parameters they take and what they return. If the spec depends on an observation infrastructure, find and read the files that implement it.
- [ ] **For existing interfaces your spec will consume, copy the signatures from source.** Open the file or the prerequisite RFC. Copy the function name, parameters, types, and return type character by character. Do not type them from memory.
- [ ] **For JSON formats your spec will read or write, find an actual example on disk.** If your spec reads `state.json`, find a real `state.json` in the project. Note the exact field names and value types. Your spec's field names must match exactly.
- [ ] **For greenfield features with no existing code, read the interfaces your spec will consume from.** Prerequisite RFCs, library APIs, framework documentation. Phase 1 still applies; the "code" is the interface definitions your feature depends on.

If you cannot verify a claim about the codebase, do not write it. "I think the function takes three arguments" is not a spec. Open the file.

### Understand the consumers

Three agents will read this spec. Each one needs different things from it.

| Agent | What it reads | What it needs | How it fails |
|-------|--------------|---------------|-------------|
| Architect | Full spec plus related specs (scored by relevance; for child RFCs, siblings and parent are included) | File paths for every behavior, data model before logic, per-story acceptance criteria, explicit dependencies between sections | Scope is vague, file ownership is ambiguous, dependencies are implicit |
| Developer | Implementation sections, interface contracts, examples | Complete function/method signatures, specified error handling, concrete input/output examples, named constants with values | Signatures are incomplete, error handling says "as appropriate", edge cases listed in tests but missing from implementation |
| Reviewer | Acceptance criteria, output contracts, regression zones | Independently verifiable criteria, concrete output examples with correct values, list of files that overlap with other features | Criteria require full-system understanding, output format is described but not shown |

---

## Phase 2: Drafting

Apply these while writing each section of the spec.

### Structure for the Architect

- [ ] **File Impact table early.** List every file created or modified, with a one-line description of the change. The Architect uses this to assign file ownership. Without it, the Architect invents file paths from training data.
- [ ] **Data model before behavior.** Present types, schemas, and structures before the functions that use them. The Architect creates foundation tasks first; if types are buried after the algorithm, decomposition order is wrong.
- [ ] **Explicit section dependencies.** If Section 5 consumes the output of Section 3, write it: "Consumes the `moderate_areas` set from Step 3. Area names are CSG cluster IDs when CSG is present, directory paths otherwise." The Architect turns these into task dependency edges.
- [ ] **Scope boundaries name files, not concepts.** "Out of scope: modifications to the dashboard" is not enforceable. "Out of scope: files under `dashboard/`" is.

### Specify for the Developer

- [ ] **Every function has a full signature.** Name, parameters with types, return type. No exceptions. "A function that computes volatility" cannot be implemented. A complete signature with typed parameters can.
- [ ] **Error handling is explicit.** For every operation that can fail (file not found, malformed input, null value, timeout), state the behavior: return null, skip with warning, use a default, raise. "Handle errors appropriately" produces five different implementations from five agents.
- [ ] **Concrete examples before abstract descriptions.** Show the function being called with real-looking input and output before explaining the algorithm. The Developer wires things up from the example, then implements the internals from the algorithm.
- [ ] **Constants have names, values, and locations.** Token budgets, thresholds, timeouts, window sizes. Each needs: a name, a numeric value, and which file or section defines it. Unnamed constants scatter as magic numbers.

### Choose the right representation for each section

Implementation sections use real code in the project's language. The Developer agent writes in that language; giving it code in the same language eliminates translation errors. Other representations complement the code where they communicate more clearly.

| Content type | Primary representation | Complement with |
|-------------|----------------------|----------------|
| Data structures (fields, types, constraints) | Code in the project's language (class, struct, type definitions) | Schema table for the interface contract (field name, type, required/optional, description). The code is authoritative; the table is for cross-RFC reference. |
| Decision logic (thresholds, classifications) | Decision table: condition columns, outcome column | Code block if the branching logic has subtle ordering dependencies |
| Algorithms (matching, grouping, scoring, traversal) | Code in the project's language | Numbered steps as a summary above the code block for orientation |
| Data flow between components | Diagram (ASCII or mermaid) | Prose only if fewer than 3 components |
| Output formats (JSON, config files) | Concrete example with realistic, arithmetically correct values | Schema table mapping each key to its source field |

**Code blocks are the default for implementation sections.** The project's language is the shared vocabulary between the spec and the Developer agent. Schema tables, decision tables, and numbered steps are for contracts and summaries that need to be readable without running the code.

**Decision tables replace nested conditionals for classification logic.** Risk scoring with 4 tiers, area classification with 3 bands, severity assignment with multiple conditions. Tables make branches countable and exhaustive in a way nested if/else does not.

**Schema tables live in Interface Contract sections.** They summarize the code's data structures for cross-RFC consumption. The code definition is authoritative; the schema table is for the Architect and for sibling RFCs that need to reference fields without reading the full code block.

### Document data representations across boundaries

When a value crosses a pipeline step, function boundary, or serialization layer, the producer and consumer must agree on what the value represents, not just what type it is.

- [ ] **For every value passed between pipeline steps, document what it contains, not just its type.** "`moderate_areas: set of strings`" is a type. "`moderate_areas: set of area names, where area names are CSG cluster IDs when CSG is present and directory paths when CSG is absent`" is a representation contract. The type allows comparison; the representation contract tells you whether the comparison is meaningful.
- [ ] **For every output field, verify the field name matches between the data structure and the serialized output.** If your schema has a field called `retry_rate` but your output JSON example shows `retry_rate_in_area`, one of them is wrong. Compare every field name character by character.
- [ ] **For every persistent output format, include a `schema_version` field.** When the output structure changes between code versions, consumers reading old files need to detect the mismatch. Incremental hashes catch input changes, not schema changes.
- [ ] **Output example values must be consistent with the algorithm.** If your algorithm computes `touch_rate = features_in_window / window` and your example shows `window: 5` and `features_in_window: 5`, the `touch_rate` must be `1.0`, not `0.86`. Run the algorithm mentally on the example inputs and verify the outputs match. A Developer comparing their implementation against a wrong example will "fix" correct code to match the wrong example.

### Testing plan is a contract, not a wish list

- [ ] **The testing section covers the happy path.** At minimum: one test per function showing normal input producing expected output. If a function has no happy-path test, the spec doesn't define what correct behavior looks like.
- [ ] **Every edge case in the testing section has a corresponding branch in the implementation.** If the test plan says "empty input returns empty result," the implementation must contain the guard clause. Do not list edge cases you haven't implemented handling for.
- [ ] **RFC acceptance criteria trace to PRD success criteria.** Each acceptance criterion in the RFC should map to at least one success criterion in the linked PRD. An RFC that passes all its own criteria but addresses none of the PRD's goals is a correctly-built wrong thing.

### Self-containment

- [ ] **No forward references to unwritten specs.** If the spec says "see the future caching RFC for details," that section is incomplete. Either include enough detail for the current scope or mark it explicitly as out of scope.
- [ ] **Every external interface consumed is documented in the spec.** If the implementation calls an existing function, the spec includes that function's signature and return type. The agent should not need to read other files to understand this spec.
- [ ] **Helper functions referenced in the implementation are defined in the implementation.** If `compute_volatility` calls `area_to_cluster`, the spec must show `area_to_cluster`'s implementation (or explicitly say "body omitted, trivial lookup"). Agents implement what the spec shows; a called-but-undefined function becomes a stub that does nothing.

---

## Phase 3: Verification

Run these checks after the draft is complete. Every check is mechanical. Either it passes or it doesn't.

### All spec types

**1. Links resolve.**
- [ ] Every `[text](path)` link pointing to a local file resolves to a file that exists right now.
- [ ] Every `> See`, `> Depends on`, and `> Parent RFC` header link resolves.
- [ ] Every user story ID referenced exists in the linked PRD's User Stories table.

**2. Tables are populated.**
- [ ] Every table has at least one real data row (no placeholder dashes, no TBD).
- [ ] Every table column referenced in prose actually exists in the table.

**3. Success criteria are mechanically testable.**
- [ ] Each criterion can produce a pass/fail result without human judgment.
- [ ] No criteria use "appropriate," "reasonable," "properly," or "correctly" without a numeric or structural definition.

**4. Scope boundaries are complete.**
- [ ] Every Out of Scope item has a reason (not just "out of scope: X" but "because Y").
- [ ] No In Scope item contradicts an Out of Scope item in a linked spec.

### PRD-specific

**5. User story coverage.**
- [ ] Every user flow maps to at least one user story. A flow without a story has no acceptance criteria.
- [ ] Every success criterion traces to at least one user story.

**6. RFC Decomposition integrity (multi-RFC only).**
- [ ] Every user story ID appears in at least one child RFC's row. Count and compare.
- [ ] Dependency graph is acyclic.
- [ ] Every child RFC has a testable output (not "works correctly").

### RFC-specific

**7. Data structure constructability.**
- [ ] List every required field in every data structure definition (the ones with no default and not marked optional).
- [ ] Find every place that data structure is constructed in the spec (search for the type name followed by an opening delimiter).
- [ ] For each construction site, verify every required field is present. A missing required field is a runtime error.
- [ ] Every factory method, static method, or instance method called elsewhere has a body in the definition (or an explicit "body omitted" note).

**8. No dead computed values.**
- [ ] For every variable assigned inside a function body, find where it is consumed (return, constructor, function argument, downstream expression). A computed value used nowhere means a missing field assignment.

**9. Signature consistency.**
- [ ] For every function defined in the spec, find every call site. Compare: argument count, argument names, argument types. Mismatches crash at runtime.
- [ ] For child RFCs: the Consumes signatures must match the prerequisite's Produces signatures character for character. Open them side by side.

**10. Return type consistency.**
- [ ] For every function that returns a value, find every call site. Check what operations the caller performs on the return value. If the return type is a union that includes null but the caller accesses a field without a null guard, the contract is broken.

**11. Loop cost.**
- [ ] For every function called inside a loop: read its body. If it contains a loop over growing data, the combination is O(n*m). Build an index before the outer loop or document the cost.
- [ ] If you've built batch indices for 2 of 3 similar expensive operations, build one for the third. Inconsistency means one path is accidentally quadratic.

**12. Edge case traceability.**
- [ ] Every edge case in the Testing section has a corresponding branch in the implementation. If no branch exists, add one or remove the edge case.

**13. Serialization fidelity.**
- [ ] If automatic serialization produces field names that differ from the output contract, the serializer must explicitly rename or exclude them.
- [ ] Mentally serialize a sample instance. Compare every key name to the output contract. No undocumented keys.
- [ ] Verify the output example's values are arithmetically consistent with the algorithm described in the spec.

**14. Data-flow tracing across steps.**

For every parameter in every function defined in this spec:

- [ ] If the parameter comes from another function's return value or another pipeline step's output, identify where that value is produced.
- [ ] Read what the producer says the value contains (not the type; the representation). Read what the consumer does with it.
- [ ] Verify the consumer's operations are valid for all possible representations the producer can emit. If the producer emits cluster IDs or directory paths depending on configuration, the consumer must handle both, not assume one.
- [ ] For every function that was replaced, renamed, or inlined during drafting, grep for the old name across the entire spec (Produces, test plans, interface contracts, edge cases). Every stale reference is a bug.

**15. Testing plan completeness.**
- [ ] At least one happy-path test exists for every function defined in the spec.
- [ ] Every acceptance criterion (RFC) or verification criterion (Design) maps to at least one success criterion in the linked PRD. A spec that passes its own criteria but addresses none of the PRD's goals is a correctly-built wrong thing.

### Design-specific

**16. Token/value traceability.**
- [ ] Every color references a token name, not a hex code.
- [ ] Every spacing references a token, not a pixel value.
- [ ] Every font specification references a typography role, not raw size/weight.

**17. State completeness.**
- [ ] Interactive element states table has no empty cells (use "N/A with reason").
- [ ] All four page-level states (empty, loading, populated, error) have content.

**18. Component containment.**
- [ ] Every Component ID has a Parent ID tracing to a Region. No orphans.
- [ ] No duplicate Component IDs.

### Multi-RFC family (run once after all children are drafted)

**19. Cross-child interface alignment.**
- [ ] For each child's Consumes, open the prerequisite's Produces side by side. Compare every signature character by character.
- [ ] If you changed, removed, or inlined a function in one child after the initial draft, grep for that name across all children. Every reference must be updated or removed.

**20. Story coverage.**
- [ ] Union of all child RFC story IDs equals the PRD's full story ID set.

**21. Dependency ordering.**
- [ ] For each child in order, every function and type in its Consumes section is defined in an earlier child.

**22. Data representation consistency across children.**
- [ ] For every value in a child's Consumes that originates from a different child's Produces, verify both specs document the same representation (not just type). If Produces says "area names are CSG cluster IDs or directory paths depending on CSG availability," Consumes must say the same thing and the consuming code must handle both forms.

---

## When to Use Each Phase

| Situation | Phase 1 | Phase 2 | Phase 3 |
|-----------|---------|---------|---------|
| New standalone PRD | Full | Full | Checks 1-6, 15 |
| New standalone RFC | Full | Full | Checks 1-4, 7-15 |
| New standalone Design spec | Full | Full | Checks 1-4, 16-18 |
| New child RFC in a family | Full | Full | Checks 1-4, 7-15, then 19-22 after all children done |
| Modifying an existing spec | Re-read changed files | Apply to changed sections | Type-appropriate checks on changed sections (PRD: 5-6; RFC: 7-15; Design: 16-18), plus check 19 if child RFC |
| Splitting a monolith into children | Re-read all code blocks being split | Apply to each child | Full pass on every child, then 19-22 on the family |
