# RFC: {Feature Name}

> See [{product-spec}]({product-spec}) for product context.
> Depends on: [{dep}]({dep}).
<!-- CHILD RFC HEADERS (use when this RFC is part of a multi-RFC feature):
     > Parent RFC: [{parent-rfc}]({parent-rfc})
     > Depends on: [{sibling-rfc}]({sibling-rfc})

     The Parent RFC header tells related_specs.py this RFC belongs to a
     family. The Depends on header lists prerequisite sibling RFCs whose
     output this RFC consumes. Both headers are scored by related_specs.py:
     - Parent ref: BOOST_PARENT_REF = 0.10
     - Dependency: BOOST_DEPENDENCY = 0.50
     - Filename pair with siblings: BOOST_FILENAME_PAIR = 0.15

     NAMING CONVENTION: {feature-name}-{part}.md
     Example: speed-spec-trajectory-foundation.md,
              speed-spec-trajectory-risk.md

     Delete these comments (and the Parent RFC line) for standalone RFCs. -->

## Basic Example
<!-- A concrete code snippet, API call, or GraphQL query showing the feature
     in action. Grounds the reader before the detailed design.
     This is the React RFC pattern — show what it looks like to USE the feature
     before explaining how it works. Omit if not applicable. -->

## Interface Contract
<!-- USE FOR CHILD RFCs ONLY. Delete this section for standalone RFCs.

     When this RFC is part of a multi-RFC feature, declare what it consumes
     from prerequisite RFCs and what it produces for downstream RFCs.

     WHY: The Architect decomposes each child RFC independently. Without an
     explicit interface, the Architect must load the prerequisite RFC to
     understand this RFC's inputs. With an interface, the prerequisite's
     output types and function signatures appear in both specs, so the
     Architect can decompose this RFC without loading the full dependency.

     CONSUMES: Types, functions, or data files produced by prerequisite RFCs.
     Include the function signature or dataclass definition so this RFC is
     self-contained for decomposition.

     PRODUCES: Types, functions, or data files that downstream RFCs consume.
     Include the exact signature and return type.

     Read by: Architect (task input/output), Coherence Checker (interface match) -->

### Consumes (from prerequisite RFCs)
<!-- Example:
     From `speed-spec-trajectory-foundation.md`:
     - `FeatureRecord` dataclass (name, tasks, completed_at, ...)
     - `_load_all_observations(dir) -> dict[str, list[dict]]` -->

### Produces (for downstream RFCs)
<!-- Example:
     - `_score_risk_accumulation(features, csg, obs, root, moderate) -> list[RiskAccumulation]`
     - `RiskAccumulation` dataclass (file, risk_level, evidence, ...) -->

## Data Model
<!-- Tables, columns, relationships, constraints.
     This becomes the contract source of truth. Be precise about types,
     nullability, defaults, and foreign keys.
     Read by: Architect (contract generation), Coherence Checker (interface verification) -->

## State Machine
<!-- If applicable: valid states, transitions, triggers, side effects.
     A table or diagram is better than prose. Include impossible transitions
     explicitly ("archived → active is not allowed because...").
     Omit this section if the feature has no stateful entities. -->

## API Surface
<!-- Endpoints, GraphQL types, mutations, queries.
     For each: input types, return types, error cases.
     Be specific about error responses — "returns 400" is not enough.
     "Returns 400 with {field, message} when name exceeds 100 chars" is.
     Read by: Architect (task decomposition), Developer (implementation), Coherence Checker -->

## Validation Rules
<!-- Business logic constraints. What inputs are rejected and why?
     These become test cases. Every rule here should map to at least one test. -->
| Field | Constraints |
|-------|-------------|
| | |

## Testing

### Acceptance Criteria
<!-- Verifiable statements about what "done" means. Not test names, not
     implementation details. Observable behaviors a reviewer could confirm.

     Bad:  "Test the caching layer."
     Good: "A cold-start query returns in under 200ms. Cache-hit returns
            in under 15ms. Evicted entries re-fetch transparently."

     Each criterion here gates the feature. If it doesn't pass, the feature
     doesn't ship. -->

