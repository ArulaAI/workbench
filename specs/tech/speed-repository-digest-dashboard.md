# RFC: Repository Digest

> See [Repository Digest PRD](../product/speed-repository-digest.md) for product context.
> Depends on the existing Layer 1 project map and Codebase Semantic Graph artifacts, dashboard GraphQL API, and project knowledge pipeline.

## Basic Example

After SPEED indexes an unfamiliar target repository, it writes a repository-scoped artifact at `.speed/context/repository-digest.json`. The dashboard reads that artifact without scanning source files or invoking an LLM.

```graphql
query RepositoryDigest {
  repositoryDigest {
    schemaVersion
    status
    freshness {
      state
      indexedGitHead
      currentGitHead
      generatedAt
      staleReasons
    }
    identity {
      name
      summary
      confidence
      evidence { source path line description }
    }
    footprint {
      fileCount
      lineCount
      symbolCount
      domainCount
      languages { name files lines percent }
    }
    domains(limit: 10) {
      id
      label
      summary
      confidence
      fileCount
      symbolCount
      representativeFiles
      dependsOn
      usedBy
      evidence { source path symbol description }
    }
    commands {
      purpose
      command
      workingDirectory
      confidence
      evidence { source path line description }
    }
    hotspots(limit: 10) {
      symbolId
      name
      file
      line
      reason
      blastRadius
      dependents
    }
    readiness {
      capability
      status
      reason
      remediation
    }
  }
}
```

Example response for a Rails and React commerce repository:

```json
{
  "data": {
    "repositoryDigest": {
      "schemaVersion": 1,
      "status": "PARTIAL",
      "freshness": {
        "state": "CURRENT",
        "indexedGitHead": "8ca21d4e12f3",
        "currentGitHead": "8ca21d4e12f3",
        "generatedAt": "2026-08-26T18:42:11Z",
        "staleReasons": []
      },
      "identity": {
        "name": "acme-storefront",
        "summary": "Multi-tenant commerce platform with a Rails API, Sidekiq workers, and a React administration client.",
        "confidence": "DERIVED",
        "evidence": [
          {
            "source": "DOCUMENTATION",
            "path": "README.md",
            "line": 3,
            "description": "Repository overview"
          },
          {
            "source": "MANIFEST",
            "path": "Gemfile",
            "line": 12,
            "description": "Rails dependency"
          }
        ]
      },
      "footprint": {
        "fileCount": 1042,
        "lineCount": 138420,
        "symbolCount": 3816,
        "domainCount": 7,
        "languages": [
          { "name": "Ruby", "files": 684, "lines": 91806, "percent": 66.32 },
          { "name": "TypeScript", "files": 241, "lines": 37912, "percent": 27.39 }
        ]
      },
      "domains": [
        {
          "id": "cluster-orders",
          "label": "Orders",
          "summary": "Cart conversion, order state transitions, totals, refunds, and cancellation.",
          "confidence": "DERIVED",
          "fileCount": 46,
          "symbolCount": 312,
          "representativeFiles": [
            "app/models/order.rb",
            "app/services/orders/checkout.rb"
          ],
          "dependsOn": ["cluster-catalog", "cluster-payments"],
          "usedBy": ["cluster-admin", "cluster-fulfillment"],
          "evidence": [
            {
              "source": "SEMANTIC_GRAPH",
              "path": "app/models/order.rb",
              "symbol": "Order",
              "description": "High-centrality representative symbol"
            }
          ]
        }
      ],
      "commands": [
        {
          "purpose": "TEST",
          "command": "bundle exec rspec",
          "workingDirectory": ".",
          "confidence": "CONFIRMED",
          "evidence": [
            {
              "source": "PROJECT_INSTRUCTIONS",
              "path": "CLAUDE.md",
              "line": 41,
              "description": "Documented test command"
            }
          ]
        }
      ],
      "hotspots": [
        {
          "symbolId": "ruby:app/models/order.rb:Order#recalculate!",
          "name": "Order#recalculate!",
          "file": "app/models/order.rb",
          "line": 184,
          "reason": "Used by checkout, discounts, refunds, and admin edits",
          "blastRadius": 47,
          "dependents": 19
        }
      ],
      "readiness": [
        {
          "capability": "PROJECT_MAP",
          "status": "AVAILABLE",
          "reason": null,
          "remediation": null
        },
        {
          "capability": "SPEC_ALIGNMENT",
          "status": "UNAVAILABLE",
          "reason": "No specification alignment artifact was found",
          "remediation": "Add product specifications and run SPEED validation"
        }
      ]
    }
  }
}
```

The same repository with only a project map still returns useful data:

```json
{
  "status": "PARTIAL",
  "footprint": {
    "file_count": 1042,
    "line_count": 138420,
    "symbol_count": null,
    "domain_count": null
  },
  "domains": [],
  "hotspots": [],
  "readiness": [
    { "capability": "project_map", "status": "available" },
    {
      "capability": "semantic_graph",
      "status": "unavailable",
      "reason": "semantic-graph.json does not exist",
      "remediation": "Run the Layer 1 context build"
    }
  ]
}
```

## Interface Contract

This RFC is a standalone vertical design. Its builder consumes existing repository discovery artifacts and produces one versioned artifact consumed by the API, dashboard, and optional agent-context assembly.

### Consumes

```python
# Existing artifacts, all relative to the target project.
.speed/context/project-map.json
.speed/context/semantic-graph.json             # optional
.speed/context/spec-alignment.json              # optional
.speed/context/skeletons/                       # optional
.speed/memory/conventions.json                  # optional
.speed/memory/project-knowledge.json            # optional
.speed/memory/project-knowledge-drafts.json     # readiness only
.speed/memory/observations/*.jsonl              # optional

# Repository sources selected through bounded, denylisted loaders.
README.md | README | readme.md                   # optional
CLAUDE.md | AGENTS.md | CONTRIBUTING.md          # optional
package.json | pyproject.toml | Cargo.toml | ... # optional
speed.toml                                       # configuration fingerprint
```

The minimum valid input is a structurally valid `project-map.json`. No other artifact is required.

### Produces

```python
from pathlib import Path
from typing import Any

def build_repository_digest(
    project_root: Path,
    *,
    config: dict[str, Any] | None = None,
    narrative: bool = False,
) -> dict[str, Any]:
    """Build and atomically persist repository-digest.json.

    Raises DigestInputError only when the required project map is absent or
    invalid. Optional-source failures are represented in readiness records.
    """


def load_repository_digest(project_root: Path) -> dict[str, Any] | None:
    """Return a validated stored digest, or None when absent or malformed."""


def compute_digest_freshness(
    project_root: Path,
    digest: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare stored fingerprint inputs with current repository state."""


def project_digest_for_agent(
    digest: dict[str, Any],
    *,
    token_budget: int,
) -> str:
    """Produce deterministic Markdown context within token_budget."""
```

Primary artifact:

```text
.speed/context/repository-digest.json
```

The builder must write to a temporary file in `.speed/context/`, flush it, and replace the destination atomically. It must never truncate the last valid digest before the replacement is complete.

## Data Model

The digest is a JSON artifact, not a database table. SQLite ingestion is unnecessary because reads are repository-local, the artifact is replaced as a unit, and no historical aggregation is required in this phase.

### Top-level `RepositoryDigest`

| Field | JSON type | Required | Constraints and meaning |
|-------|-----------|----------|-------------------------|
| `schema_version` | integer | Yes | Exactly `1` for this RFC. Consumers reject unsupported versions. |
| `status` | string enum | Yes | `complete`, `partial`, or `failed`. A successfully stored artifact is normally complete or partial. |
| `generated_at` | string | Yes | UTC ISO 8601 timestamp ending in `Z`. |
| `generator` | object | Yes | Builder name and implementation version. |
| `fingerprint` | object | Yes | Inputs used for freshness calculation. |
| `identity` | object | Yes | Repository name, purpose summary, confidence, evidence. Summary may be empty. |
| `footprint` | object | Yes | Deterministic counts from the project map and optional CSG. |
| `domains` | array | Yes | Ranked semantic domains; empty when unavailable. |
| `relationships` | array | Yes | Ranked cross-domain directed edges; empty when unavailable. |
| `entrypoints` | array | Yes | Runtime or structural entrypoints; empty when unavailable. |
| `commands` | array | Yes | Discovered commands; empty when unavailable. |
| `hotspots` | array | Yes | Ranked high-impact symbols; empty when unavailable. |
| `conventions` | array | Yes | Approved conventions only; empty when unavailable. |
| `risks` | array | Yes | Evidence-backed structural or historical risk signals. |
| `gaps` | array | Yes | Explicit unknowns and ambiguous discoveries. |
| `readiness` | array | Yes | One record per known discovery capability. |
| `warnings` | array | Yes | Non-fatal builder warnings safe for user display. |

