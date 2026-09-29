# Business-domain discovery defect index

Related Feature: speed-business-domain-discovery
Trial repositories: `/private/tmp/speed-domain-petclinic`, `/private/tmp/speed-domain-grocery`

The implementation assessment identified ten separate defects. They are related, but they do not have the same immediate cause, correction or regression tests. Each finding therefore has its own defect record:

1. [F-01 — Parallel extraction normalization drops structural relationships](business-domain-parallel-normalization-drops-structural-relationships.md)
2. [F-02 — The adapter architecture lacks discoverable semantic resolution](business-domain-adapter-contract-lacks-semantic-resolution.md)
3. [F-03 — Incomplete framework endpoints silently default to resolved](business-domain-endpoint-identity-defaults-resolved.md)
4. [F-04 — Traversal exhaustion is mistaken for semantic trace completeness](business-domain-traversal-exhaustion-misreported-complete.md)
5. [F-05 — SQL call extraction mistakes syntax and built-ins for application calls](business-domain-sql-call-extraction-misclassifies-syntax.md)
6. [F-06 — Contract and implementation anchors are not canonically reconciled](business-domain-anchor-canonicalization-missing.md)
7. [F-07 — Implementation units are promoted without entry-point evidence](business-domain-ui-anchor-selection-uses-render-functions.md)
8. [F-08 — Detected operations do not completely hydrate the canonical data model](business-domain-data-model-hydration-incomplete.md)
9. [F-09 — Provider-wide failure becomes a per-packet retry storm and publishable budget truncation](business-domain-provider-failure-retry-storm.md)
10. [F-10 — Provider contract violations cannot self-heal or reliably resume](business-domain-provider-contract-cannot-self-heal-or-resume.md)

## Relationship between the findings

```text
F-01: existing relationships are dropped --------+
                                                  |
F-02: required resolution capability is absent ---+--> incomplete fact graph
                                                  |            |
F-03: incomplete anchors default to success ------+            v
                                                        F-04: empty traversal
                                                              becomes "resolved"

F-05: false SQL calls are invented --------------------> false unresolved frontiers

F-01/F-02/F-03: unresolved endpoint identity ----------> F-06: no canonical anchor
                                                               or alias reconciliation

F-07: implementation syntax replaces registration ------> invalid anchor inventory

F-08: detected resources/effects remain disconnected ----> incomplete data-model hydration

F-09: shared provider failure is retried per packet ------> retry storm, budget masking,
                                                            degraded partial publication

F-10: provider/runtime contracts diverge -----------------> blind one-error repair,
                                                            unverified cache and lost resume
```

F-01 and F-02 can cause relationships to be absent. F-03 independently publishes incomplete boundary records as successful. F-04 then makes absence look like trace completeness. F-05 fails in the opposite direction: it invents edges and makes traces look unresolved for reasons that are not real calls. F-06 means that even evidenced contract and implementation representations have no canonical anchor and alias reconciliation stage before interpretation. F-07 promotes implementation units without first establishing registration, visibility or external invocation. F-08 stores detected resources and effects without completely hydrating the canonical edges, bindings, traces, activities and information uses that make those facts usable. F-09 treats shared provider failure as independent packet failures until it either wastes the attempt or becomes publishable budget truncation.

Fixing one finding does not close the others. The common correction is a single normalized fact contract, discoverable source capabilities, explicit resolution states and trace completion based on satisfied semantic obligations rather than the presence or absence of locally known edges. F-10 additionally requires the runtime provider protocol to use that same contract, aggregate repairable findings, independently verify candidates and durably checkpoint every successful semantic unit.

## Cross-trial assessment rule

Every finding is evaluated against both `/private/tmp/speed-domain-petclinic` and `/private/tmp/speed-domain-grocery`. A defect file states whether each trial directly reproduces the symptom, exercises the same shared mechanism, or provides no direct evidence. Non-reproduction is recorded honestly; it is not converted into proof that the affected path is correct.

All corrections must preserve a language- and framework-agnostic core. Language, SQL-dialect and framework knowledge is permitted only inside trusted discoverable adapters/enrichers that implement the common versioned capability and fact contracts. Core inventory, normalization, tracing, synthesis and verification must not branch on language, dialect or framework names.
