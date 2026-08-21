# RFC: Dashboard Learning Curation

> See [product spec](../product/speed-dashboard-learning.md) for product context.
> Prototype: [learning-prototype.html](../../working-docs/learning-prototype.html)
> Depends on: [Observations RFC](speed-observations.md), [Synthesis RFC](speed-synthesis.md)

## Basic Example

```graphql
# Query 1: portfolio trajectory and per-feature lessons
query LearningTrajectory {
  learningTrajectory {
    summary                         # LLM narrative (nullable)
    featureCount
    observationCount
    trajectory {
      feature
      coveragePct
      firstPassRate
      escalationCount
      reworkCount
    }
    latestFeature {
      name
      taskCount
      retryCount
      escalationCount
      coveragePct
      criteriaPassRate
      lessons {
        type                        # "good" | "warn"
        title
        detail
        refMarker                   # "A" | "B" | "C" etc
        metric                      # nullable supporting number
      }
    }
    failureClassification {
      pipelineFailures
      pipelineFailuresTrend         # "improving" | "stable" | "worsening"
      specComplexityFailures
      specComplexityTrend
    }
  }
}

# Query 2: proposed changes from synthesis
query LearningProposals {
  learningProposals {
    proposals {
      id
      type                          # "template" | "convention" | "audit"
      title
      mechanism                     # "writes to project-knowledge.json → conventions"
      changeText                    # the exact guidance text
      refMarker                     # matches lesson refMarker
      evidenceSummary               # "6 observations across 3 features, weight 12.5"
      evidence {
        patternDescription
        observations {
          description
          feature
          weight
          type                      # observation type (retry, reviewer_finding, etc.)
        }
        trendData {
          feature
          value
          label                     # "2 rework" | "0 rework"
        }
      }
      status                        # "proposed" | "accepted" | "dismissed"
    }
  }
}

# Mutation: accept or dismiss a proposal
mutation CurateProposal($id: String!, $action: String!) {
  curateProposal(id: $id, action: $action) {
    success
    error
    targetFile                      # what file was modified (for confirmation)
  }
}
```

## Data Model

### What the trajectory resolver reads

| Source | Path | Data extracted |
|--------|------|----------------|
| Observations | `.speed/memory/observations/{feature}.jsonl` | Count per feature, type distribution |
| Synthesis metadata | `.speed/memory/synthesis-meta.json` | Features processed, observation counts, last run time |
| Feature state | `.speed/features/*/state.json` | Completion status, dates |
| Spec traceability | `.speed/features/*/spec-traceability.json` | Coverage % per feature |
| Criteria verification | `.speed/features/*/criteria-verify.json` | First-pass rate per feature |
| Escalation logs | `.speed/features/*/logs/escalations.json` | Count per feature |
| Failure history | `.speed/memory/failure_history.jsonl` | Pipeline vs spec-complexity classification |

### What the proposals resolver reads

| Source | Path | Data extracted |
|--------|------|----------------|
| Learnings files | `.speed/memory/{agent}-learnings.json` (6 files) | Guidance entries with weight, evidence chains, category |
| Observations | `.speed/memory/observations/{feature}.jsonl` | Source observations for each proposal's evidence |
| Synthesis rejects | `.speed/memory/synthesis-rejects.json` | Previously dismissed entries (to exclude) |

### Proposal assembly

Each proposal maps from a synthesized learning entry:

1. Read all 6 `{agent}-learnings.json` files
2. Filter to entries with `weight >= 4.0` (recurrence-validated, not single-occurrence noise)
3. Exclude entries already in `synthesis-rejects.json`
4. Classify each entry into a proposal type:
   - Entries about spec structure/content → TEMPLATE (target: PRD/RFC template)
   - Entries about code patterns/conventions → CONVENTION (target: `project-knowledge.json`)
   - Entries about threshold/sensitivity → AUDIT (target: `speed.toml`)
5. Generate `changeText` from the entry's `guidance` field (the exact text to add)
6. Generate `mechanism` from the proposal type + target file
7. Attach evidence: trace back to source observations via `source_observations` IDs

### What the mutation writes