### Canonical JSON example

```json
{
  "schema_version": 1,
  "status": "complete",
  "generated_at": "2026-08-26T18:42:11Z",
  "generator": {
    "name": "speed-repository-digest",
    "version": "1"
  },
  "fingerprint": {
    "git_head": "8ca21d4e12f3e50a3dd0",
    "discovery_config_sha256": "sha256:0c48d3...",
    "project_map_sha256": "sha256:91aad7...",
    "semantic_graph_sha256": "sha256:5fc410...",
    "knowledge_sha256": "sha256:a2240f...",
    "schema_version": 1
  },
  "identity": {
    "name": "acme-storefront",
    "summary": "Multi-tenant commerce platform with a Rails API and React administration client.",
    "confidence": "derived",
    "evidence": [
      {
        "source": "documentation",
        "path": "README.md",
        "line": 3,
        "symbol": null,
        "artifact_key": null,
        "description": "Repository overview"
      }
    ]
  },
  "footprint": {
    "file_count": 1042,
    "line_count": 138420,
    "source_file_count": 925,
    "config_file_count": 64,
    "asset_file_count": 53,
    "symbol_count": 3816,
    "domain_count": 7,
    "cross_domain_relationship_count": 24,
    "languages": [
      { "name": "Ruby", "files": 684, "lines": 91806, "percent": 66.32 }
    ]
  },
  "domains": [],
  "relationships": [],
  "entrypoints": [],
  "commands": [],
  "hotspots": [],
  "conventions": [],
  "risks": [],
  "gaps": [],
  "readiness": [],
  "warnings": []
}
```

### `EvidenceRef`

Every interpretive claim and every command must include evidence. Pure aggregate values may cite the relevant artifact key rather than a line.

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `source` | enum | Yes | `project_map`, `semantic_graph`, `documentation`, `manifest`, `project_instructions`, `convention`, `project_knowledge`, `observation`, or `spec_alignment` |
| `path` | string or null | No | Normalized repository-relative path; never absolute and never containing `..` segments |
| `line` | integer or null | No | One-based source line when known |
| `symbol` | string or null | No | CSG symbol ID or display name |
| `artifact_key` | string or null | No | JSON pointer-like location such as `/summary/languages/Ruby` |
| `description` | string | Yes | Short explanation of what the evidence supports |

At least one of `path`, `symbol`, or `artifact_key` must be non-null.

### Confidence

| Value | Use |
|-------|-----|
| `confirmed` | Explicitly stated in project-owned documentation or configuration, or exactly measured from an artifact |
| `derived` | Deterministically computed from multiple confirmed signals, such as a domain relationship from CSG edges |
| `inferred` | Selected by bounded narrative synthesis or a heuristic that can plausibly be wrong |
| `unknown` | The system has insufficient or contradictory evidence |

Confidence is attached to claims, not entire sections. A domain's file count can be confirmed while its human-readable purpose remains inferred.

### `DomainDigest`

| Field | Type | Constraints |
|-------|------|-------------|
| `id` | string | Stable CSG cluster ID |
| `label` | string | 1 to 80 characters; fallback is `Unlabeled domain <short-id>` |
| `summary` | string | Maximum 400 characters; may be empty |
| `confidence` | confidence enum | Confidence in label and summary |
| `file_count` | integer | Non-negative |
| `symbol_count` | integer | Non-negative |
| `cohesion` | number or null | Existing CSG metric; no digest-specific recomputation |
| `avg_blast_radius` | number | Non-negative |
| `representative_files` | string[] | Maximum 5 in stored default projection |
| `representative_symbols` | string[] | Maximum 5 |
| `depends_on` | string[] | Domain IDs with outgoing cross-domain edges |
| `used_by` | string[] | Domain IDs with incoming cross-domain edges |
| `evidence` | `EvidenceRef[]` | At least one reference |

Domain ranking score is deterministic:

```text
rank_score =
    0.35 * normalized(symbol_count)
  + 0.25 * normalized(file_count)
  + 0.25 * normalized(cross_domain_degree)
  + 0.15 * normalized(avg_blast_radius)
```

Ties sort by `id`. Normalization uses the maximum value among current domains; an all-zero dimension contributes zero. Ranking affects presentation only and is stored as `rank` plus `rank_score` for reproducibility.

### `CommandDigest`

| Field | Type | Constraints |
|-------|------|-------------|
| `purpose` | enum | `run`, `develop`, `build`, `test`, `lint`, `typecheck`, `format`, `migrate`, `worker`, or `other` |
| `command` | string | Stored verbatim from a supported source, maximum 500 characters; never executed by the digest builder |
| `working_directory` | string | Repository-relative; `.` means root |
| `confidence` | confidence enum | Manifest scripts and explicit instructions are confirmed; conventional guesses are not allowed in v1 |
| `evidence` | `EvidenceRef[]` | Must identify manifest or instruction source |

When two sources declare the same normalized command and working directory, merge their evidence. When they conflict, retain both records and create a gap with type `conflicting_commands`.

### `HotspotDigest`

| Field | Type | Constraints |
|-------|------|-------------|
| `symbol_id` | string | Existing CSG node ID |
| `name` | string | Existing symbol display name |
| `file` | string | Repository-relative path |
| `line` | integer | One-based line, or `0` only if absent in the CSG |
| `domain_id` | string | Owning cluster ID |
| `blast_radius` | integer | Existing impact metric |
| `dependents` | integer | Existing impact metric |
| `centrality` | number | Existing impact metric |
| `reason` | string | Deterministic template based on metrics and cross-domain use |
| `evidence` | `EvidenceRef[]` | CSG symbol reference |

Hotspots sort by blast radius descending, dependents descending, centrality descending, then symbol ID. The digest must not invent coverage claims because coverage discovery is outside this RFC.

### `ConventionDigest`

| Field | Type | Constraints |
|-------|------|-------------|
| `text` | string | The convention statement, verbatim from `conventions.json` |
| `scope` | string[] | File paths or directory globs the convention applies to |
| `confidence` | confidence enum | `confirmed` for config-derived entries, `derived` for discovered entries — see Conventions, below |
| `evidence` | `EvidenceRef[]` | At least one reference, `source: convention` |

### `GapDigest`

| Field | Type | Constraints |
|-------|------|-------------|
| `type` | string | Stable identifier: `purpose_not_discovered`, `domain_label_unresolved`, or `conflicting_commands` — see Gaps, below |
| `description` | string | Human-readable explanation of what's ambiguous or unknown |
| `evidence` | `EvidenceRef[]` | May be empty when the gap is an absence of evidence rather than a conflict between sources |

### `ReadinessRecord`

Known capabilities are `project_map`, `semantic_graph`, `documentation`, `manifests`, `project_instructions`, `conventions`, `project_knowledge`, `observations`, and `spec_alignment`.

| Field | Type | Meaning |
|-------|------|---------|
| `capability` | enum | Capability identifier |
| `status` | enum | `available`, `partial`, `unavailable`, `invalid`, or `stale` |
| `reason` | string or null | User-readable cause |
| `remediation` | string or null | Safe action or command description; never automatically executed |
| `source_path` | string or null | Expected or actual artifact path |

### Fingerprint

The freshness fingerprint includes inputs that can change conclusions:

```python
@dataclass(frozen=True)
class DigestFingerprint:
    git_head: str | None
    discovery_config_sha256: str
    project_map_sha256: str
    semantic_graph_sha256: str | None
    knowledge_sha256: str | None
    schema_version: int
```

`discovery_config_sha256` hashes a canonical JSON projection of only discovery-relevant configuration: scope, ignore patterns, categories, language extraction configuration, and digest configuration. It does not hash unrelated agent models, ports, UI theme, or verbosity.

`knowledge_sha256` hashes the canonical content of approved conventions and project knowledge. Draft knowledge is excluded from the hash because it cannot affect authoritative digest claims; its count may affect readiness and therefore is computed at query time.

## State Machine

The persisted digest has no mutable workflow record. Its effective state is derived from artifact presence, validity, build status, and fingerprint comparison.

```text
                    no artifact
                        │
                        ▼
                     MISSING
                        │ refresh
                        ▼
                    GENERATING
                   /          \
          successful            failed
             write                build
             /  \                  │
            ▼    ▼                 ▼
       COMPLETE PARTIAL          ERROR
            │      │               │
            └──┬───┘               │
      fingerprint mismatch         │
               ▼                   │
              STALE ◀───────────────
       (last valid digest remains)
```

| Current state | Trigger | Next state | Side effect |
|---------------|---------|------------|-------------|
| `missing` | Refresh requested | `generating` | Start builder; no readable artifact yet |
| `generating` | All configured inputs processed | `complete` | Atomically write complete artifact |
| `generating` | Required project map valid; optional input absent or invalid | `partial` | Atomically write artifact with readiness and warnings |
| `generating` | Required project map absent or invalid | `error` | Preserve old artifact if one exists; write build-status error only |
| `complete` or `partial` | Fingerprint component differs | `stale` | Keep artifact readable and list stale reasons |
| `stale` | Refresh succeeds | `complete` or `partial` | Atomically replace old artifact |
| `stale` | Refresh fails | `stale` | Preserve old artifact and expose last refresh error |

`failed` is a valid JSON schema value for diagnostic serialization but is not written over a previously valid digest. The API represents generation failure separately through `buildStatus`.

## API Surface

### GraphQL enums

```graphql
enum DigestStatus {
  COMPLETE
  PARTIAL
  FAILED
}

enum DigestEffectiveState {
  MISSING
  GENERATING
  CURRENT
  STALE
  ERROR
}

enum DigestConfidence {
  CONFIRMED
  DERIVED
  INFERRED
  UNKNOWN
}

enum DigestCapabilityStatus {
  AVAILABLE
  PARTIAL
  UNAVAILABLE
  INVALID
  STALE
}

enum DigestCommandPurpose {
  RUN
  DEVELOP
  BUILD
  TEST
  LINT
  TYPECHECK
  FORMAT
  MIGRATE
  WORKER
  OTHER
}
```

### Query: `repositoryDigest`

```graphql
type Query {
  repositoryDigest: RepositoryDigest
}
```

Returns `null` only when no valid stored artifact exists. The query performs bounded reads of the digest, current git HEAD, relevant configuration, and approved knowledge files to calculate freshness. It must not rebuild discovery, walk the repository, invoke an agent provider, or execute a discovered command.

```graphql
type RepositoryDigest {
  schemaVersion: Int!
  status: DigestStatus!
  effectiveState: DigestEffectiveState!
  generatedAt: String!
  freshness: DigestFreshness!
  identity: DigestIdentity!
  footprint: DigestFootprint!
  domains(limit: Int = 10): [DigestDomain!]!
  relationships(limit: Int = 30): [DigestRelationship!]!
  entrypoints(limit: Int = 10): [DigestEntrypoint!]!
  commands: [DigestCommand!]!
  hotspots(limit: Int = 10): [DigestHotspot!]!
  conventions(limit: Int = 10): [DigestConvention!]!
  risks(limit: Int = 10): [DigestRisk!]!
  gaps: [DigestGap!]!
  readiness: [DigestReadiness!]!
  warnings: [String!]!
}
```

Limits must be between 1 and 100. Invalid limits produce a GraphQL validation error with the field and accepted range. The resolver slices already-ranked stored arrays; it does not recompute ranking.

### Query: `repositoryDigestStatus`

```graphql
type Query {
  repositoryDigestStatus: RepositoryDigestBuildStatus!
}

type RepositoryDigestBuildStatus {
  state: DigestEffectiveState!
  startedAt: String
  completedAt: String
  lastError: String
  hasReadableDigest: Boolean!
  indexedGitHead: String
  currentGitHead: String
  staleReasons: [String!]!
}
```

The lightweight status query supports polling during a refresh. A refresh error must be sanitized for display and must not contain provider prompts, secret values, absolute home paths, or stack traces.

### Mutation: `refreshRepositoryDigest`

```graphql
type Mutation {
  refreshRepositoryDigest(
    rebuildDiscovery: Boolean! = false
    narrative: Boolean! = false
  ): RepositoryDigestRefreshResult!
}

type RepositoryDigestRefreshResult {
  accepted: Boolean!
  state: DigestEffectiveState!
  message: String!
  hasReadableDigest: Boolean!
}
```

Behavior:

1. Acquire a repository-scoped digest build lock.
2. If a build is running, return `accepted: false`, state `GENERATING`, and do not start another process.
3. If `rebuildDiscovery` is false, require an existing valid project map and build from available artifacts.
4. If `rebuildDiscovery` is true, invoke the existing Layer 1 builder before digest generation. Do not implement a separate scanner.
5. Start work in the existing dashboard background-execution mechanism and return immediately.
6. Persist build status outside `repository-digest.json`, for example `.speed/context/repository-digest-status.json`.
7. On success, atomically replace the digest and update status.
8. On failure, retain the last valid digest and record a sanitized error.

Authorization follows the dashboard's existing local-project mutation policy. If remote or multi-user dashboard authentication is later introduced, refresh requires project-write permission; read queries require project-read permission.

### Subscription: `repositoryDigestUpdated`

```graphql
type Subscription {
  repositoryDigestUpdated: RepositoryDigestBuildStatus!
}
```

Emit on `GENERATING`, successful completion, and failure. The frontend may poll if subscriptions are unavailable. The event contains status only, not the full digest.

### Optional CLI surface

```text
speed digest [--refresh] [--rebuild-discovery] [--json]
```

- With no flags, print the current digest in bounded Markdown or report that none exists.
- `--refresh` builds from current discovery artifacts.
- `--rebuild-discovery` implies `--refresh` and invokes Layer 1 first.
- `--json` emits the stored JSON to stdout and sends progress logs to stderr.
- Exit `0` for complete or partial success, `3` for missing/invalid required discovery input, and the existing provider error code if optional narrative synthesis was explicitly requested and failed without a deterministic fallback.

The CLI is a Should-level deliverable. The dashboard and artifact contract do not depend on it.

## Validation Rules

| Field or behavior | Constraints |
|-------------------|-------------|
| Project root | Must resolve to the dashboard's configured target root; never accepted as a client-supplied path |
| Required project map | Must be a JSON object with a files array and summary object; malformed or absent input prevents a new digest write |
| Repository-relative paths | Must be normalized, must not be absolute, and must not contain a `..` path component |
| `schema_version` | Must equal `1`; unsupported versions return no digest plus an invalid status reason |
| Timestamps | Must parse as timezone-aware ISO 8601 and serialize in UTC with `Z` |
| Confidence | Must be one of the four defined values; unknown input values normalize to `unknown` with a warning |
| Evidence | Every identity summary, domain narrative, command, convention, and risk requires at least one valid evidence reference |
| Summary length | Identity summary maximum 600 characters; domain summary maximum 400; risk and gap descriptions maximum 500 |
| Arrays | Stored domains maximum 100, hotspots maximum 100, risks maximum 100; builder records a warning when truncation occurs |
| Counts | Must be integers greater than or equal to zero; unavailable optional counts are `null`, never `0` |
| Percentages | Rounded to two decimals; sum may vary from 100 by at most 0.05 due to rounding |
| Commands | Maximum 500 characters; must not contain NUL; never executed or interpolated into a shell by digest code |
| Domain references | `depends_on` and `used_by` IDs must refer to stored domains; invalid references are dropped with a warning |
| Hotspot references | Must resolve to a CSG node from the same semantic graph fingerprint |
| Approved knowledge | Only accepted or committed conventions and project-knowledge entries may appear as guidance |
| Draft knowledge | May affect readiness counts only; content must not appear in authoritative sections |
| Narrative disabled | Builder uses deterministic summaries or empty summaries and never calls an agent provider |
| Narrative failure | Builder falls back to deterministic output and records a warning unless the caller explicitly requires narrative-only behavior, which v1 does not expose |
| Refresh concurrency | At most one build per target repository; duplicate requests return current generating status |

