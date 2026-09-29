# Defect: Traversal exhaustion is mistaken for semantic trace completeness

Severity: P0
Related Feature: speed-business-domain-discovery
Finding: F-04
Status: Resolved
Related Findings: F-01, F-02, F-03, F-05
Tags: tracing, graph, resolution, reachability, completeness, obligations, language-agnostic

## Summary

The trace walker marks a trace `resolved` whenever its recorded frontier is empty. The frontier contains only edges the walker saw but could not follow, plus depth and symbol-limit stops. It contains nothing when a required relationship was never extracted.

Consequently, these two states produce the same result:

- every relationship required to reach a supporting implementation was resolved; and
- every edge present in an incomplete local graph was exhausted.

An interface method, abstract method, contract declaration or unimplemented declaration can have no outgoing edges in the graph. Under the current algorithm, that absence creates no frontier or diagnostic and is therefore treated as success.

PetClinic's OpenAPI `POST /visits` operation is a concrete false-resolution example: its trace is marked resolved after visiting only the OpenAPI declaration, while the existing `VisitRestController.addVisit` implementation is disconnected in a separate trace.

## Evidence from the PetClinic trial

The trial repository is `/private/tmp/speed-domain-petclinic`.

The trace artifact contains 95 traces:

- 62 are marked `resolved`;
- 33 are marked `unresolved`;
- 49 resolved traces contain exactly one symbol and no edges;
- those 49 comprise 36 OpenAPI traces and 13 TSX traces.

That count does not prove that all 49 are wrong. A trusted adapter may legitimately identify a concrete leaf implementation with no downstream calls. It proves that the current `resolved` state cannot distinguish such a valid terminal from a declaration whose required implementation relationship was never extracted.

### Concrete `addVisit` example

The OpenAPI document declares `POST /visits` with `operationId: addVisit`.

`VisitRestController` implements the generated `VisitsApi` interface and contains a concrete `addVisit` body that:

- maps the request;
- calls `ClinicService.saveVisit`;
- maps the response; and
- constructs a `201 Created` response.

The facts artifact stores the contract and controller as disconnected anchors:

| Source anchor | Persisted trace |
| --- | --- |
| `src/main/resources/openapi.yml::POST /visits` | `resolved`; one symbol; zero edges; empty frontier; empty stop reasons; null reason |
| `VisitRestController.addVisit` | `unresolved`; three reached symbols; nine edges; seven unresolved or ambiguous frontier edges |

The OpenAPI trace has ID `trace:a4dd391239b196e66861af85`. Its anchor is `anchor:21e1e532c9466c0e2bf7cedc`, and its sole symbol is `symbol:3b6d1c4303b3c8506f39117f`.

It never reaches `VisitRestController.addVisit`, whose separate symbol is `symbol:2fbcd480735299566bd61ded`.

The declaration-only trace therefore appears more complete than the trace starting at the actual implementation. The claim is not that the controller trace is known to be semantically complete. The demonstrated defect is that the contract trace is positively marked resolved without reaching the available implementation at all.

### What this evidence proves

- The OpenAPI `addVisit` trace visits only its declaration symbol.
- A corresponding concrete controller body exists in the same source inventory but is absent from that trace.
- The trace has no edge, frontier item, stop reason or diagnostic.
- The walker derives `resolved` from the empty frontier.
- No independent implementation-reached or valid-terminal condition is evaluated.
- A relationship missing from extraction cannot become a frontier item under the current representation.

### What this evidence does not prove

- It does not prove that every one-symbol trace is invalid.
- It does not prove that every OpenAPI operation has exactly one implementation.
- It does not prove that name equality alone should connect the OpenAPI and controller methods.
- It does not prove that the controller's downstream calls are all resolvable.
- It does not justify treating every empty outgoing-edge list as an error; a positively identified concrete leaf can be a valid terminal.

## Grocery trial applicability

Grocery was checked for the same false-resolved trace symptom. It does **not** directly reproduce it in the persisted trial: all 29 SQL traces are marked unresolved because each contains unresolved frontier edges. F-05 establishes that many of those frontiers are false or misclassified SQL calls.