**Accept (CONVENTION)**:
```json
// Appends to .speed/memory/project-knowledge.json
{
  "id": "conv-gwt-criteria",
  "category": "spec_writing",
  "guidance": "Write acceptance criteria in Given/When/Then format...",
  "source": "learning-curation",
  "accepted_at": "2026-03-15T17:45:00Z",
  "source_learnings_entry": "dl-criteria-format"
}
```

**Accept (TEMPLATE)**:
```
// Appends guidance text to the specified template section
// File: specs/product/_template.md (or specs/tech/_template.md)
// Section: User Flows
// Appends: "For each flow, specify what happens when the primary action fails..."
```

**Accept (AUDIT)**:
```toml
# Appends/modifies rule in speed.toml
[audit.rules.design_spec_required]
trigger = "feature_scope_includes_cli_or_dashboard"
severity = "warning"
message = "Visual consistency depends on a design spec"
```

**Dismiss**:
```json
// Appends to .speed/memory/synthesis-rejects.json
{
  "learnings_entry_id": "dl-design-spec-audit",
  "dismissed_at": "2026-03-15T17:46:00Z",
  "dismissed_by": "sanjay"
}
```

### LLM portfolio narrative

**Trigger**: On page load, if LLM provider is configured.

**Input** (~3K tokens):
- Feature count and names
- Coverage trajectory (per-feature numbers)
- First-pass rate trajectory
- Escalation counts
- Failure classification counts
- Latest feature's lesson summaries

**Prompt**: "Synthesize a 2-3 paragraph portfolio narrative. Lead with the trajectory (improving, stable, or declining). Identify the main remaining gap with specific evidence. Note whether pipeline improvements are genuine or reflect easier specs. Write as direct prose, not a list."

**Degradation**: Without LLM, the narrative is null. The left panel shows trajectory metrics and per-feature lessons without the synthesized narrative. The structured data is self-sufficient.

## API Surface

### GraphQL types

```python
@strawberry.type
class TrajectoryPoint:
    feature: str
    coverage_pct: float
    first_pass_rate: float
    escalation_count: int
    rework_count: int

@strawberry.type
class FeatureLesson:
    type: str                      # "good" | "warn"
    title: str
    detail: str
    ref_marker: Optional[str]
    metric: Optional[str]

@strawberry.type
class LatestFeatureData:
    name: str
    task_count: int
    retry_count: int
    escalation_count: int
    coverage_pct: float
    criteria_pass_rate: float
    lessons: list[FeatureLesson]

@strawberry.type
class FailureClassification:
    pipeline_failures: int
    pipeline_failures_trend: str
    spec_complexity_failures: int
    spec_complexity_trend: str

@strawberry.type
class LearningTrajectoryView:
    summary: Optional[str]
    feature_count: int
    observation_count: int
    trajectory: list[TrajectoryPoint]
    latest_feature: Optional[LatestFeatureData]
    failure_classification: FailureClassification

@strawberry.type
class ProposalObservation:
    description: str
    feature: str
    weight: float
    type: str

@strawberry.type
class ProposalTrendPoint:
    feature: str
    value: str
    label: str

@strawberry.type
class ProposalEvidence:
    pattern_description: str
    observations: list[ProposalObservation]
    trend_data: list[ProposalTrendPoint]

@strawberry.type
class Proposal:
    id: str
    type: str
    title: str
    mechanism: str
    change_text: str
    ref_marker: Optional[str]
    evidence_summary: str
    evidence: ProposalEvidence
    status: str

@strawberry.type
class LearningProposalsView:
    proposals: list[Proposal]

@strawberry.input
class CurationInput:
    id: str
    action: str                    # "accept" | "dismiss"

@strawberry.type
class CurationResult:
    success: bool
    error: Optional[str]
    target_file: Optional[str]
```

## Component Architecture

```
app/learning/page.tsx
├── Left panel (420px, scrollable, subtle gradient bg)
│   ├── PortfolioHeader (title + subtitle)
│   ├── TrajectoryRows (compact: label | value | arrow | from)
│   ├── Narrative (13px, 1.8 line-height, the star)
│   ├── FeatureLessons
│   │   ├── SectionHeader (feature name + intent + aggregate)
│   │   └── LessonCard[] (good/warn, icon + body + ref-marker)
│   └── FailureClassification (two compact boxes)
│
└── Right panel (flex, scrollable)
    ├── SectionHeader ("Proposed Changes" in violet + intent + aggregate)
    └── ProposalCard[]
        ├── Top: ref-marker + type badge + title + accepted label
        ├── Mechanism (11px, secondary, with file icon)
        ├── ChangeText (violet-tinted block with left border)
        ├── EvidenceTrigger (expandable, collapsed by default)
        │   └── EvidencePanel (pattern desc + mini trend + observation rows)
        └── Buttons: Accept / Dismiss
```