### Evidence validation example

Rejected:

```json
{
  "summary": "Payments are routed through Stripe.",
  "confidence": "confirmed",
  "evidence": []
}
```

Accepted:

```json
{
  "summary": "The repository declares the Stripe SDK and routes payment operations through Payments::StripeGateway.",
  "confidence": "derived",
  "evidence": [
    {
      "source": "manifest",
      "path": "Gemfile",
      "line": 42,
      "description": "Stripe SDK dependency"
    },
    {
      "source": "semantic_graph",
      "path": "app/services/payments/stripe_gateway.rb",
      "symbol": "Payments::StripeGateway",
      "description": "Payment gateway implementation"
    }
  ]
}
```

## Builder Design

### Pipeline

```text
resolve target paths
        │
        ▼
load and validate project map ──invalid──▶ abort, preserve prior digest
        │
        ▼
load optional discovery inputs independently
        │
        ├── missing/invalid ──▶ readiness record + warning
        ▼
derive deterministic facts
        │
        ├── footprint
        ├── domains and relationships
        ├── entrypoints and hotspots
        ├── commands
        ├── conventions and risks
        ├── gaps and readiness
        │
        ▼
optional bounded narrative synthesis
        │ failure
        ├──────────────▶ deterministic fallback + warning
        ▼
validate complete output
        │
        ▼
atomic write repository-digest.json
```

### Input isolation

Each optional loader returns an `InputResult[T]` rather than throwing through the pipeline:

```python
@dataclass
class InputResult(Generic[T]):
    capability: str
    status: Literal["available", "partial", "unavailable", "invalid", "stale"]
    value: T | None
    reason: str | None
    warnings: list[str]
    source_path: str | None
```

Example: malformed conventions must not erase valid semantic domains.

```python
project_map = InputResult(status="available", value={...})
csg = InputResult(status="available", value={...})
conventions = InputResult(
    status="invalid",
    value=None,
    reason="conventions.json is not valid JSON",
    warnings=[],
    source_path=".speed/memory/conventions.json",
)
```

The output becomes `partial`, domains remain populated, conventions remain empty, and readiness explains the invalid optional input.

### Repository identity

Repository name selection order:

1. Existing dashboard project registration name, when available to the caller.
2. Name field from a root manifest (`package.json`, `pyproject.toml`, `Cargo.toml`, and registered equivalents).
3. Git remote repository basename.
4. Target root directory basename.

Purpose evidence candidates, in priority order:

1. Product vision configured by `specs.vision_file`.
2. README title and first non-badge prose paragraph.
3. Root manifest description.
4. No purpose statement.

Deterministic mode selects and lightly normalizes the highest-priority statement. It does not combine unrelated paragraphs. Narrative mode may synthesize a maximum two-sentence summary from at most 12 evidence records and must return selected evidence IDs.

If a README says "Build status" followed by badges and then "Acme is a multi-tenant commerce platform," badge-only lines are skipped. If the README contains only installation instructions, identity summary remains empty and the digest adds `purpose_not_discovered` to gaps.

### Domains

The CSG remains authoritative for membership and edges. Digest generation does not recluster symbols.

For each cluster:

1. Read cluster ID, files, symbols, cohesion, and graph edges.
2. Select representative symbols by centrality, then blast radius, then symbol ID.
3. Select representative files by number of representative symbols, then symbol count, then path.
4. Prefer an existing cluster label if Layer 1 provides one.
5. Otherwise derive a label from the longest common meaningful directory or namespace term among representative files and symbols.
6. If no term has support from at least 30% of cluster files or three files, whichever is smaller, use `Unlabeled domain <short-id>` with confidence `unknown`.
7. Build `depends_on` and `used_by` from cross-cluster CSG edges.

Label derivation example:

```text
Representative paths:
  app/services/orders/checkout.rb
  app/models/order.rb
  app/graphql/mutations/create_order.rb

Tokens after stopword removal:
  orders: 2 paths
  order: 2 symbols/paths
  checkout: 1 path

Normalized label: Orders
Confidence: derived
Evidence: three representative paths and their cluster membership
```

Counterexample:

```text
src/util.py
src/common.py
src/helpers.py

No meaningful term clears the support threshold.
Label: Unlabeled domain c-17a2
Confidence: unknown
Gap: domain_label_unresolved
```

### Commands

Command extraction must use a registry so other discovery consumers can reuse it. The digest consumes normalized records from that registry.

Initial supported sources:

| Source | Examples |
|--------|----------|
| Project instructions | Commands under test, lint, typecheck, build, run, or development headings in `CLAUDE.md` or `AGENTS.md` |
| `package.json` | `scripts` entries; workspace working directory retained |
| `pyproject.toml` | Registered tool scripts and documented task-runner entries |
| `Makefile` | Named targets only; display as `make <target>` without executing recipes |
| `Cargo.toml` | Package metadata plus explicit repository instructions; do not guess `cargo test` solely because Cargo exists |
| `Procfile` variants | Process name and command, such as web or worker |
| CI workflow | Commands may corroborate a command but are not promoted alone when they require CI-only environment setup |

Conflict example:

```text
CLAUDE.md:       npm test
package.json:    "test": "vitest run"
CI workflow:     npm run test:ci
```

The digest returns all three with their exact purpose and evidence. It does not decide that one supersedes the others. A `conflicting_commands` gap explains the difference if multiple root-level commands claim the same purpose.

### Conventions

Reads `.speed/memory/conventions.json` (optional; absence produces an empty `conventions` array and a `conventions` readiness record of `unavailable`, not an error). Only entries the convention pipeline has already accepted are included — drafts and rejected candidates never appear, per the Validation Rules requirement that "only accepted or committed conventions... may appear as guidance." Each accepted entry maps to one `ConventionDigest`: `text` and `scope` pass through unchanged from the source entry, `confidence` is derived from the entry's own `source` field (`config` → `confirmed`, `discovered` → `derived`), and `evidence` cites the convention's canonical example with `source: convention`.

### Risks

V1 risk records are evidence-backed signals, not generalized code-quality judgments:

- `high_blast_radius`: symbol is within the top 1% by blast radius and has at least 10 dependents.
- `cross_domain_hub`: symbol has edges touching at least three domains.
- `repeated_failure`: at least three qualifying observations share a normalized failure key and scope.
- `stale_knowledge`: an approved knowledge entry is past its staleness threshold or explicitly flagged.
- `conflicting_discovery`: two authoritative sources disagree about the same command or purpose statement.

The digest must not claim "weak test coverage," "poor quality," "security vulnerability," or "high churn" without a discovery artifact designed to substantiate that claim.

### Gaps

Gaps aren't produced by a dedicated detector — the `gaps` array is a collection point. Each earlier pipeline stage that hits an ambiguity it can't resolve emits a `GapDigest` instead of silently guessing: repository identity emits `purpose_not_discovered` when no purpose statement clears the evidence bar (see Repository identity), domain labeling emits `domain_label_unresolved` when no term clears the support threshold (see Domains), and command extraction emits `conflicting_commands` when multiple root-level commands claim the same purpose (see Commands). The builder aggregates whatever each stage produced; there is no additional gap-detection logic beyond what those three sections already describe.

### Agent projection