That result does not validate the trace-completion algorithm. It means F-05 currently masks the empty-frontier side of F-04 in this repository. Removing false SQL edges could make a routine's frontier empty, at which point the common `_traces()` logic would again derive `resolved` solely from frontier absence.

The SQL adapter also discards package-specification declarations before tracing, so Grocery contains no declaration-only package-spec traces against which to exercise semantic terminal rules. A language-agnostic correction must cover both outcomes:

- a package specification without a resolved body is not a concrete implementation terminal; and
- a concrete package-body routine with no outgoing calls may be a valid terminal only when the adapter positively identifies its executable body and all required obligations are satisfied.

This is why F-04 must not be implemented as a Java/interface special case.

## Exact execution path

`Extractor.extract()` calls `_connections()` and then `_traces()`. `_connections()` stores only relationships returned by the active adapters. A relationship dropped by F-01 or unavailable because of F-02 never enters `facts['edges']`.

`_traces()` constructs its outgoing-edge map exclusively from persisted edges:

```python
outgoing: dict[str, list[dict]] = {}
for edge in self.facts['edges'].values():
    outgoing.setdefault(edge['from_ref']['id'], []).append(edge)
```

For each anchor, it starts a breadth-first walk at the anchor's symbol. It examines only relationships already present in that map:

```python
for edge in outgoing.get(symbol, []):
```

The frontier is populated only when:

- a persisted edge is marked ambiguous or unresolved;
- a persisted edge has no target;
- the symbol limit is reached; or
- the depth limit is reached.

There is no record meaning “this declaration requires an implementation edge, but no extractor supplied one.” When the outgoing list is empty, the queue ends. Resolution is derived solely from whether the frontier contains anything:

```python
resolution='unresolved' if frontier else 'resolved'
```

### Flow from the top

```text
Explicit repository-digest refresh
                |
                v
          refresh_digest()
                |
                v
             discover()
                |
                v
        Extractor.extract()
                |
        +-------+--------+
        |                |
        v                v
  create anchors    create known edges
        |                |
        +-------+--------+
                v
           _traces()
                |
                v
       start at anchor symbol
                |
                v
       outgoing.get(symbol, [])
          /                 \
 known edge exists      no known edge exists
        |                       |
        v                       v
 follow it or record      queue becomes empty
 an explicit frontier           |
          \                     /
           +---------+---------+
                     v
             is frontier empty?
                /          \
              yes           no
               |             |
               v             v
          `resolved`     `unresolved`
```

For the OpenAPI `addVisit` anchor, no contract-to-interface or contract-to-controller edge exists. The walker visits the OpenAPI symbol, finds no outgoing edge, creates no frontier, and records `resolved`. The concrete controller implementation cannot be considered because it is not reachable through the incomplete edge set.

## Downstream propagation

The incorrect trace state does not stay local:

1. `packet_for(..., 'activity', ...)` includes only the trace's recorded symbols and edges. The activity provider receives the OpenAPI declaration without the controller body, service call or missing-implementation gap.
2. `accept_activity()` blocks `verified_on_trace` only when the referenced trace's stored resolution is not `resolved`. It does not independently prove that the trace reached an implementation.
3. Domain symbol memberships are derived from the trace's symbol list. A declaration-only trace can therefore be presented as the implementation membership of an activity.

The implementation collapses two different questions:

| Question | Answer available today |
| --- | --- |
| Did the walker exhaust every edge present in its local graph? | Yes |
| Did the trace satisfy every relationship required to reach supporting implementation? | Unknown |

Only the first follows from an empty queue and frontier. The RFC trace contract requires the second before claiming resolution.

## Root cause

Traversal state and semantic proof state share one field.

The graph contains positive edges but no language-independent obligations describing:

- the starting symbol's role—contract, declaration, interface, concrete implementation or external boundary;
- which relationship capabilities must be satisfied;
- which expected relationships are absent;
- what terminal roles are valid for the anchor; or
- whether the active adapters had enough capability and evidence to make the decision.

