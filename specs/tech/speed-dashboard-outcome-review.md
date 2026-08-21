# RFC: Dashboard Outcome Review

> See [product spec](../product/speed-dashboard-outcome-review.md) for product context.
> Prototype: [outcome-review-prototype.html](../../working-docs/outcome-review-prototype.html)
> Design decisions: [surface-design-decisions.md](../../working-docs/surface-design-decisions.md)

## Basic Example

```graphql
# Query: load the review for a completed feature
query OutcomeReview($feature: String!) {
  outcomeReview(feature: $feature) {
    feature
    completedAt
    summary                    # LLM narrative (nullable if no provider)
    metrics {
      coveragePct
      criteriaPassed
      criteriaTotal
      guardianVerdict          # "approved" | "flagged" | "skipped"
      securityCritical
      securityMedium
    }
    judgmentItems {
      id
      type                     # "unverifiable" | "uncovered" | "failed"
      storyId
      criteriaIndex
      title
      description
      options                  # ["Will test manually", "Needs a test", "Blocking issue"]
      resolvedOption           # nullable (null if unresolved)
      evidence {
        criteriaText
        verificationMethod     # "test" | "schema_check" | "file_exists" | "manual" | "none"
        verificationDetail
        status                 # "passed" | "failed" | "unverifiable" | "uncovered"
      }
    }
    requirements {
      storyId
      title
      criteriaCount
      passedCount
      status                   # "all_passed" | "has_issues"
      criteria {
        text
        status
        method
        detail
      }
    }
    findings {
      type                     # "guardian" | "coherence" | "security"
      verdict                  # "pass" | "warn" | "fail"
      title
      detail
      severity                 # nullable, for security findings
    }
    verdict {
      status                   # "pending" | "approved" | "rework"
      resolvedAt               # nullable ISO string
      resolvedBy               # nullable string (git user)
    }
  }
}

# Mutation: persist judgments and verdict
mutation SubmitReview($feature: String!, $input: ReviewInput!) {
  submitReview(feature: $feature, input: $input) {
    success
    error
  }
}
```

## Data Model

### What the resolver reads

| Source | Path pattern | Data extracted |
|--------|-------------|----------------|
| Criteria verification | `.speed/features/{feature}/criteria-verify.json` | Per-criteria pass/fail/unverifiable, method, evidence text |
| Spec traceability | `.speed/features/{feature}/spec-traceability.json` | Coverage %, requirement-to-task mapping, uncovered requirements |
| Guardian logs | `.speed/features/{feature}/logs/Guardian-*.jsonl` | Last verdict entry (approved/flagged), reason, spec quote |
| Coherence logs | `.speed/features/{feature}/logs/Coherence-*.jsonl` | Last entry: consistent/inconsistent, issues list |
| Security logs | `.speed/features/{feature}/logs/Security-*.jsonl` | Findings by severity (critical/medium/low), descriptions |
| Feature state | `.speed/features/{feature}/state.json` | Status, completed_at |
| Review state | `.speed/features/{feature}/review.json` | Previous judgments (if partial save), verdict |

### What the mutation writes

**File:** `.speed/features/{feature}/review.json`

```json
{
  "feature": "speed-defects",
  "verdict": "approved",
  "resolved_at": "2026-03-15T17:30:00Z",
  "resolved_by": "sanjay",
  "judgments": [
    {
      "id": "j-s4-c2",
      "type": "unverifiable",
      "story_id": "S4",
      "criteria_index": 2,
      "title": "ISBN format validation",
      "selected_option": "Will test manually"
    },
    {
      "id": "j-s6-c1",
      "type": "uncovered",
      "story_id": "S6",
      "criteria_index": 1,
      "title": "CSV import path",
      "selected_option": "Intentional deferral"
    }
  ],
  "metadata": {
    "total_criteria": 14,
    "passed": 12,
    "coverage_pct": 94.0,
    "guardian_verdict": "approved",
    "security_critical": 0,
    "security_medium": 1
  }
}
```