## File Impact

| File | Change |
|------|--------|
| `dashboard/backend/resolvers/learning.py` | New file. Two functions: `get_trajectory()`, `get_proposals()`. Reads observations, learnings, synthesis-meta. |
| `dashboard/backend/resolvers/learning_mutation.py` | New file. `curate_proposal()` function. Writes to project-knowledge.json, templates, speed.toml, or synthesis-rejects.json. |
| `dashboard/backend/schema.py` | Add LearningTrajectoryView, LearningProposalsView types, two query fields, one mutation. Import resolvers. |
| `dashboard/frontend/lib/graphql/queries/learning.ts` | New file. LEARNING_TRAJECTORY_QUERY, LEARNING_PROPOSALS_QUERY, CURATE_PROPOSAL_MUTATION. |
| `dashboard/frontend/app/learning/page.tsx` | New file. Two-panel layout with trajectory, lessons, and proposal cards. |
| `dashboard/frontend/components/layout/sidebar.tsx` | Shared: add nav items for all 4 new pages. See Define RFC for details. |
| `dashboard/frontend/components/layout/header.tsx` | Shared: add view entries for all 4 new pages. See Define RFC for details. |

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Wider left panel (420px) | Narrative needs room | Same width as OR (340px), single column | The spec says "narrative over numbers." Prose at 13px in 340px is cramped. 420px gives comfortable line lengths for reading. |
| Two separate queries | Trajectory + Proposals split | Single combined query | The trajectory is read-heavy (stable data). The proposals are write-heavy (accept/dismiss changes status). Splitting lets the proposals query refetch after mutation without re-computing trajectory. |
| Proposal weight threshold 4.0 | Only recurrence-validated entries | Show all entries, lower threshold | The recurrence filter (2+ occurrences) already reduced noise. Weight 4.0 means the entry has substantial evidence (a retry=3.0 alone doesn't qualify; it needs corroboration). |
| Accept writes directly to target files | Immediate effect | Staging area with batch apply | The team is in a ceremony. Accept means "carry this forward now." Staging adds a second confirmation step that dilutes the curation decision. |
| Violet accent for the page | Differentiates from OR's emerald | Same accent across all pages | The ceremony is editorial (violet), not judicial (emerald). Visual distinction reinforces the different purpose. |

## Drawbacks

- **Three write targets for one mutation.** The `curate_proposal` mutation must handle `project-knowledge.json` (JSON append), template files (markdown section append), and `speed.toml` (TOML modification). Three different file formats, three different write patterns. Error handling per target is complex.
- **Template writes are fragile.** Appending guidance to a markdown template section requires parsing the template to find the section boundary. If the template format changes, the write could corrupt the file.
- **No undo for accepted proposals.** Once accepted, the change is written to the target file. Undoing requires manually editing the file. A "revert last accept" action would need to track what was written and where.
- **Observation JSONL parsing is slow for large portfolios.** With 120 observations per feature and 20 completed features, the trajectory resolver reads and parses 2,400+ JSONL lines. This should stay under 200ms but could be slow without indexing.

## Unresolved Questions

- **Proposal-to-lesson ref-marker assignment**: How are ref-markers (A, B, C) assigned? By weight (highest-weight proposal gets A)? By lesson order? The prototype uses manual assignment. The resolver needs a deterministic algorithm.
- **Template section identification**: When a TEMPLATE proposal writes guidance, how does the resolver find the target section in the template file? By section heading text match? By a marker comment in the template?
- **Concurrent writes**: If two team members accept different proposals simultaneously, the file writes could conflict. V1 assumes single-user curation. V2 needs file locking or append-only patterns.
- **Proposal refresh after accept**: After accepting a proposal, should the proposals query refetch? The accepted proposal's status changes to "accepted" in the learnings file. A refetch would update the UI. But if the team is curating 5 proposals in sequence, 5 refetches add latency.
