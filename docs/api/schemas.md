---
title: Technical Schemas
description: Machine-verifiable structures for the context pipeline and orchestration state.
---

SPEED relies on strict JSON schemas to ensure high-fidelity communication between the orchestrator and agents. The complete schema reference with property tables, examples, and tabs is at [Architecture: Technical Schemas](/docs/architecture/schemas/).

The schemas covered:

| Schema | Location | Purpose |
|--------|----------|---------|
| **Architect Output** | Feature plan output | Task DAG, contract, validation rules, cross-cutting concerns. |
| **CSG** | `.speed/context/semantic-graph.json` | Symbol nodes, reference edges, domain clusters. |
| **Project Map** | `.speed/context/project-map.json` | Canonical file registry with languages and line counts. |
| **Spec Alignment** | `.speed/features/{feature}/context/spec-alignment.json` | Requirement claims mapped to code with confirmed/missing/divergent status. |
| **Task Definition** | `.speed/features/{feature}/tasks/{id}.json` | Per-task definition with files_touched, acceptance criteria, and traceability. |
| **Data Model Contract** | `.speed/features/{feature}/contract.json` | Entity and relationship definitions enforced during integration. |