`project_digest_for_agent()` renders a bounded Markdown projection of the already-stored digest — it never triggers a fresh build. Content is added in a fixed priority order until the token budget is exhausted: identity, then freshness, then readiness gaps, then domains ranked highest-first per the Domains ranking score, truncating an individual domain's detail before dropping it outright. At the smallest budgets, even the required header can exceed what's available — in that case the projection returns a short truncation notice instead of overrunning the budget (see Edge Cases). At larger budgets, the projection includes progressively more ranked domains until either the budget or the full domain list is exhausted, whichever comes first. Which global agent stages call this function, and at what budget, is still open (Unresolved Question 6); this section specifies the function's own deterministic behavior independent of who calls it.

### Narrative synthesis

Narrative synthesis is optional and disabled by default in v1. When enabled:

- Input contains only normalized evidence records, never arbitrary full repository files.
- Maximum input is 12,000 estimated tokens.
- Output must conform to a JSON schema containing text plus evidence IDs.
- Identity summary is at most 600 characters; each domain summary is at most 400.
- Any returned evidence ID not present in the input invalidates that claim.
- Provider failure, timeout, invalid JSON, or invalid evidence IDs triggers deterministic fallback.
- Synthesized text always has confidence `inferred` unless it restates one explicit source without combination.

Example input:

```json
{
  "claim": "repository_identity",
  "evidence": [
    { "id": "e1", "text": "Acme is a multi-tenant commerce platform", "source": "README.md:3" },
    { "id": "e2", "text": "rails ~> 8.0", "source": "Gemfile:12" },
    { "id": "e3", "text": "admin workspace uses React", "source": "admin/package.json:/dependencies/react" }
  ]
}
```

Valid output:

```json
{
  "text": "Multi-tenant commerce platform with a Rails backend and React administration client.",
  "evidence_ids": ["e1", "e2", "e3"]
}
```

Invalid output:

```json
{
  "text": "PCI-compliant global commerce platform deployed on AWS.",
  "evidence_ids": ["e1", "e99"]
}
```

The input does not support PCI compliance, global scope, AWS, or `e99`; the builder discards the output.

## Dashboard Design

### Route and navigation

- Route: `/digest`
- Navigation label: `Digest`
- Icon: a document or scan-text icon from the existing Lucide dependency
- Placement: immediately after Topology because Digest interprets repository-wide topology and links into it
- Also reachable from the Define workflow via a return-aware entry point — see Define workflow entry point, below. This is additive; `/digest` remains the single, standalone implementation of the page.

### Define workflow entry point

RD-8 requires opening the digest from the Define workflow without leaving the dashboard, and returning afterward without losing workflow state. Define's feature route is `/define/[feature]` (`dashboard/frontend/app/define/[feature]/page.tsx`); its layout already renders the shared `Header` component (`dashboard/frontend/components/layout/header.tsx`).

- `Header`, when rendered on a `/define/[feature]` route, adds a "Repository Digest" link reading the current `feature` route param and pointing to `/digest?returnTo=define&feature=<feature>`. This is same-tab, in-app navigation — no external window, satisfying "without leaving the dashboard."
- `/digest` reads the `returnTo` and `feature` query parameters. When both are present and `feature` is a valid feature name (see Edge Cases), the page header shows a persistent "← Return to Define" affordance next to the Refresh action, linking back to `/define/<feature>`.
- No state hand-off mechanism is required beyond the return link. Define's ceremony state — drafts, validation snapshots, suggestion threads — is persisted server-side (see `speed-define-ceremony-foundation.md` and its siblings), not held only in client-side component state, so navigating away to `/digest` and back resumes exactly where the user left off.
- Evidence links opened from `/digest` in this mode behave identically to the standalone case: the same `/topology?cluster=<id>&symbol=<id>` deep links, the same copyable `path:line` text. Define does not get a separate evidence-interaction model.
- Absent `returnTo`/`feature`, `/digest` behaves exactly as the standalone page described above — the Define entry point changes nothing about the page's default behavior.

### Page layout

```text
┌────────────────────────────────────────────────────────────────────┐
│ Repository Digest                         CURRENT · 8ca21d4 · 6m ago │
│ acme-storefront                                                     │
│ Multi-tenant commerce platform with Rails API...         [Refresh]  │
├──────────────┬───────────────┬───────────────┬──────────────────────┤
│ 1,042 files  │ 138k lines   │ 7 domains    │ 3,816 symbols           │
├───────────────────────────────────────┬───────────────────────────────┤
│ System map                          │ Discovery readiness            │
│ Admin · API · Orders · Payments     │ ✓ Map       ✓ Graph           │
│                                     │ ⏳ Knowledge · specs           │
├───────────────────────────────────────┼───────────────────────────────┤
│ Major domains                                                        │
│ Orders        46 files   312 symbols   high connectivity   [Open]    │
│ Catalog       71 files   428 symbols   medium connectivity [Open]    │
├───────────────────────────────────────┬───────────────────────────────┤
│ Entrypoints and commands            │ Hotspots and risks             │
│ API      bin/rails server           │ TenantContext.current     68   │
│ Tests    bundle exec rspec          │ Order#recalculate!        47   │
├───────────────────────────────────────┴───────────────────────────────┤
│ Conventions and discovery gaps                                       │
└────────────────────────────────────────────────────────────────────┘
```

The page follows the existing dashboard design system. Elevated content uses the existing `.surface` class. Accent color is reserved for the primary Refresh action, the primary repository metric, and active navigation. Technical values, hashes, commands, and file paths use IBM Plex Mono. Explanatory prose uses Inter.

### Evidence interaction

Every narrative card includes a confidence badge and an evidence affordance:

```text
Orders
Cart conversion, state transitions, totals, refunds, and cancellation.
[Derived] [3 sources]
```

Selecting `3 sources` opens a side panel:

```text
Evidence

semantic_graph
Order · app/models/order.rb:14
High-centrality representative symbol

semantic_graph
Orders::Checkout · app/services/orders/checkout.rb:9
Cluster member and external dependency source

documentation
README.md:48
Order lifecycle overview
```

If a source viewer is unavailable, file evidence is still shown as copyable `path:line` text. Topology evidence links to `/topology?cluster=<id>&symbol=<id>`.

### Page states

**Loading:** Skeleton title, four KPI cells, two large panels, and domain rows. Existing content remains visible during background refresh with a small generating indicator.

**Missing:** Explain that no digest exists. Primary action is "Build digest." If no project map exists, label the action "Index repository and build digest" and set `rebuildDiscovery: true`.

**Partial:** Render available sections normally. Readiness and missing sections explain prerequisites. Do not use an error-page treatment because partial output is expected.

**Stale:** Keep all content visible under a persistent amber banner:

```text
Digest describes 8ca21d4; repository is now 91f4b20.
Changed repository content may make domains and hotspots inaccurate. [Refresh]
```

**Refresh error with prior digest:** Keep the stale digest visible. Show a dismissible error containing the failing capability and safe remediation.

**Malformed artifact:** Show an error state with "Rebuild digest." Do not attempt to render partially parsed values.

**Empty repository:** Show zero files and a readiness message explaining that the project map contains no indexed files. Domain and command sections use an empty state rather than disappearing.

### Responsive behavior

- At 1280px and above, use the two-column information-dense layout shown above.
- From 768px to 1279px, KPI cards remain in two or four columns depending on available width; detail panels stack.
- Below 768px, all sections form one column, tables become horizontally scrollable, and evidence opens as a full-height sheet.
- Long commands and paths wrap at safe boundaries and include copy controls; they never force the whole page wider.

## Testing

### Acceptance Criteria