This file is consumed by:
- The learning pipeline's Step 2 (review findings extraction)
- The landing page's Judge panel (verdict status)
- Future release management tools

### Judgment item assembly

Judgment items are assembled from three sources:

1. **Unverifiable criteria**: from `criteria-verify.json` where `status == "unverifiable"`
2. **Uncovered requirements**: from `spec-traceability.json` where a requirement has no task mapping
3. **Failed criteria**: from `criteria-verify.json` where `status == "failed"`

Each source produces a different set of options:

| Type | Options |
|------|---------|
| unverifiable | "Will test manually", "Needs an automated test", "Blocking issue" |
| uncovered | "Intentional deferral", "Should have been included" |
| failed | "Accept as-is", "Needs fix" |

### LLM executive summary

**Trigger**: On page load, if LLM provider is configured.

**Input** (~2K tokens):
- Feature name and completion date
- Coverage %, criteria counts
- Guardian verdict with reason
- Security findings by severity
- Judgment items (types and titles)

**Prompt**: "Write a 3-5 sentence executive summary of this feature's outcome review. Plain English. A VP reading this should understand the outcome without knowing what SPEED is. Include: coverage, criteria pass rate, what needs attention, guardian verdict, security status, recommendation."

**Output**: Narrative string stored in memory (not persisted). Regenerated on each load unless caching is implemented.

**Degradation**: Without LLM provider, the summary field is null. The page renders metrics + judgment items + findings without the narrative. The structured data is self-sufficient.

## API Surface

### GraphQL types

```python
@strawberry.type
class OutcomeMetrics:
    coverage_pct: float
    criteria_passed: int
    criteria_total: int
    guardian_verdict: str
    security_critical: int
    security_medium: int

@strawberry.type
class JudgmentEvidence:
    criteria_text: str
    verification_method: str
    verification_detail: Optional[str]
    status: str

@strawberry.type
class JudgmentItem:
    id: str
    type: str
    story_id: str
    criteria_index: Optional[int]
    title: str
    description: str
    options: list[str]
    resolved_option: Optional[str]
    evidence: list[JudgmentEvidence]

@strawberry.type
class RequirementCriteria:
    text: str
    status: str
    method: str
    detail: Optional[str]

@strawberry.type
class RequirementItem:
    story_id: str
    title: str
    criteria_count: int
    passed_count: int
    status: str
    criteria: list[RequirementCriteria]

@strawberry.type
class AutomatedFinding:
    type: str
    verdict: str
    title: str
    detail: str
    severity: Optional[str]

@strawberry.type
class ReviewVerdict:
    status: str
    resolved_at: Optional[str]
    resolved_by: Optional[str]

@strawberry.type
class OutcomeReviewView:
    feature: str
    completed_at: Optional[str]
    summary: Optional[str]
    metrics: OutcomeMetrics
    judgment_items: list[JudgmentItem]
    requirements: list[RequirementItem]
    findings: list[AutomatedFinding]
    verdict: ReviewVerdict

# Mutation input
@strawberry.input
class JudgmentInput:
    id: str
    selected_option: str

@strawberry.input
class ReviewInput:
    verdict: str
    judgments: list[JudgmentInput]

@strawberry.type
class ReviewResult:
    success: bool
    error: Optional[str]
```

### Query and mutation fields

```python
@strawberry.field
def outcome_review(self, info: strawberry.types.Info, feature: str) -> Optional[OutcomeReviewView]:
    project_root = info.context["project_root"]
    return outcome_review_resolver.get_outcome_review(project_root, feature)

@strawberry.mutation
def submit_review(self, info: strawberry.types.Info, feature: str, input: ReviewInput) -> ReviewResult:
    project_root = info.context["project_root"]
    return outcome_review_resolver.submit_review(project_root, feature, input)
```

## Component Architecture

