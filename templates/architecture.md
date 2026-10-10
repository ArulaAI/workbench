# Architecture: {Feature Name}

> See [{product-spec}]({product-spec}) for product context.

<!--
  WHO READS THIS SPEC
  The architect who owns the system writes it. Engineers read it before writing
  the tech spec, the Auditor checks tech specs against its boundaries and
  quality constraints, and the Architect agent treats it as constraints when it
  decomposes work into tasks.

  PLATFORM OR FEATURE
  Use the same template for the platform overview (specs/architecture/overview.md)
  and for a feature (specs/architecture/<feature>.md). The platform document
  describes the system as built; a feature document describes how one feature
  fits into it.

  If a section genuinely does not apply, say so and why, so the omission reads
  as a decision rather than a gap.
-->

## Context
<!-- What problem this architecture solves, the system it lives in, and the
     forces that shape it: load, latency budgets, team ownership, deadlines. -->

## Responsibilities
<!-- What each part of the system is responsible for, and just as important,
     what it is not responsible for. -->

## Boundaries
<!-- Where this feature or system stops. Which services own which data and
     decisions, and which calls cross a boundary. A tech spec that moves a
     responsibility across one of these lines must say so explicitly. -->

## Components and Dependencies
<!-- Components, how they connect, and what each depends on: other services,
     stores, queues, third parties. A diagram or table beats prose. -->

## Data and Trust Boundaries
<!-- What data flows where, what is sensitive (card data, personal data), and
     where trust changes: network edges, third-party calls, untrusted input. -->

## Failure Modes
<!-- What happens when each dependency is slow, down or wrong. Timeouts,
     retries, fallbacks and what the user sees. -->

## Quality Constraints
<!-- Measurable limits the implementation must respect: latency budgets,
     availability, throughput, data retention, consistency guarantees. -->

## Decisions
<!-- Architectural choices with the alternatives considered and why they lost. -->
| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| | | | |

## Verification
<!-- How we will know the architecture holds: tests, load checks, monitoring,
     review gates. Each quality constraint above should map to a check here. -->