- A target repository with a valid project map and CSG produces a schema-valid digest whose aggregate counts exactly match the source artifacts.
- A repository with a valid project map and no other discovery artifacts produces a readable partial digest with honest readiness records and null optional counts.
- Every interpretive claim returned through GraphQL contains confidence and valid evidence.
- Reading the digest through GraphQL does not invoke source walking, Layer 1 building, command execution, or an agent provider.
- A fingerprint mismatch marks a stored digest stale while preserving and returning its contents.
- Failed refresh never overwrites the last valid digest.
- Two concurrent refresh requests start only one builder.
- Sensitive, ignored, and out-of-root paths never appear in digest content or evidence.
- The dashboard renders complete, partial, missing, stale, generating, refresh-failed, and malformed states.
- Opening Repository Digest from a Define feature page (`/define/[feature]` → `/digest?returnTo=define&feature=...`) never opens a new tab or external view, and the resulting `/digest` page shows a working "Return to Define" affordance back to the originating feature.
- Domain and hotspot limits are deterministic and enforced between 1 and 100.
- Deterministic digest generation (excluding optional narrative synthesis) completes in under 5 seconds for a repository with an existing Layer 1 index and no more than 5,000 indexed files.
- The optional agent projection never exceeds its configured token budget and always retains identity, freshness, readiness gaps, and the highest-ranked domains before lower-ranked details.

### Risks and Coverage

| Risk | Severity | Test Approach |
|------|----------|---------------|
| Optional malformed input prevents all output | High | Fixture matrix with each optional artifact independently absent and malformed; assert partial output retains unrelated sections |
| Counts drift from source artifacts | High | Contract fixtures with hand-computed totals and property tests for language/category rollups |
| Unsupported claims receive strong confidence | High | Schema validation plus claim/evidence tests; narrative adversarial fixtures with hallucinated evidence IDs |
| Path traversal leaks files outside project root | Critical | Unit tests for absolute paths, `..`, symlinks, encoded separators, and evidence normalization |
| Refresh destroys last valid artifact | High | Integration test injects failure before and during atomic replace and compares prior digest bytes |
| Staleness misses relevant changes | High | Fingerprint tests varying git HEAD, config, project map, CSG, knowledge, and schema version independently |
| Staleness fires for irrelevant config changes | Medium | Change UI theme, port, verbosity, and agent model; assert fingerprint remains stable |
| Duplicate refreshes race | High | Concurrent mutation test with a controlled slow builder and repository-scoped lock |
| Large CSG causes excessive memory or response size | Medium | Synthetic 100k-node fixture; verify stored caps, deterministic ordering, and resolver slicing |
| Discovered command is accidentally executed | Critical | Mock subprocess boundary and assert no command sourced from manifests reaches execution APIs |
| UI hides uncertainty | High | Component tests and visual snapshots for unknown confidence, partial readiness, and stale banner |
| GraphQL schema and JSON contract drift | High | Golden artifact parsed through resolver into a snapshot of all public fields |
| Agent projection exceeds budget | High | Exact token-estimation boundary tests at zero, minimum, typical, and oversized budgets |
| Deterministic generation exceeds the 5-second/5,000-file performance target | Medium | Benchmark fixture at 5,000 indexed files; assert wall-clock time excluding narrative synthesis |
| Refresh observes an inconsistent git HEAD mid-build | Medium | Integration test that mutates HEAD after generation starts; assert the digest is written then immediately marked stale, or retried once per configuration |
| Refresh observes inconsistent knowledge files mid-build | Medium | Integration test that mutates conventions/project-knowledge between hash calculation and write; assert the final fingerprint recheck catches the change |

### Test Plan

**Unit tests**

New `tests/test_repository_digest.py` covers:

- Required project-map validation.
- Optional loader isolation.
- File, line, category, language, symbol, and domain rollups.
- Percentage rounding and zero-line repositories.
- Domain ranking, tie-breaking, labeling, and unlabeled fallback.
- Relationship direction and deduplication.
- Representative file and symbol selection.
- Hotspot thresholds and deterministic ordering.
- Command normalization, deduplication, conflicts, and working directories.
- Confidence assignment.
- Evidence validation and path normalization.
- Risk rule thresholds.
- Canonical hashing and configuration projection.
- Atomic output validation before replacement.
- Narrative response validation and deterministic fallback.
- Agent projection ordering and token cuts.
- Agent projection token-budget boundaries: zero, minimum, typical, and oversized budgets, exercising the priority order in Agent projection.
- Conventions filtering to approved-only entries and confidence mapping by source (`config` → `confirmed`, `discovered` → `derived`).
- Gap aggregation from the identity, domain-labeling, and command-extraction stages.
- Path traversal, symlink resolution, and credential-denylist rejection for supplemental documentation and manifest loaders.
- Deterministic generation wall-clock time against the 5-second/5,000-file target.

Example domain ranking test:

```python
def test_domain_ranking_is_deterministic_when_scores_tie():
    domains = [
        make_domain(id="cluster-b", symbols=10, files=5, degree=2, blast=3),
        make_domain(id="cluster-a", symbols=10, files=5, degree=2, blast=3),
    ]

    ranked = rank_domains(domains)

    assert [d["id"] for d in ranked] == ["cluster-a", "cluster-b"]
    assert ranked[0]["rank"] == 1
    assert ranked[1]["rank"] == 2
```

Example partial-input test:

```python
def test_invalid_conventions_do_not_remove_topology(tmp_path):
    write_project_map(tmp_path, files=PROJECT_FILES)
    write_semantic_graph(tmp_path, nodes=NODES, edges=EDGES)
    write_text(tmp_path / ".speed/memory/conventions.json", "{not-json")

    digest = build_repository_digest(tmp_path)

    assert digest["status"] == "partial"
    assert digest["domains"]
    assert digest["conventions"] == []
    assert readiness(digest, "conventions")["status"] == "invalid"
```

**Integration tests**

New `dashboard/backend/tests/test_repository_digest.py` covers:

- Resolver reads a golden digest through actual target path resolution.
- Missing and malformed artifacts return null plus useful status.
- Freshness comparison uses current repository HEAD without modifying the repository.
- Mutation starts one background build and status transitions generating to current.
- Duplicate mutation returns `accepted: false`.
- Refresh failure preserves an existing digest.
- GraphQL field limits and enum translations match the JSON contract.
- Subscription emits generating and terminal states.

Use temporary git repositories with explicit commits for freshness tests. No test may depend on the SPEED repository's current working tree.

**End-to-end tests**

These five scenarios require a dedicated end-to-end task run against the full stack (backend and frontend together) — they are not covered by the unit or integration suites above:

- Index a small fixture repository, build a digest, start the dashboard backend, and verify the frontend displays the expected identity, counts, domains, command, and readiness.
- Modify and commit a fixture source file; verify the page changes to stale without losing content.
- Refresh; verify the page returns to current and displays the new short HEAD.
- Remove the CSG and refresh without rebuilding discovery; verify a partial digest replaces the prior one only after successful validation.
- Corrupt the project map and refresh; verify the previous digest remains visible with a refresh error.

**Visual/UI tests**

Component snapshots at 1440px, 1024px, and 390px for:

- Complete digest with maximum default domains and hotspots.
- Partial digest with multiple unavailable capabilities.
- Stale digest with a long current-versus-indexed message.
- Missing digest call to action.
- Generating state with and without an older readable digest.
- Refresh error.
- Long repository name, command, path, and domain label.
- Evidence panel containing file, symbol, and artifact-key evidence.

Verify keyboard focus, visible confidence labels independent of color, readable secondary text contrast, horizontal table containment, and reduced-motion behavior.

### Edge Cases

- Git repository has no commits, so current HEAD is unavailable.
- Target directory is not a git repository but contains valid discovery artifacts.
- Project map contains zero files.
- All indexed files are binary assets and line count is zero.
- A language record has files but no line counts.
- Semantic graph exists with zero nodes or edges.
- CSG nodes reference files absent from the project map.
- Cluster IDs contain characters unsafe for URLs.
- A single cluster contains every symbol.
- Every symbol has identical impact metrics.
- Domain edges contain duplicates or references to missing nodes.
- README is empty, badge-only, non-UTF-8, excessively large, or a symlink outside the target root.
- Multiple root manifests declare different project names.
- Monorepo packages contain commands with identical names but different working directories.
- A command contains quotes, shell operators, environment assignments, or newlines.
- Convention file contains pending, rejected, and accepted records together.
- Observation lines include malformed JSON among valid lines.
- Current git HEAD changes while generation is in progress. The builder records the HEAD observed at start and rechecks before write; a mismatch writes the digest but immediately marks it stale, or retries once if configured.
- Knowledge files change between hash calculation and artifact write. Apply the same final fingerprint recheck.
- Existing digest uses a future schema version.
- Status file says generating after the builder process has died. Existing process-status recovery marks it error after the standard stale-process threshold.
- Atomic replacement fails because the filesystem is read-only or full.
- Two dashboard processes request refresh against the same repository.
- `limit` is zero, negative, above 100, or omitted.
- Optional narrative provider times out or returns valid JSON with fabricated evidence IDs.
- Agent projection token budget is too small for even the required header. Return a minimal truncation notice within budget rather than overrun.
- `returnTo=define` is present but `feature` is missing, malformed, or no longer resolves to an existing feature. The "Return to Define" affordance is omitted rather than linking to a broken route; the rest of `/digest` renders normally.