F-01 and F-02 can cause the graph to be incomplete, but F-04 remains independently necessary. Even a better graph can legitimately stop at declarations, ambiguous selections, unavailable source and external boundaries. Empty adjacency is never, by itself, proof of an implemented production path.

F-05 demonstrates the inverse error: fabricated SQL edges create false frontiers and false unresolved traces. Together they show that correct trace status requires both trustworthy edges and explicit semantic completion obligations.

## Expected behavior

1. Mechanical traversal completion and semantic trace resolution are separate fields or decisions.
2. Every activity anchor declares a normalized starting role and required relationship capabilities.
3. Missing expected relationships become explicit unresolved obligations even when no concrete edge exists.
4. A production activity trace resolves only after reaching a supported terminal through the required resolved relationships.
5. A contract, interface, abstract method or declaration is not a valid implementation terminal merely because it has no outgoing edges.
6. A concrete leaf can resolve with zero downstream calls only when a trusted adapter positively identifies an executable body and all required selection/incoming obligations are satisfied.
7. Ambiguous, external, unavailable and capability-incomplete boundaries retain explicit states and reasons.
8. Core tracing evaluates normalized roles, obligations and terminal records without checking language or framework names.

## Violated requirements

- **Trace definition:** A trace is a chain of typed, resolved relationships from an activity anchor to supporting implementation.
- **Spring and frontend connections:** An OpenAPI contract is an anchor, not proof that its implementation exists.
- **Bounded tracing:** Depth and symbol limits are resource controls, not claims of semantic completeness.
- **Extraction contract:** Missing and unsupported behavior must remain explicit.
- **Support decision table:** Declared-only behavior or a missing production path is at most partial; supported status requires a resolved production path.
- **No invented implementation:** Exhausting an incomplete graph cannot prove implementation.
- **Language-independent core:** Adapters express roles, obligations and terminals through common records rather than language checks in tracing.

## User and system impact

- Declaration-only traces can be marked resolved without reaching implementation.
- Missing extractor capabilities disappear as apparent success instead of reducing coverage.
- Coverage looks healthier than the underlying evidence.
- Semantic synthesis receives a closed-looking packet that omits both implementation and the fact that it is missing.
- `verified_on_trace` can trust a false-positive trace state.
- Domain memberships can label contract-only symbols as implementation evidence.
- A real concrete trace can appear less complete than its disconnected declaration.
- Provider time and token budget are spent interpreting a fundamentally misleading evidence boundary.

## Reproduction

1. Run repository-digest refresh against `/private/tmp/speed-domain-petclinic`.
2. Inspect the two anchors whose operation name is `addVisit`.
3. Confirm that OpenAPI anchor `anchor:21e1e532c9466c0e2bf7cedc` has trace `trace:a4dd391239b196e66861af85` with one symbol, zero edges, an empty frontier, no stop reason and `resolution: resolved`.
4. Confirm that the trace does not contain concrete controller symbol `symbol:2fbcd480735299566bd61ded`.
5. Confirm that `VisitRestController` implements `VisitsApi` and contains the concrete `addVisit` body.
6. Inspect `_traces()` and confirm that it builds adjacency only from persisted edges.
7. Confirm that a missing relationship creates no obligation or frontier record.
8. Confirm that final trace resolution depends only on whether the recorded frontier is empty.
9. Inspect `packet_for`, `accept_activity()` and domain membership derivation to observe how the false resolved state propagates.

## Required correction

1. Separate traversal exhaustion from semantic trace resolution.
2. Extend the normalized adapter contract so adapters can declare whether a symbol is a contract, declaration, interface, abstract declaration, concrete executable implementation or external boundary.
3. Let adapters declare, through language-independent records, the relationship capabilities required for each anchor and the valid terminal conditions.
4. Represent missing expected relationships as explicit unresolved obligations with stable reason codes, source evidence and capability diagnostics.
5. Require an implementation-backed path for traces that claim implemented production behavior.
6. Keep contract-only and declaration-only traces unresolved or partial even when their outgoing edge list is empty.
7. Allow a concrete zero-call leaf to resolve only when a trusted adapter identifies an executable body and all required incoming/selection obligations are satisfied.
8. Preserve ambiguous implementations and bounded candidates instead of selecting one implicitly.
9. Preserve external and unavailable boundaries explicitly; do not equate them with either a missing local edge or a verified implementation.
10. Propagate trace obligations, stop reasons and adapter capability gaps into every applicable model-ready graph scope.
11. Prevent `verified_on_trace`, supported activity status and implementation-role memberships from relying on mechanical traversal exhaustion.
12. Evaluate all completion rules in common tracing code using normalized roles and obligations, without language or framework branches.