```
app/outcome-review/page.tsx
├── Left panel (340px, persistent)
│   ├── FeatureIdentity (name + status)
│   ├── OutcomeMetrics (2x1 grid: coverage, criteria)
│   ├── ExecutiveSummary (12px narrative, scrollable)
│   ├── AutomatedFindings (compact indicator rows)
│   ├── JudgmentProgress ("N of M resolved")
│   └── VerdictAction (pinned bottom: Approve / Rework)
│
└── Right panel (flex, scrollable)
    ├── SectionHeader ("Judgments" + intent + aggregate)
    ├── JudgmentCard[] (expanded: badge + title + desc + options + evidence trigger)
    │   └── InlineEvidence (expandable per card)
    ├── SectionHeader ("Full Requirements" + intent + aggregate)
    └── RequirementItem[] (caret + id + title + status, expandable criteria)
```

### Client state

Judgment resolution state is managed in React component state (not server state) until the user clicks Approve:

```typescript
const [resolutions, setResolutions] = useState<Record<string, string>>({});
// key: judgment item id, value: selected option text

const allResolved = judgmentItems.every(item => resolutions[item.id]);
```

On Approve click, the mutation sends all resolutions. On success, the page refetches to show the post-approval state.

## File Impact

| File | Change |
|------|--------|
| `dashboard/backend/resolvers/outcome_review.py` | New file. Reads verification artifacts, assembles judgment items, calls LLM for summary. |
| `dashboard/backend/schema.py` | Add OutcomeReviewView types, query field, mutation. Import resolver. Add Mutation class to schema. |
| `dashboard/frontend/lib/graphql/queries/outcome-review.ts` | New file. OUTCOME_REVIEW_QUERY, SUBMIT_REVIEW_MUTATION. |
| `dashboard/frontend/app/outcome-review/page.tsx` | New file. Two-panel layout with judgment cards and evidence. |
| `dashboard/frontend/components/layout/sidebar.tsx` | Shared: add nav items for all 4 new pages. See Define RFC for details. |
| `dashboard/frontend/components/layout/header.tsx` | Shared: add view entries for all 4 new pages. See Define RFC for details. |

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Two-panel layout | Left: persistent context. Right: work area. | Single column (shareable doc), three-panel | The team needs the aggregate outcome visible while judging individual items. Single column loses persistent context. |
| Client-side resolution state | useState until Approve | Server-side partial save | Simplifies implementation. The ceremony is short (2-5 items). Partial save adds complexity for minimal benefit. |
| Judgment cards carry inline evidence | Evidence expands inside each card | Separate evidence section with cross-references | Eliminates scrolling between sections. The evidence for a judgment is one click away, right where you need it. |
| Natural collapse post-approval | Resolved cards collapse, no mode switch | Separate "artifact" rendering | The resolved state IS the artifact. No dual rendering needed. |
| Summary regenerated on load | Not cached | Cached per verification run | Ensures summary reflects latest data. Cost is ~$0.01 per load. Cache invalidation is complex (what triggers refresh?). |

## Drawbacks

- **No partial save.** If the user closes the page mid-ceremony, judgments are lost. For V1 with 2-5 items, this is acceptable. For features with 10+ judgment items, partial save becomes important.
- **LLM cost per load.** The executive summary costs ~$0.01 every page load. With 10 loads per review (the team discusses, refreshes, etc.), that's $0.10. Caching would eliminate repeat calls.
- **No multi-reviewer support.** V1 assumes one team approves together. No concept of individual reviewer approval or quorum. The mutation records one `resolved_by` user.
- **Mutation creates the schema for `review.json`.** This is a new file format that the learning pipeline's Step 2 must learn to consume. Coordination required.

## Unresolved Questions

- **LLM provider detection**: How does the resolver know if the LLM provider is configured? Check for environment variable? Try a call and catch failure? The existing dashboard resolvers don't make LLM calls.
- **Rework re-execution**: When "Request Rework" is clicked, the mutation writes the rework annotations. But what triggers re-execution? Does the PM run `speed run` again? Does the dashboard show a "re-run" button? The handoff between dashboard and CLI is undefined.
- **Review.json versioning**: If the team re-opens a completed review and changes a judgment, should it create a new version or overwrite? Overwrite is simpler but loses the audit trail of the original judgment.