### Out of Scope

- Accuracy benchmarking for arbitrary natural-language questions, because v1 is not a repository chat system.
- Correctness of the underlying language extractors and clustering algorithms beyond verifying that the digest preserves their artifact values.
- Security scanning, vulnerability detection, and compliance certification.
- Commit ownership or contributor analytics.
- Cross-repository or organization-wide digest aggregation.
- Browser integration with external source hosts such as GitHub; evidence remains local metadata unless another feature supplies external links.
- Load testing multiple simultaneous target repositories in one dashboard process, because the current dashboard is project-scoped.

## Security & Controls

### Filesystem boundaries

- All paths originate from the server-configured project root. GraphQL clients cannot supply a root.
- Resolve evidence paths lexically and reject absolute paths or any path containing `..` before joining.
- For supplemental documentation and manifest reads, resolve symlinks and require the resolved target to remain inside the project root.
- Continue to honor project map scope and ignore behavior. Supplemental loaders use an explicit allowlist of filenames and the project-knowledge denylist for `.env`, `.env.local`, `*.key`, `*.pem`, and credential-prefixed files.
- Never include absolute paths in the artifact or GraphQL response.

### Content handling

- Treat repository text and synthesized narrative as untrusted. React renders plain text; no `dangerouslySetInnerHTML`.
- Limit read sizes per supplemental source to 256 KiB and total supplemental text to 2 MiB before normalization.
- Strip NUL characters and reject invalid control characters from stored display strings.
- Do not execute, shell-expand, or validate commands by running them.
- Do not interpolate repository content into shell commands. Existing builder APIs receive explicit path arguments.

### Provider boundary

- Narrative synthesis is opt-in.
- Send only normalized evidence snippets with repository-relative provenance.
- Never send secrets, ignored files, full environment files, credential material, or arbitrary binary data.
- Validate structured output against the digest narrative schema.
- Reject evidence references not present in the request.
- Record provider and model metadata only in internal generation logs, not in user-facing claims unless existing telemetry policy permits it.

### Auditability

- Emit a digest-generation event with project identifier, indexed HEAD, fingerprint, status, duration, available capabilities, warning count, and whether narrative was requested.
- Do not log source snippets, commands containing possible secret values, or complete provider prompts.
- Refresh errors are sanitized before persistence.

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Relationship to discovery | Digest is a projection of existing discovery artifacts | Independently scan source files; build a separate repository summarizer | Shared artifacts keep human orientation aligned with the context agents receive and avoid duplicate parsers and drift. |
| Minimum dependency | Require only `project-map.json` | Require a complete CSG; allow README-only digest | Project map provides a stable, useful minimum while preserving progressive degradation. README-only output would omit the measured repository boundary. |
| Storage | Versioned JSON at `.speed/context/repository-digest.json` | SQLite tables; generate on every query; Markdown only | JSON matches SPEED's inspectable file-based state, supports atomic replacement, and serves API plus agents. |
| Read behavior | Query reads cached artifact and computes freshness only | Rebuild on page load; background automatic refresh | Reads stay fast, predictable, and free of hidden provider costs or source scans. |
| Freshness | Composite fingerprint of HEAD, discovery config, artifacts, knowledge, and schema | Git HEAD only; modification timestamps only; fixed TTL | Conclusions can change without HEAD moving, while unrelated UI or agent configuration should not invalidate the digest. |
| Optional failures | Produce partial digest with readiness records | Fail the entire build; silently omit sections | Partial data is useful, and explicit readiness prevents omission from being mistaken for absence. |
| Confidence model | Per-claim confirmed/derived/inferred/unknown | One overall percentage; no confidence labels | Different fields have different evidentiary strength. A single score hides that distinction. |
| Evidence | Structured references required for interpretive claims | Free-text citations; no citations | Structured evidence supports UI drill-down, validation, and future agent use. |
| Domain source | Reuse CSG clusters and labels | Recluster specifically for the digest; infer solely from directories | CSG is the shared architectural model. Digest-specific clustering would create conflicting system maps. |
| Ranking | Deterministic formula with stable tie-breaks | LLM ranking; alphabetical only; user-configured weights in v1 | Determinism makes output testable and refresh diffs explainable while still surfacing important areas. |
| Narrative | Optional, bounded, schema-validated, off by default | Mandatory LLM summary; deterministic only forever | V1 remains reliable and inexpensive while preserving a controlled path to better prose. |
| Commands | Display only, never execute | Execute to verify; omit commands | Execution is unsafe and environment-dependent. Provenance gives users enough context to judge commands. |
| History | Keep only current digest, with old one preserved on failed refresh | Store every digest; overwrite before generation | Historical analytics are out of scope, while failure safety is mandatory. Git and events retain enough operational trace for v1. |
| API pagination | Store capped ranked arrays and expose limit slicing | Return entire graph; cursor pagination | Digest is a bounded orientation artifact, not a graph API. Existing Topology handles complete exploration. |
| UI relationship | New `/digest` view beside Topology | Replace Home; embed only in Define; add cards to Topology | A dedicated view supports orientation while links and future embedding can reuse it without crowding specialized pages. |
| Define access mechanism | Return-aware link (`/digest?returnTo=define&feature=<feature>`) from Define's header, not embedding | Full embed of the digest UI inside `/define/[feature]`; a second, Define-specific digest view | Satisfies RD-8's "without leaving the dashboard" requirement while keeping one digest implementation and one set of rendering states. Embedding would duplicate the page inside Define's own layout for no added capability. |

## Drawbacks

- The feature adds another derived artifact whose schema and freshness rules require long-term maintenance.
- Users may still over-trust inferred domain names even with confidence labels and evidence.
- A repository-wide summary necessarily compresses detail and can obscure small but critical subsystems.
- Reusing the CSG inherits its language-support gaps, extraction errors, and clustering quality.
- Composite fingerprint calculation requires reading and hashing several artifacts, adding bounded overhead to status queries unless hashes are cached.
- Command discovery across heterogeneous ecosystems can become a growing registry that needs ownership outside the digest feature.
- Optional narrative synthesis adds provider-specific failure modes, cost, latency, and privacy considerations even though deterministic fallback exists.
- A dedicated dashboard route increases navigation density and frontend maintenance.
- Partial digests can differ substantially between fresh and mature SPEED installations, complicating screenshots, documentation, and user expectations.

## Search / Query Strategy

No new search index is introduced.

Expected data volumes:

| Data | Typical | Supported design target |
|------|---------|-------------------------|
| Project-map files | 100 to 20,000 | 100,000 |
| CSG nodes | 500 to 50,000 | 250,000 |
| CSG edges | 1,000 to 150,000 | 1,000,000 |
| Stored digest domains | 5 to 30 | Capped at 100 |
| Stored digest hotspots | 10 to 50 | Capped at 100 |
| Stored artifact size | 50 to 300 KiB | 2 MiB hard warning threshold |

Build access patterns are linear over project map files and CSG nodes/edges. Use maps keyed by node and cluster ID to avoid repeated graph scans. Expected complexity is `O(F + N + E + K)`, where `F` is files, `N` nodes, `E` edges, and `K` knowledge/observation records.

Read access loads one bounded JSON artifact. The backend may cache the parsed artifact keyed by `(path, mtime_ns, size)` within the process. Freshness checks cache canonical hashes using the same key. Cache entries are project-scoped and invalidated when file metadata changes.