## Acceptance tests

The defect is fixed only when all of the following pass:

1. **Declaration is not implementation:** A contract, interface method, abstract method or declaration with no implementation edge produces an unresolved trace with a missing-implementation reason.
2. **PetClinic `addVisit`:** The `POST /visits` trace either reaches exact `VisitRestController.addVisit` implementation evidence or remains explicitly unresolved. It cannot be a resolved one-symbol, zero-edge trace while disconnected.
3. **Traversal state is separate:** A fixture that exhausts every recorded edge while retaining an unsatisfied obligation records traversal completion but semantic resolution remains unresolved.
4. **Concrete leaf terminal:** A concrete executable method with no calls resolves only when positively identified as a valid terminal and no required relationship or capability is missing.
5. **Missing-edge visibility:** Removing a required relationship producer creates an explicit obligation/frontier diagnostic rather than changing the trace to resolved.
6. **Ambiguous implementation:** A contract with two plausible implementations remains ambiguous and retains bounded candidates.
7. **External implementation:** A target outside available source stops at an explicit external or unavailable boundary and is not called a resolved production trace without authorized evidence.
8. **Capability gap:** A selected adapter lacking a required resolution capability leaves an explicit unresolved obligation.
9. **Activity validation:** `verified_on_trace` and supported activity status are rejected for declaration-only, capability-incomplete or obligation-incomplete traces even when traversal completed.
10. **Graph-input completeness:** Whole-graph and deterministic-slice inputs include stop reasons, unsatisfied obligations and capability gaps.
11. **Implementation membership:** Memberships labeled `implements` originate only from implementation-backed traces; contract-only symbols remain declarations or unresolved evidence.
12. **Cross-language terminal contract:** Equivalent contract, declaration, concrete-leaf, ambiguous and external fixtures in Java and at least one non-Java adapter produce the same completion outcomes without changes to core tracing.
13. **Bounded traversal:** Depth and symbol limits set explicit traversal stop conditions and cannot be mistaken for semantic success.
14. **False-edge resistance:** Removing the false SQL call edges described in F-05 can remove false frontiers but cannot by itself upgrade a trace whose real semantic obligations remain unsatisfied.
15. **SQL contract terminal:** A package-spec declaration without a resolved package body remains unresolved or partial even when it has no outgoing edges.
16. **SQL executable leaf:** A package-body routine with no calls resolves only when the dialect adapter positively identifies the executable body and all required contract/selection obligations are satisfied.

F-04 must remain a separate defect even after F-01 and F-02 improve the graph. A complete graph walk is an algorithmic fact; a complete implementation trace is a semantic claim requiring positive evidence.

## Resolution

Status: completed

- Mechanical traversal completion is now independent from semantic resolution; missing implementation, capability and limit obligations remain explicit.
- Adapters provide normalized roles, required relationships/capabilities and positively evidenced executable terminals. Contract, abstract, ambiguous, external and SQL spec/body boundaries retain their distinct outcomes.
- Trace diagnostics and capability records propagate to every model-ready graph scope, and incomplete traces cannot support verified activities or implementation memberships.
- Cross-language, bounded traversal, SQL and PetClinic regressions cover all 16 acceptance criteria. PetClinic's OpenAPI `addVisit` trace is now explicitly unresolved rather than falsely resolved.
- Verification passed: 328 Discover/shared extraction tests, 23 valid and 14 invalid contract specimens, Python compilation, and diff integrity checks.