### Risks and Coverage
<!-- Start from "what could go wrong?" not "what should we test?"
     Derive tests from risks, not from the code structure.
     Google's Inquiry Method: identify risks first, test plan follows.

     Not every feature needs all test levels. A data pipeline might need
     mostly integration tests. A pure function might only need unit tests.
     Blindly following the test pyramid is itself an anti-pattern. State
     what THIS change needs and why. -->

| Risk | Severity | Test Approach |
|------|----------|---------------|
| | | |

### Test Plan

**Unit tests**
<!-- Which modules get new tests? What behaviors do they verify?
     If modifying existing code, note current coverage for affected modules.
     Focus on logic branches and edge cases, not trivial getters. -->

**Integration tests**
<!-- Cross-module or cross-service interactions that need verification.
     Configuration variants that change behavior.
     If integration tests aren't useful for this change, say so and why. -->

**End-to-end tests**
<!-- User-facing workflows that must pass across the full stack.
     If deferred to a later phase, state the milestone and reasoning. -->

**Visual/UI tests**
<!-- Screenshot diffing, layout regression, component rendering checks.
     Which components or pages need visual snapshots? What breakpoints?
     What visual states matter (loading, empty, error, overflow)?
     Omit this section if the feature has no UI. -->

### Edge Cases
<!-- Specific boundary conditions the tests must cover. These are the
     scenarios a reviewer would ask about: empty inputs, max sizes,
     concurrent access, permission boundaries, clock skew, network
     failures, malformed data.

     Listing them here forces you to think through them before writing
     code. Every edge case should trace to a risk from the table above. -->

### Out of Scope
<!-- What is explicitly NOT tested in this phase, and why.
     Prevents reviewers from asking "but what about X?" and prevents
     future engineers from assuming the gap was an oversight.
     e.g., "Performance testing deferred until feature exits beta
     because traffic volume won't justify it before then." -->

## Security & Controls
<!-- Auth: which endpoints need authentication? What roles/permissions?
     Data: any PII? Encryption at rest or in transit?
     Input: sanitization rules, injection prevention.
     Rate limiting: which endpoints? What limits?
     Audit: what actions get logged?
     Think OWASP top 10 for this specific feature. -->

## Key Decisions
<!-- Architectural choices and their rationale. The "Alternatives Considered"
     column is the most important — it proves you did the thinking.
     If alternatives is empty, you haven't explored the design space.
     Read by: Plan Verifier (checks for semantic drift from stated rationale) -->
| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| | | | |

## Drawbacks
<!-- Why should we NOT do this? Implementation cost, complexity, maintenance burden.
     "There are no drawbacks" is never true. Every design choice trades something.
     Be honest — this section builds trust with reviewers and catches problems
     you'd otherwise discover during implementation. -->

## Search / Query Strategy
<!-- If applicable: indexing approach, query patterns, expected performance.
     Include estimated data volumes and access patterns.
     Omit this section if the feature doesn't introduce new queries. -->

## Migration Strategy
<!-- If changing existing data: how do we get from A to B safely?
     Sequence: migrations first or code first? Feature flags? Phased rollout?
     What's the rollback plan if something goes wrong?
     Omit this section if there are no data changes. -->

## File Impact
<!-- Which files, modules, or services does this change touch?
     e.g., "src/backend/app/models/tribe.py (new model),
     src/backend/app/graphql/mutations/tribe.py (new mutations),
     src/frontend/components/features/tribe-card.tsx (new component)"
     Helps the Architect scope tasks and the Developer navigate the codebase. -->

## Dependencies
<!-- What must exist before this can be built?
     Be specific: not "needs auth" but "needs the User model from F1 and
     the session middleware from PR #23." -->

## Unresolved Questions
<!-- What parts of the design are still TBD? What needs investigation?
     Each question should state what it blocks and a proposed path to resolve.
     This section should shrink to zero before speed plan runs. -->