GraphQL field limits slice stored ranked arrays. Filtering or arbitrary full-text search belongs in Topology or a future repository-search feature.

## Migration Strategy

No existing persistent data is modified.

Rollout sequence:

1. Add digest JSON schema, builder, validation, and tests. No dashboard behavior changes.
2. Add backend loader, freshness calculation, GraphQL types, query, and status query.
3. Add `/digest` page and navigation behind artifact availability; missing state remains supported.
4. Add refresh mutation, build status, lock, and subscription.
5. Add optional agent-context projection after the artifact contract is stable.
6. Evaluate narrative synthesis separately and keep it disabled by default until evidence fidelity tests pass.

Existing projects require no migration. Their first digest request returns missing and offers an explicit build action. `speed init` does not generate a digest automatically in v1.

Schema evolution rules:

- Additive optional fields may remain within schema version 1 if old consumers can ignore them.
- Removing fields, changing meaning, or changing enum values increments `schema_version`.
- A consumer encountering a newer unsupported version returns an invalid status and offers rebuild/upgrade guidance; it does not guess at compatibility.
- Builder replacement is atomic, so rollback consists of reverting code and regenerating with the older supported schema. If an older builder cannot overwrite a newer artifact safely, it writes a clear incompatibility error and preserves the artifact.

## File Impact

Proposed paths use existing module conventions and may be adjusted if a shared discovery-command registry already exists during implementation.

### Core context and discovery

- `lib/context/repository_digest.py` (new): artifact loading, deterministic assembly, ranking, confidence, validation, atomic persistence.
- `lib/context/repository_digest_schema.py` (new): typed constants/dataclasses or validation helpers for schema version 1.
- `lib/context/repository_digest_freshness.py` (new): canonical hashing, discovery-config projection, freshness comparison.
- `lib/context/command_discovery.py` (new or shared existing module): reusable normalized command discovery. It must not be dashboard-specific.
- `lib/context/layer1.py` (modified): optional explicit hook to generate the digest after successful index construction; no mandatory generation on every existing path until rollout policy is decided.
- `lib/context/assembly.py` (modified in agent-context phase): budgeted repository digest projection for eligible global stages.
- `lib/toml.py` and `templates/speed-toml.toml` (modified only if digest configuration is introduced): parse documented digest settings.

### CLI and orchestration

- `speed` or `lib/cmd/digest.sh` (new/modified): optional `speed digest` command routing.
- `lib/events.sh` (modified): digest-generation event type if existing generic events cannot represent it.

### Dashboard backend

- `dashboard/backend/resolvers/repository_digest.py` (new): loader, GraphQL mapping, freshness, refresh coordination.
- `dashboard/backend/resolvers/repository_digest_types.py` (new): Strawberry types and enums.
- `dashboard/backend/schema.py` (modified): queries, mutation, and subscription registration.
- `dashboard/backend/paths.py` (modified): canonical digest and status paths if not covered by existing context path helpers.
- `dashboard/backend/subscriptions.py` (modified): digest status event if the generic event channel is insufficient.
- `dashboard/backend/tests/test_repository_digest.py` (new): resolver and refresh integration tests.

### Dashboard frontend

- `dashboard/frontend/app/digest/page.tsx` (new): route and state orchestration, including reading `returnTo`/`feature` query params for the Define return affordance.
- `dashboard/frontend/components/layout/header.tsx` (modified): adds a "Repository Digest" link when rendered on a `/define/[feature]` route, targeting `/digest?returnTo=define&feature=<feature>`.
- `dashboard/frontend/components/digest/DigestHeader.tsx` (new).
- `dashboard/frontend/components/digest/FootprintGrid.tsx` (new).
- `dashboard/frontend/components/digest/SystemMap.tsx` (new): bounded domain relationship display; reuse existing graph components where practical.
- `dashboard/frontend/components/digest/DomainList.tsx` (new).
- `dashboard/frontend/components/digest/CommandList.tsx` (new).
- `dashboard/frontend/components/digest/RiskPanel.tsx` (new).
- `dashboard/frontend/components/digest/ReadinessPanel.tsx` (new).
- `dashboard/frontend/components/digest/EvidencePanel.tsx` (new).
- `dashboard/frontend/lib/graphql/queries/repository-digest.ts` (new): query, mutation, subscription, and TypeScript types.
- `dashboard/frontend/components/layout/sidebar.tsx` (modified): Digest navigation item.
- `dashboard/frontend/app/globals.css` (modified only for digest-specific layout classes that cannot be expressed with existing tokens and utilities).
- `dashboard/frontend/__tests__/digest/` (new): component and page-state tests.

### Documentation

- `dashboard/README.md` (modified): `/digest` view and GraphQL operations.
- `docs/architecture/context-pipeline.md` (modified): repository digest as a Layer 1 projection, its cache key, and its consumers.
- `docs/api/config.md` (modified only if configuration is added).

## Dependencies

- Existing `build_project_map()` output and schema, including scope, ignore, category, language, directory, and line-count data.
- Existing CSG output, cluster assignments, edges, symbol locations, and impact metrics.
- Existing target-project path resolution in `dashboard/backend/paths.py`.
- Existing Strawberry GraphQL server and subscription manager.
- Existing dashboard frontend GraphQL client, layout, loading skeletons, and design tokens.
- Existing approved conventions and project-knowledge formats. The digest must adapt through loaders rather than redefine those schemas.
- Existing observation formats for historical risk signals.
- Existing spec-alignment artifact for optional coverage readiness.
- Existing lock and background-process conventions for refresh coordination.
- A shared command discovery registry. If none exists, it is created as a discovery capability and tested independently before the digest consumes it.

No external service or new database is required. Optional narrative synthesis uses the existing configured provider abstraction and remains disabled by default.

## Unresolved Questions

1. **Default generation point:** Should a normal Layer 1 build always generate the deterministic digest, or should generation remain explicit until performance is measured on large repositories? This blocks the final `layer1.py` hook. Proposed resolution: benchmark against the existing large-repository fixtures and enable by default if p95 incremental time is below 5 seconds.

2. **Refresh authority:** The current dashboard is local and project-scoped, but multiplayer work is expanding. Which authorization primitive should guard `refreshRepositoryDigest` before remote access exists? This blocks the mutation's final policy. Proposed resolution: reuse the strongest existing project mutation guard and document that remote deployments must require project-write permission.

3. **Source-file navigation:** There is no general source browser in the current dashboard navigation. Should evidence paths open a lightweight read-only source panel, copy the path, or defer to Topology only? This blocks part of the evidence interaction. Proposed resolution: v1 links CSG evidence to Topology and makes all paths copyable; a source viewer is a separate feature.

4. **Command discovery ownership:** Is command extraction already sufficiently centralized in configuration and gate parsing, or should this RFC introduce `lib/context/command_discovery.py`? This blocks file ownership and reuse. Proposed resolution: audit existing CLAUDE.md and manifest command parsers, then extract shared normalization rather than duplicating them.

5. **Narrative release:** What evidence-fidelity threshold must narrative synthesis meet before it can be enabled in UI? This blocks only the optional narrative flag. Proposed resolution: require 100% valid evidence IDs and zero unsupported material claims across a curated multilingual repository evaluation set; ship deterministic summaries first.

6. **Agent consumers:** Which global agent stages receive `project_digest_for_agent()` and with what budgets? This blocks the Should-level agent integration, not the dashboard. Proposed resolution: start with Architect and Define assistance at 2,000 tokens, evaluate context usefulness, and keep per-task Developer packages unchanged.

7. **Digest history:** Should successful previous digests be retained for architectural-change comparison? This is outside v1 but affects whether atomic replacement discards useful data. Proposed resolution: emit compact generation events now; design historical snapshots only when a user story requires comparison.

8. **Domain label correction:** Should human corrections update the digest alone or become approved project knowledge that influences future indexing? This blocks correction UX, which is outside v1. Proposed resolution: do not add digest-local overrides; route future corrections through project knowledge so all consumers share them.
