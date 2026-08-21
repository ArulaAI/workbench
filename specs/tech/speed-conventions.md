# Tech Spec: Convention Discovery & Project Knowledge

> Product spec: [speed-conventions.md](../product/speed-conventions.md)
> Depends on: Observation Infrastructure ([speed-observations.md](speed-observations.md)), CSG infrastructure (`lib/context/csg.py`, `lib/context/layer1_domain_clustering.py`), Tree-sitter infrastructure (`lib/context/treesitter_extract.py`)

## Basic Example

Run convention discovery, inspect the result, and see how it reaches an agent prompt:

```python
from pathlib import Path
from lib.learn.conventions import discover_conventions, format_conventions_for_agent

# Discover conventions from codebase
result = discover_conventions(
    project_root=Path("/home/user/myproject"),
    memory_dir=Path("/home/user/myproject/.speed/memory"),
    csg_path=Path("/home/user/myproject/.speed/context/semantic-graph.json"),
)

# Inspect what was found
print(f"{len(result.conventions)} conventions, {len(result.candidates)} candidates")
for c in result.conventions:
    print(f"  [{c.confidence}] {c.convention} (source: {c.source})")

# Output:
#   7 conventions, 3 candidates
#   [established] Import ordering enforced by ruff (isort rules enabled) (source: config)
#   [established] Always modify `lib/toml.py` and `templates/speed-toml.toml` together. ... (source: discovered)
#   [emerging] Use snake_case for functions in `lib/`. 87% of 42 functions follow ... (source: discovered)
#   ...

# Format for the Developer agent (scoped to task files)
conventions_md = format_conventions_for_agent(
    conventions_path=Path("/home/user/myproject/.speed/memory/conventions.json"),
    agent="developer",
    task_files=["lib/toml.py", "templates/speed-toml.toml"],
)
print(conventions_md)

# Output (injected into the Developer prompt as "### Project Conventions"):
#   **Implementation patterns:**
#   - Always update `templates/speed-toml.toml` when modifying `lib/toml.py`. (established — co-modified 12/12 commits)
#   - Use relative imports within `lib/context/`. Absolute imports everywhere else. (ref: lib/context/assembly.py:12)
#   ...
```

CLI equivalent:

```bash
# Discover conventions (writes conventions.json, conventions-meta.json, conventions-candidates.json)
speed learn --conventions

# Seed project knowledge drafts from existing docs
speed learn --seed-knowledge
# → Operator reviews .speed/memory/project-knowledge-drafts.json
# → Manually promotes accepted entries to .speed/memory/project-knowledge.json

# Conventions and knowledge are automatically injected into agent prompts
# on the next speed run / speed review / speed plan
```

## Overview

Convention Discovery reads linter/formatter configs, the codebase (tree-sitter AST, git history, lock files), and integrates evidence from the observation log. Deterministic templates format patterns into structured convention entries. No LLM calls. Project Knowledge provides a human-maintained companion file for knowledge that code analysis can't extract. Both feed into agent prompts through the existing assembly/injection pattern.

```
Linter/formatter configs (ESLint, Ruff, Prettier, tsconfig, etc.)
lib/context/csg.py (clusters, symbols, edges)
lib/context/layer1_domain_clustering.py (domain clusters)
lib/context/treesitter_extract.py (imports, function/class names)
git log (co-modification history)
lock files / manifests (dependency inventory)
.speed/memory/observations/ (reviewer findings, human corrections)
        ↓
   ┌─────────────────────────────────────────────────┐
   │         Convention Discovery Pipeline            │
   │                                                  │
   │  Phase 0: Config reading (no LLM)                │
   │  Phase A: Mechanical extraction (no LLM)         │
   │  Phase B: Observation integration (no LLM)       │
   │  Phase C: Template formatting & validation (no   │
   │           LLM)                                   │
   │                                                  │
   │  Entire pipeline is LLM-free. Deterministic.     │
   └──────────────────┬──────────────────────────────┘
                      ↓
   .speed/memory/
   ├── conventions.json              ← discovered conventions
   ├── conventions-candidates.json   ← rejected patterns
   ├── conventions-meta.json         ← incremental state
   ├── project-knowledge.json        ← human-maintained
   └── project-knowledge-drafts.json ← seeded/system-prompted entries
                      ↓
   assemble_developer()  → "Implementation Guidance" section
   assemble_reviewer()   → "Convention Checklist" section
   assemble_architect()  → "Structural Constraints" section
```

### End-to-End Integration Map

Every integration point annotated NEW, EXISTING, or MODIFIED. Read top to bottom to trace data from source to agent prompt, and from agent output back through the feedback loop.

```
╔════════════════════════════════════════════════════════╗
║              CLI ENTRY POINTS                          ║
║                                                        ║
║  speed learn --conventions       [MODIFIED — new flag] ║
║  speed learn --seed-knowledge    [MODIFIED — new flag] ║
║  speed plan                      [EXISTING]            ║
║  speed run                       [EXISTING]            ║
║  speed review                    [EXISTING]            ║
╚═══════════╤════════════════════════════════╤═══════════╝
            │                                │
            │ learn path                     │ agent path
            ▼                                │
╔═══════════════════════════════╗             │
║  LEARN COMMAND [MODIFIED]     ║             │
║  lib/cmd/learn.sh             ║             │
║                               ║             │
║  --conventions flag    [NEW]  ║             │
║  --seed-knowledge flag [NEW]  ║             │
║         │                     ║             │
║         ▼                     ║             │
║  lib/learn_bridge.sh [MOD]    ║             │
║  learn_conventions()   [NEW]  ║             │
║  learn_seed_knowledge() [NEW] ║             │
╚═══════════╤═══════════════════╝             │
            │                                 │
            ▼                                 │
╔═══════════════════════════════════════════╗  │
║          TRIGGER CHECK [NEW]              ║  │
║          _should_run_discovery()          ║  │
║                                           ║  │
║  conventions-meta.json missing? → first   ║  │
║  50+ files changed since last?  → full    ║  │
║  3+ features completed?         → full    ║  │
║  CSG cluster checksums differ?  → full    ║  │
║  5+ convention_violations?      → partial ║  │
║  --conventions flag?            → manual  ║  │
╚═══════════╤═══════════════════════════════╝  │
            │ trigger met                      │
            ▼                                  │
┌───────────────────────────────────────────────────────┐
│                    DATA SOURCES                        │
│                                                        │
│  ┌──────────────────────┐  ┌────────────────────────┐ │
│  │ Linter/fmt configs   │  │ Tree-sitter AST        │ │
│  │ [EXISTING in repos]  │  │ [EXISTING]             │ │
│  │ 16 types:            │  │ treesitter_extract.py  │ │
│  │ .editorconfig        │  │ • structured imports   │ │
│  │ pyproject.toml       │  │ • function/method names│ │
│  │ .eslintrc.*          │  │ • class names          │ │
│  │ .prettierrc          │  └────────────────────────┘ │
│  │ biome.json           │                              │
│  │ tsconfig.json        │  ┌────────────────────────┐ │
│  │ .golangci.yml        │  │ CSG [EXISTING]         │ │
│  │ clippy.toml          │  │ csg.py                 │ │
│  │ checkstyle.xml       │  │ • symbols (Layer A)    │ │
│  │ pmd.xml              │  │ • edges (Layer B)      │ │
│  │ .rubocop.yml         │  │ • clusters (Layer C)   │ │
│  │ .clang-format        │  │ • impact (Layer D)     │ │
│  │ .clang-tidy          │  └────────────────────────┘ │
│  │ stylecop.json        │                              │
│  │ .shellcheckrc        │  ┌────────────────────────┐ │
│  └──────────────────────┘  │ Git history [EXISTING] │ │
│                             │ git log --numstat      │ │
│  ┌──────────────────────┐  └────────────────────────┘ │
│  │ Lock files [EXISTING]│                              │
│  │ requirements.txt     │  ┌────────────────────────┐ │
│  │ package.json         │  │ Observation log        │ │
│  │ Cargo.toml           │  │ [EXISTING]             │ │
│  │ go.sum               │  │ .speed/memory/         │ │
│  └──────────────────────┘  │ observations/*.jsonl   │ │
│                             └────────────────────────┘ │
└────────────────────────┬──────────────────────────────┘
                         │
                         ▼
╔════════════════════════════════════════════════════════╗
║     CONVENTION DISCOVERY PIPELINE [NEW]                ║
║     lib/learn/conventions.py                           ║
║                                                        ║
║  ┌──────────────────────────────────────────────────┐  ║
║  │ Phase 0: Config reading [NEW]                    │  ║
║  │ _extract_config_conventions()                    │  ║
║  │                                                  │  ║
║  │ Reads: 16 config file types [EXISTING files]     │  ║
║  │ Parses: TOML/JSON/YAML per type [NEW parsers]    │  ║
║  │ Emits: ConventionEntry objects                   │  ║
║  │        confidence=established, source=config     │  ║
║  │ Skips: Phase C validation (config IS evidence)   │  ║
║  └─────────────────────┬────────────────────────────┘  ║
║                        ▼                               ║
║  ┌──────────────────────────────────────────────────┐  ║
║  │ Phase A: Mechanical extraction [NEW]             │  ║
║  │                                                  │  ║
║  │ A1: _extract_comodification() [NEW]              │  ║
║  │     reads: git log --numstat [EXISTING]          │  ║
║  │     emits: RawPattern(type="comodification")     │  ║
║  │                                                  │  ║
║  │ A2: _extract_imports_and_naming() [NEW]          │  ║
║  │     reads: treesitter_extract.py [EXISTING]      │  ║
║  │     reads: CSG symbol names [EXISTING]           │  ║
║  │     emits: RawPattern(type="naming"|"import")    │  ║
║  │                                                  │  ║
║  │ A3: _extract_import_graph() [NEW]                │  ║
║  │     reads: CSG edges + clusters [EXISTING]       │  ║
║  │     emits: RawPattern(type="import")             │  ║
║  │                                                  │  ║
║  │ A4: _extract_dependency_usage() [NEW]            │  ║
║  │     reads: lock files [EXISTING]                 │  ║
║  │     reads: import chains from A2/A3              │  ║
║  │     emits: RawPattern(type="dependency")         │  ║
║  └─────────────────────┬────────────────────────────┘  ║
║                        ▼                               ║
║  ┌──────────────────────────────────────────────────┐  ║
║  │ Phase B: Observation integration [NEW]           │  ║
║  │ _integrate_observations()                        │  ║
║  │                                                  │  ║
║  │ reads: .speed/memory/observations/*.jsonl        │  ║
║  │        [EXISTING observation format]             │  ║
║  │ filters: convention_violation, reviewer_finding, │  ║
║  │          human_override [EXISTING obs types]     │  ║
║  │ correlates: raw patterns ↔ observations [NEW]    │  ║
║  │ actions:                                         │  ║
║  │   strengthen existing patterns (++ obs_support)  │  ║
║  │   create new patterns (obs-only, no code match)  │  ║
║  └─────────────────────┬────────────────────────────┘  ║
║                        ▼                               ║
║  ┌──────────────────────────────────────────────────┐  ║
║  │ Phase C: Template formatting & validation [NEW]  │  ║
║  │ _format_and_validate()                           │  ║
║  │                                                  │  ║
║  │ CONVENTION_TEMPLATES (20 templates) [NEW]        │  ║
║  │   pattern.type → template key → convention text  │  ║
║  │                                                  │  ║
║  │ Quality bar [NEW] — 4 checks:                    │  ║
║  │   actionable / project-specific / evidenced /    │  ║
║  │   scoped                                         │  ║
║  │                                                  │  ║
║  │ _assign_confidence() [NEW]                       │  ║
║  │   90%+ adherence AND obs → established           │  ║
║  │   60%+ adherence OR 3+ obs → emerging            │  ║
║  │   recent trend away → decaying                   │  ║
║  │                                                  │  ║
║  │ Evolution tracking [NEW]                         │  ║
║  │   old + new pattern in same scope → evolution{}  │  ║
║  │                                                  │  ║
║  │ Conflict handling [NEW]                          │  ║
║  │   contradictory patterns → conflict entry        │  ║
║  │   obs evidence available → auto-resolve          │  ║
║  │                                                  │  ║
║  │ Split:                                           │  ║
║  │   passed → conventions.json                      │  ║
║  │   rejected → conventions-candidates.json         │  ║
║  └────────────┬─────────────────────────────────────┘  ║
╚═══════════════╪════════════════════════════════════════╝
                │
     ┌──────────┴──────────────────────────────┐
     │                                          │
     ▼                                          ▼
┌──────────────────────┐  ┌──────────────────────────────┐
│ CONVENTION OUTPUTS   │  │ PROJECT KNOWLEDGE PIPELINE   │
│ .speed/memory/ [NEW] │  │ lib/learn/project_knowledge  │
│                      │  │                    .py [NEW] │
│ conventions.json     │  │                              │
│ ├─ conventions[]     │  │ seed_knowledge() [NEW]       │
│ ├─ conflicts[]       │  │ ├─ reads: README, CLAUDE.md, │
│ └─ views{}           │  │ │  CONTRIBUTING, ADRs,       │
│    ├─ developer      │  │ │  inline IMPORTANT/HACK/etc │
│    ├─ reviewer       │  │ └─ writes: pk-drafts.json    │
│    └─ architect      │  │                              │
│                      │  │ detect_knowledge_gaps() [NEW]│
│ conventions-meta     │  │ ├─ reads: observations       │
│  .json               │  │ │  [EXISTING]                │
│ ├─ last_run          │  │ ├─ groups: 3+ retries/area   │
│ ├─ files_analyzed    │  │ └─ writes: pk-drafts.json    │
│ ├─ cluster_checksums │  │                              │
│ └─ trigger           │  │ check_staleness() [NEW]      │
│                      │  │ ├─ reads: pk.json [NEW]      │
│ conventions-         │  │ ├─ checks: file paths exist, │
│  candidates.json     │  │ │  dep versions, 90d age     │
│ (rejected patterns)  │  │ └─ writes: pk-drafts.json    │
└──────────┬───────────┘  │                              │
           │              │         ┌────────────────┐   │
           │              │         │ Human reviews  │   │
           │              │         │ drafts, moves  │   │
           │              │         │ accepted →     │   │
           │              │         │ pk.json        │   │
           │              │         └───────┬────────┘   │
           │              │                 │            │
           │              │  project-knowledge.json [NEW]│
           │              │  project-knowledge-drafts    │
           │              │                   .json [NEW]│
           │              └──────────────┬───────────────┘
           │                             │
           └──────────┬──────────────────┘
                      │
                      ▼
╔════════════════════════════════════════════════════════╗
║  FORMATTING LAYER [NEW]                                ║
║  lib/learn/conventions.py                              ║
║                                                        ║
║  format_conventions_for_agent(               [NEW]     ║
║      conventions_path, agent, task_files)              ║
║  ├─ reads: conventions.json → views.{agent}            ║
║  ├─ filters: by task_files scope                       ║
║  └─ pre-truncates: to max_tokens (2,000)               ║
║     returns: markdown string                           ║
║                                                        ║
║  format_knowledge_for_agent(                 [NEW]     ║
║      knowledge_path, agent, task_files)                ║
║  ├─ reads: project-knowledge.json → entries[]          ║
║  ├─ filters: by agents[] contains agent                ║
║  ├─ filters: by applies_to[] ∩ task_files              ║
║  └─ pre-truncates: to max_tokens (1,500)               ║
║     returns: markdown string                           ║
╚══════════════════╤═════════════════════════════════════╝
                   │
                   │  conventions_md, knowledge_md
                   ▼
╔════════════════════════════════════════════════════════╗
║  CONTEXT BRIDGE [MODIFIED]                             ║
║  lib/context_bridge.sh                                 ║
║                                                        ║
║  context_assemble_developer() [MODIFIED]               ║
║  context_assemble_reviewer()  [MODIFIED]               ║
║  context_assemble_architect() [MODIFIED]               ║
║                                                        ║
║  Each function gains [NEW]:                            ║
║  ├─ from lib.learn.conventions import                  ║
║  │    format_conventions_for_agent,                    ║
║  │    format_knowledge_for_agent                       ║
║  ├─ Load conventions.json + project-knowledge.json     ║
║  ├─ Call formatters with (agent_name, task_files)      ║
║  └─ Pass conventions_md + knowledge_md as new args     ║
║     to assemble_*() functions                          ║
║                                                        ║
║  Existing pattern preserved [EXISTING]:                ║
║  ├─ filter_learnings_for_task() → learnings_md         ║
║  └─ Pass learnings_md to assemble_*()                  ║
╚══════════════════╤═════════════════════════════════════╝
                   │
                   │  conventions_md, knowledge_md,
                   │  learnings_md (+ all existing args)
                   ▼
╔════════════════════════════════════════════════════════╗
║  ASSEMBLY FUNCTIONS [MODIFIED]                         ║
║  lib/context/assembly.py                               ║
║                                                        ║
║  ┌──────────────────────────────────────────────────┐  ║
║  │ assemble_developer() [MODIFIED]                  │  ║
║  │ + conventions: str = ""          [NEW param]     │  ║
║  │ + project_knowledge: str = ""    [NEW param]     │  ║
║  │                                                  │  ║
║  │ Section insertion point:                         │  ║
║  │   ... Cross-Cutting Constraints  [EXISTING]      │  ║
║  │   ──────────────────────────────────────────     │  ║
║  │   "### Project Conventions"      [NEW section]   │  ║
║  │   "### Project Knowledge"        [NEW section]   │  ║
║  │   "### Learned Patterns"         [EXISTING]      │  ║
║  │   ──────────────────────────────────────────     │  ║
║  │   ... Files You'll Modify        [EXISTING]      │  ║
║  ├──────────────────────────────────────────────────┤  ║
║  │ assemble_reviewer() [MODIFIED]                   │  ║
║  │ + conventions: str = ""          [NEW param]     │  ║
║  │ + project_knowledge: str = ""    [NEW param]     │  ║
║  │                                                  │  ║
║  │ Section insertion point:                         │  ║
║  │   ... Assumptions to Verify      [EXISTING]      │  ║
║  │   ──────────────────────────────────────────     │  ║
║  │   "### Convention Checklist"     [NEW section]   │  ║
║  │   "### Project Knowledge"        [NEW section]   │  ║
║  │   "### Review Calibration"       [EXISTING]      │  ║
║  │   ──────────────────────────────────────────     │  ║
║  │   ... Git Diff                   [EXISTING]      │  ║
║  ├──────────────────────────────────────────────────┤  ║
║  │ assemble_architect() [MODIFIED]                  │  ║
║  │ + conventions: str = ""          [NEW param]     │  ║
║  │ + project_knowledge: str = ""    [NEW param]     │  ║
║  │                                                  │  ║
║  │ Section insertion point:                         │  ║
║  │   ... Directory Structure        [EXISTING]      │  ║
║  │   ──────────────────────────────────────────     │  ║
║  │   "### Structural Conventions"   [NEW section]   │  ║
║  │   "### Project Knowledge"        [NEW section]   │  ║
║  │   "### Project History"          [EXISTING]      │  ║
║  │   ──────────────────────────────────────────     │  ║
║  │   ... Domain Architecture        [EXISTING]      │  ║
║  └──────────────────────────────────────────────────┘  ║
║                                                        ║
║  BUDGET MECHANICS [EXISTING — unchanged]               ║
║  STAGE_ALLOCATIONS 10% reserve per stage               ║
║  Subdivision by insertion order in assembly:            ║
║  ┌────────────┬─────────┬───────┬─────────┬──────────┐ ║
║  │ Agent      │ Reserve │ Conv  │ Know    │ Learnings│ ║
║  ├────────────┼─────────┼───────┼─────────┼──────────┤ ║
║  │ Developer  │  8,000  │≤2,000 │ ≤1,500  │ ≤4,500   │ ║
║  │ Reviewer   │  6,000  │≤2,000 │ ≤1,500  │ ≤2,500   │ ║
║  │ Architect  │  6,000  │≤2,000 │ ≤1,500  │ ≤2,500   │ ║
║  └────────────┴─────────┴───────┴─────────┴──────────┘ ║
║  Priority: conventions → knowledge → learnings         ║
║  _truncate() clips from end → learnings cut first      ║
╚══════════════════╤═════════════════════════════════════╝
                   │
                   │  final markdown prompt
                   ▼
╔════════════════════════════════════════════════════════╗
║  AGENT PROMPTS [EXISTING — no agent file changes]      ║
║                                                        ║
║  ┌────────────────┐┌────────────────┐┌──────────────┐  ║
║  │ Developer      ││ Reviewer       ││ Architect    │  ║
║  │ lib/cmd/run.sh ││ lib/cmd/       ││ lib/cmd/     │  ║
║  │ [EXISTING]     ││ review.sh      ││ plan.sh      │  ║
║  │                ││ [EXISTING]     ││ [EXISTING]   │  ║
║  │ Now receives:  ││ Now receives:  ││ Now receives:│  ║
║  │ • Project      ││ • Convention   ││ • Structural │  ║
║  │   Conventions  ││   Checklist    ││   Conventions│  ║
║  │ • Project      ││ • Project      ││ • Project    │  ║
║  │   Knowledge    ││   Knowledge    ││   Knowledge  │  ║
║  │ • Learned      ││ • Review       ││ • Project    │  ║
║  │   Patterns     ││   Calibration  ││   History    │  ║
║  └───────┬────────┘└───────┬────────┘└──────┬───────┘  ║
╚══════════╪═════════════════╪════════════════╪══════════╝
           │                 │                │
           ▼                 ▼                ▼
╔════════════════════════════════════════════════════════╗
║  FEEDBACK LOOP                                         ║
║                                                        ║
║  Agent executes task                    [EXISTING]     ║
║       │                                                ║
║       ▼                                                ║
║  Produces artifacts (logs, diffs, etc.) [EXISTING]     ║
║       │                                                ║
║       ▼                                                ║
║  speed learn → extract.py               [EXISTING]     ║
║  10 extraction steps + 4 human correction steps        ║
║       │                                                ║
║       ├──→ .speed/memory/observations/  [EXISTING]     ║
║       │    *.jsonl (append-only)                       ║
║       │         │                                      ║
║       │         ├──→ Phase B reads these  [NEW hook]   ║
║       │         │    on next discovery run              ║
║       │         │                                      ║
║       │         └──→ 5+ convention_violation            ║
║       │              observations trigger  [NEW]       ║
║       │              automatic re-discovery             ║
║       │                                                ║
║       └──→ synthesize.py → learnings/   [EXISTING]     ║
║            developer-learnings.json                    ║
║            reviewer-learnings.json                     ║
║            architect-learnings.json                    ║
║            (coexist with conventions                   ║
║             in assembly reserve pool)                  ║
╚════════════════════════════════════════════════════════╝
```

| Tag | Count | What |
|-----|-------|------|
| **[NEW]** | 28 | Pipeline, formatters, templates, outputs, triggers, knowledge pipeline |
| **[EXISTING]** | 22 | Data sources, CSG, tree-sitter, observations, budget system, agent commands, learnings |
| **[MODIFIED]** | 8 | learn.sh, learn_bridge.sh, context_bridge.sh (3 functions), assembly.py (3 functions) |

## Input Contract

### CSG (from `lib/context/csg.py`) **[EXISTING]**

Convention Discovery reads the CSG as a consumer, never modifies it.

| CSG layer | What convention discovery uses |
|-----------|------------------------------|
| Symbols (Layer A) | `kind`, `signature`, `file`, `name` for naming pattern extraction (note: `decorators` field exists but is not populated by current ast-grep rules) |
| Edges (Layer B) | `type` (calls, imports, inherits) for import convention detection |
| Clusters (Layer C) | `id`, `label`, `files`, `cohesion` for scoping conventions to codebase areas |
| Impact (Layer D) | `stability` for identifying hub files in import analysis |

### Observation log (from `.speed/memory/observations/*.jsonl`) **[EXISTING]**

Phase B reads observation types that carry convention-relevant evidence:

| Observation type | Convention signal |
|-----------------|-------------------|
| `reviewer_finding` with `category: "convention"` | Direct evidence of a convention the system doesn't know |
| `human_override` with `change_category: "convention"` | Human corrected a convention violation SPEED missed |
| `human_override` with `change_category: "style"` | Code aesthetics the human cares about |
| `convention_violation` | Reviewer or human flagged a pattern deviation |

### Git history **[EXISTING]**

`git log --numstat` across all commits (not just SPEED runs). Provides co-modification pairs and change velocity per file.

### Tree-sitter AST **[EXISTING]**

Uses `lib/context/treesitter_extract.py` (ast-grep rules for Python and TypeScript/JavaScript). Validated capabilities:

- **Import analysis**: structured import data with module names. Detects test frameworks (vitest vs jest), test libraries (@testing-library/react), mocking patterns (vi.mock), lifecycle hooks (beforeEach/afterEach).
- **Function/method names**: extracted for naming convention detection (camelCase vs snake_case via regex).
- **Class names**: extracted for PascalCase detection.

Not currently extractable (fields exist in schema but ast-grep rules don't populate them):
- Decorator usage, fixture patterns, assertion style, try/except structure.

### Lock files / manifests **[EXISTING]**

`requirements.txt`, `pyproject.toml`, `package.json`, `Cargo.toml`, or equivalent. Provides dependency inventory, version pins, and core vs. peripheral library distinction.

### Linter / formatter configs **[EXISTING]**

ESLint, Ruff, Prettier, tsconfig, golangci-lint, Clippy, Biome. Phase 0 reads these directly. See Phase 0 section for the full supported config table.

### Project knowledge (from `.speed/memory/project-knowledge.json`) **[NEW]**

Human-maintained knowledge entries. Read by assembly functions for prompt injection alongside conventions. Not produced or modified by convention discovery. See the Project Knowledge Pipeline section for how entries get into this file.

## Output Contract

### Convention Discovery outputs

#### conventions.json **[NEW]**

**Schema:**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["conventions", "conflicts", "views"],
  "properties": {
    "conventions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "convention", "scope", "confidence", "tags", "evidence", "source"],
        "properties": {
          "id":                { "type": "string", "pattern": "^conv-" },
          "convention":        { "type": "string", "minLength": 10 },
          "scope":             { "type": "array", "items": { "type": "string" }, "minItems": 1 },
          "confidence":        { "type": "string", "enum": ["established", "emerging", "decaying", "conflict"] },
          "canonical_example": { "type": ["string", "null"] },
          "exceptions":        { "type": ["string", "null"] },
          "evolution":         {
            "oneOf": [
              { "type": "null" },
              {
                "type": "object",
                "required": ["old_pattern", "new_pattern", "old_files", "transition_started"],
                "properties": {
                  "old_pattern":         { "type": "string" },
                  "new_pattern":         { "type": "string" },
                  "old_files":           { "type": "array", "items": { "type": "string" } },
                  "transition_started":  { "type": "string" },
                  "note":                { "type": ["string", "null"] }
                }
              }
            ]
          },
          "tags":   { "type": "array", "items": { "type": "string" } },
          "evidence": {
            "type": "object",
            "required": ["code_adherence", "observation_support"],
            "properties": {
              "code_adherence":      { "type": "string" },
              "observation_support":  { "type": "integer", "minimum": 0 },
              "observations":         { "type": "array", "items": { "type": "string" } }
            }
          },
          "source": { "type": "string", "enum": ["config", "discovered"] }
        }
      }
    },
    "conflicts": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["area", "pattern_a", "pattern_b", "auto_resolved", "evidence"],
        "properties": {
          "area":          { "type": "string" },
          "pattern_a":     { "type": "string" },
          "pattern_b":     { "type": "string" },
          "auto_resolved": { "type": "boolean" },
          "resolution":    { "type": ["string", "null"] },
          "evidence":      { "type": "string" }
        }
      }
    },
    "views": {
      "type": "object",
      "required": ["developer", "reviewer", "architect"],
      "properties": {
        "developer": { "type": "string" },
        "reviewer":  { "type": "string" },
        "architect": { "type": "string" }
      }
    }
  }
}
```

**Confidence levels:**

| Level | Meaning | Threshold |
|-------|---------|-----------|
| `established` | Violations are bugs. Flag on sight | 90%+ of files in scope follow the pattern AND corroborated by a second data source |
| `emerging` | New code should follow. Old code may not | 60-89% adherence, OR 3+ observation entries support it |
| `decaying` | Old convention being replaced. Do NOT follow | Recent code deviates while older code follows |
| `conflict` | Two competing patterns. Document both | Neither pattern dominant; no observation evidence to auto-resolve |

**Example:**

```json
{
  "conventions": [
    {
      "id": "conv-parametrize",
      "convention": "Tests use pytest.mark.parametrize for config variations",
      "scope": ["tests/"],
      "confidence": "established",
      "canonical_example": "tests/test_toml.py:45",
      "exceptions": null,
      "evolution": null,
      "tags": ["testing"],
      "evidence": {
        "code_adherence": "18 of 20 test files",
        "observation_support": 0
      },
      "source": "discovered"
    },
    {
      "id": "conv-isinstance-guard",
      "convention": "Validate dict types with isinstance before .get() calls",
      "scope": ["lib/"],
      "confidence": "emerging",
      "canonical_example": "lib/toml.py:78",
      "exceptions": null,
      "evolution": null,
      "tags": ["correctness"],
      "evidence": {
        "code_adherence": "12 of 18 lib files",
        "observation_support": 3,
        "observations": ["convention_violation x3 across features 3, 5, 7"]
      },
      "source": "discovered"
    },
    {
      "id": "conv-ruff-import-ordering",
      "convention": "Import ordering enforced by ruff (isort rules enabled)",
      "scope": ["lib/", "tests/"],
      "confidence": "established",
      "canonical_example": "pyproject.toml",
      "exceptions": null,
      "evolution": null,
      "tags": ["import", "formatting"],
      "evidence": {
        "code_adherence": "N/A — enforced by linter",
        "observation_support": 0
      },
      "source": "config"
    }
  ],
  "conflicts": [
    {
      "area": "lib/api/",
      "pattern_a": "Return-code error handling (4 files, features 1-3)",
      "pattern_b": "Exception-based error handling (3 files, features 4+)",
      "auto_resolved": true,
      "resolution": "current = exception-based, decaying = return-code",
      "evidence": "Reviewer flagged return-code style 2x"
    }
  ],
  "views": {
    "developer": "### Project Conventions\n\n**Implementation patterns:**\n- ...",
    "reviewer": "### Convention Checklist\n\n**Flag if:**\n- ...",
    "architect": "### Structural Conventions\n\n- ..."
  }
}
```

#### conventions-meta.json **[NEW]**

**Schema:**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["last_run", "files_analyzed", "cluster_checksums", "observation_count_at_run", "trigger"],
  "properties": {
    "last_run":                     { "type": "string", "format": "date-time" },
    "files_analyzed":               { "type": "integer", "minimum": 0 },
    "cluster_checksums":            { "type": "object", "additionalProperties": { "type": "string" } },
    "observation_count_at_run":     { "type": "integer", "minimum": 0 },
    "convention_violation_count_at_run": { "type": "integer", "minimum": 0 },
    "trigger":                      { "type": "string", "enum": ["first_run", "files_changed", "features_completed", "csg_restructured", "violations_threshold", "manual"] }
  }
}
```

**Example:**

```json
{
  "last_run": "2026-03-09T10:00:00Z",
  "files_analyzed": 42,
  "cluster_checksums": {
    "cluster_context_3": "sha256:a1b2c3d4e5f6...",
    "cluster_api_1": "sha256:d4e5f6a1b2c3..."
  },
  "observation_count_at_run": 47,
  "convention_violation_count_at_run": 8,
  "trigger": "manual"
}
```

#### conventions-candidates.json **[NEW]**

Convention entries that failed the quality bar, stored for potential future promotion when more evidence accumulates. Same entry schema as `conventions[].items` above.

**Schema:**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "array",
  "items": {
    "type": "object",
    "required": ["id", "convention", "scope", "confidence", "tags", "evidence", "source", "rejection_reason"],
    "properties": {
      "id":                { "type": "string", "pattern": "^conv-" },
      "convention":        { "type": "string" },
      "scope":             { "type": "array", "items": { "type": "string" } },
      "confidence":        { "type": "string", "enum": ["established", "emerging", "decaying", "conflict"] },
      "canonical_example": { "type": ["string", "null"] },
      "exceptions":        { "type": ["string", "null"] },
      "evolution":         { "type": ["object", "null"] },
      "tags":              { "type": "array", "items": { "type": "string" } },
      "evidence":          { "type": "object" },
      "source":            { "type": "string", "enum": ["config", "discovered"] },
      "rejection_reason":  { "type": "string", "enum": ["not_actionable", "not_project_specific", "not_evidenced", "not_scoped", "redundant", "no_matching_template"] }
    }
  }
}
```

**Example:**

```json
[
  {
    "id": "conv-candidate-meaningful-names",
    "convention": "Use meaningful variable names",
    "scope": ["lib/"],
    "confidence": "emerging",
    "canonical_example": null,
    "exceptions": null,
    "evolution": null,
    "tags": ["naming"],
    "evidence": {
      "code_adherence": "N/A",
      "observation_support": 1
    },
    "source": "discovered",
    "rejection_reason": "not_project_specific"
  }
]
```

### Project Knowledge outputs

These are produced by the knowledge pipeline (`speed learn --seed-knowledge`, staleness detection, system-prompted gaps), not by convention discovery.

#### project-knowledge.json **[NEW]**

Human-maintained. The system never writes to this file directly. The human reviews drafts and promotes accepted entries here. Only entries in this file reach agent prompts.

**Schema:**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["entries"],
  "properties": {
    "entries": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "knowledge", "applies_to", "agents", "tags", "source"],
        "properties": {
          "id":              { "type": "string", "pattern": "^pk-" },
          "knowledge":       { "type": "string", "minLength": 10 },
          "why_it_matters":  { "type": ["string", "null"] },
          "applies_to":      { "type": "array", "items": { "type": "string" }, "minItems": 1 },
          "agents":          { "type": "array", "items": { "type": "string", "enum": ["developer", "reviewer", "architect"] }, "minItems": 1 },
          "tags":            { "type": "array", "items": { "type": "string" } },
          "source":          { "type": "string", "enum": ["human", "seeded"] },
          "last_verified":   { "type": ["string", "null"], "format": "date" }
        }
      }
    }
  }
}
```

**Example:**

```json
{
  "entries": [
    {
      "id": "pk-payments-async",
      "knowledge": "Payment service returns 202 for async operations. Poll /status/{id} until terminal state. Do not retry on 202.",
      "why_it_matters": "Developer attempted synchronous error handling on 202 responses in feature 3, causing test failures and 2 retries.",
      "applies_to": ["lib/api/payments.py", "lib/api/client.py"],
      "agents": ["developer", "reviewer"],
      "tags": ["api-contract", "dependency", "footgun"],
      "source": "human",
      "last_verified": "2026-03-01"
    }
  ]
}
```

#### project-knowledge-drafts.json **[NEW]**

Staging area for system-generated entries awaiting human review. Never injected into agent prompts. See the Project Knowledge Pipeline section for the three mechanisms that write to this file (seeding, system-prompted gaps, staleness detection).

**Schema:**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "array",
  "items": {
    "type": "object",
    "required": ["id", "knowledge", "applies_to", "agents", "tags", "source", "draft_reason"],
    "properties": {
      "id":              { "type": "string", "pattern": "^pk-draft-" },
      "knowledge":       { "type": "string" },
      "why_it_matters":  { "type": ["string", "null"] },
      "applies_to":      { "type": "array", "items": { "type": "string" }, "minItems": 1 },
      "agents":          { "type": "array", "items": { "type": "string", "enum": ["developer", "reviewer", "architect"] }, "minItems": 1 },
      "tags":            { "type": "array", "items": { "type": "string" } },
      "source":          { "type": "string", "enum": ["seeded", "system-prompted", "stale-flag"] },
      "draft_reason":    { "type": "string" },
      "staleness_flag":  { "type": ["string", "null"] },
      "last_verified":   { "type": ["string", "null"], "format": "date" }
    }
  }
}
```

**Example:**

```json
[
  {
    "id": "pk-draft-tomllib",
    "knowledge": "TOML parsing uses tomllib (Python 3.11+). Do not import tomli (the backport).",
    "why_it_matters": null,
    "applies_to": ["lib/toml.py"],
    "agents": ["developer"],
    "tags": ["dependency"],
    "source": "seeded",
    "draft_reason": "seeded from CLAUDE.md line 45",
    "staleness_flag": null,
    "last_verified": null
  },
  {
    "id": "pk-draft-payments-retries",
    "knowledge": "[QUESTION] Tasks touching lib/api/payments.py consistently retry. No convention or code pattern explains why. Is there an external API contract the system should know about?",
    "why_it_matters": "3 retries across 2 features with no identified root cause.",
    "applies_to": ["lib/api/payments.py"],
    "agents": ["developer"],
    "tags": ["dependency", "footgun"],
    "source": "system-prompted",
    "draft_reason": "3+ unexplained failures in tasks touching lib/api/payments.py",
    "staleness_flag": null,
    "last_verified": null
  },
  {
    "id": "pk-draft-stale-payments",
    "knowledge": "Payment service returns 202 for async operations. Poll /status/{id} until terminal state.",
    "why_it_matters": null,
    "applies_to": ["lib/api/payments-v1.py"],
    "agents": ["developer", "reviewer"],
    "tags": ["api-contract"],
    "source": "stale-flag",
    "draft_reason": "applies_to path lib/api/payments-v1.py no longer exists (renamed to payments.py)",
    "staleness_flag": "File lib/api/payments-v1.py not found in project",
    "last_verified": "2025-12-01"
  }
]
```

## Pipeline Implementation

### Module: `lib/learn/conventions.py` **[NEW]**

```python
def discover_conventions(  # NEW
    project_root: Path,
    memory_dir: Path,
    csg_path: Path | None = None,
    incremental: bool = True,
) -> ConventionResult:
    """Run the full convention discovery pipeline."""
```

### Phase 0: Config reading (no LLM) **[NEW]**

```python
def _extract_config_conventions(project_root: Path) -> list[ConventionEntry]:  # NEW
    """Read linter/formatter configs and emit established conventions directly."""
```

Scans for known config files **[EXISTING: configs already in target projects]** and maps their rules to convention entries **[NEW: mapping logic]**. Config-derived conventions skip Phase C validation (the config file is the evidence) and start at `confidence: established` with `source: config`.

| Config file | Languages | What it provides |
|-------------|-----------|-----------------|
| `.editorconfig` | All | Indent style/size, charset, trailing whitespace, final newline |
| `pyproject.toml` (ruff/black/pylint sections) | Python | Import ordering, line length, banned imports, naming rules |
| `.flake8` / `setup.cfg [flake8]` | Python | Linting rules, max line length, ignored errors |
| `.eslintrc.*` / `eslint.config.*` | JS/TS/TSX | Naming conventions, import rules, banned patterns, type strictness |
| `.prettierrc` / `prettier.config.*` | JS/TS/TSX | Formatting: tabs vs spaces, semicolons, quote style |
| `biome.json` | JS/TS/TSX | Formatting + linting (Biome projects) |
| `tsconfig.json` | TS/TSX | Strict mode, path aliases, module resolution |
| `.golangci.yml` | Go | Linting rules, banned functions, naming |
| `clippy.toml` / `.clippy.conf` | Rust | Lint levels and allowed patterns |
| `checkstyle.xml` | Java | Naming, import ordering, formatting, Javadoc rules |
| `pmd.xml` / `.pmd` | Java | Code quality rules, banned patterns |
| `.rubocop.yml` | Ruby | Naming, style, layout, lint rules |
| `.clang-format` | C/C++ | Formatting: brace style, indent, column limit |
| `.clang-tidy` | C/C++ | Lint rules, modernize checks, naming |
| `stylecop.json` / `.editorconfig` (C# sections) | C# | Naming, layout, ordering conventions |
| `.shellcheckrc` | Bash | Shell lint rules, disabled checks |

Each config file is parsed with a format-specific reader **[NEW: TOML/JSON/YAML parsers per config type]**. The canonical example for each convention is the config file path itself.

### Phase A: Mechanical extraction (no LLM) **[NEW]**

Four extractors run deterministically. Each returns a list of `RawPattern` objects.

#### A1: File co-modification **[NEW]**

```python
def _extract_comodification(project_root: Path) -> list[RawPattern]:  # NEW
    """Parse git log --numstat for co-modification pairs."""
```

Run `git log --numstat --pretty=format:"%H"` **[EXISTING: git]** across all commits. Build co-occurrence matrix and produce pairs where files are co-modified in 80%+ of commits touching either file **[NEW: co-occurrence logic]**.

Output: `RawPattern(type="comodification", files=["lib/toml.py", "templates/speed-toml.toml"], adherence=1.0, evidence="co-modified in 12 of 12 commits")`

Asymmetric co-modification also detected **[NEW]**: "changes to assembly.py always touch `__init__.py`, but not vice versa." Stored as directional pairs.

#### A2: Import and naming patterns (tree-sitter) **[NEW (uses EXISTING treesitter_extract.py)]**

```python
def _extract_imports_and_naming(project_root: Path, csg: dict) -> list[RawPattern]:  # NEW
    """Extract import patterns and naming conventions from tree-sitter output and CSG."""
```

Uses `treesitter_extract.py` **[EXISTING: ast-grep parsing infrastructure]** for structured import data and function/class name extraction. Two sub-analyses:

**Import analysis** **[NEW: aggregation logic over EXISTING tree-sitter output]**: Count framework and library usage across files. Detect:
- Test framework (vitest vs jest vs pytest) by import module names **[EXISTING: tree-sitter extracts structured imports with module names]**
- Test utilities (@testing-library/react, @testing-library/jest-dom)
- Mocking patterns (vi.mock, jest.mock)
- Lifecycle hooks (beforeEach, afterEach, beforeAll)
- Relative vs absolute import patterns per directory (from CSG edges) **[EXISTING: CSG edge data]**

**Name analysis** **[NEW: regex matching logic over EXISTING symbol data]**: Regex match against extracted function/method/class names:
- Test files: `test_<module>.py` pattern, `describe`/`it` vs `test()` style
- Function naming: camelCase vs snake_case adherence per directory
- Class names: PascalCase adherence

CSG symbol data **[EXISTING]** provides names directly (no re-parse needed for naming). Tree-sitter **[EXISTING]** provides import structure.

#### A3: Import graph (CSG) **[NEW (reads EXISTING CSG)]**

```python
def _extract_import_graph(project_root: Path, csg: dict) -> list[RawPattern]:  # NEW
    """Extract import conventions from CSG edges."""
```

CSG edge type `imports` **[EXISTING: CSG edge data]** provides the graph. Group by CSG cluster **[EXISTING: CSG cluster data]**:
- Does `lib/context/` use relative imports internally? **[NEW: per-cluster grouping logic]** (check CSG edges within cluster)
- Are there cross-boundary import conventions? **[NEW: boundary-crossing detection]** (check edges crossing cluster boundaries)
- Hub files: many importers, few imports **[NEW: hub detection logic]** (from CSG Impact layer stability scores **[EXISTING]**)

#### A4: Dependency usage patterns **[NEW]**

```python
def _extract_dependency_usage(project_root: Path) -> list[RawPattern]:  # NEW
    """Extract dependency inventory and wrapper patterns."""
```

Read lock files **[EXISTING: lock files in target projects]** for dependency inventory **[NEW: parsing logic per lock file format]**. Search for wrapper modules **[NEW: wrapper detection algorithm]**: files that import a library and re-export a project-specific interface. Detect via import analysis: if `lib/api/client.py` imports `httpx` and other files import `lib/api/client` but never import `httpx` directly, that's a wrapper convention.

### Phase B: Observation integration (no LLM) **[NEW (reads EXISTING observation log)]**

```python
def _integrate_observations(  # NEW
    raw_patterns: list[RawPattern],
    obs_dir: Path,
) -> list[RawPattern]:
    """Enrich patterns with observation log evidence."""
```

Read observation JSONL files **[EXISTING: observation log format and files]**. Filter for convention-relevant types **[NEW: filtering logic]** (see Input Contract table). For each raw pattern, check if observations corroborate or challenge it **[NEW: correlation logic]**:

- 3+ `convention_violation` observations **[EXISTING: observation type]** about isinstance checks + AST shows 60% adherence → strengthen to `emerging` **[NEW: strengthening rule]**
- 2 `human_override` entries **[EXISTING: observation type]** replacing raw httpx with the project wrapper → create new pattern even if AST didn't find one **[NEW: observation-only pattern creation]**
- `reviewer_finding` with category "convention" **[EXISTING: observation type]** → increment `observation_support` count on matching patterns **[NEW: correlation counter]**

Patterns that exist only in observations (no code pattern found) get created with `confidence: "emerging"` and `evidence.code_adherence: "N/A — observation-derived"` **[NEW: observation-derived convention creation]**.

### Phase C: Template formatting and validation (no LLM) **[NEW]**

```python
def _format_and_validate(  # NEW
    enriched_patterns: list[RawPattern],
    config_conventions: list[ConventionEntry],
) -> tuple[list[ConventionEntry], list[ConventionEntry]]:
    """Apply templates, quality bar, assign confidence. Returns (passed, rejected)."""
```

Converts raw Phase A patterns and Phase B observations into convention entries using deterministic templates **[NEW: entire template engine]**. Each pattern type has a corresponding template that generates convention text, scope, and canonical example.

```python
CONVENTION_TEMPLATES = {  # NEW

    # ── Co-modification ───────────────────────────────────────────────
    "comodification":      "Always modify `{file_a}` and `{file_b}` together. "
                           "Co-modified in {commits}/{total} commits ({rate:.0%}).",

    # ── Naming: base casing patterns ──────────────────────────────────
    "naming_snake":        "Use snake_case for {entity_type} in `{scope}`. "
                           "{adherence:.0%} of {count} {entity_type}s follow this pattern.",
    "naming_camel":        "Use camelCase for {entity_type} in `{scope}`. "
                           "{adherence:.0%} of {count} {entity_type}s follow this pattern.",
    "naming_pascal":       "Use PascalCase for {entity_type} in `{scope}`. "
                           "{adherence:.0%} of {count} {entity_type}s follow this pattern.",
    "naming_upper_snake":  "Use UPPER_SNAKE_CASE for {entity_type} in `{scope}`. "
                           "{adherence:.0%} of {count} {entity_type}s follow this pattern.",

    # ── Naming: language-specific patterns ────────────────────────────
    "naming_go_exported":  "Exported symbols use PascalCase, unexported use camelCase in `{scope}`. "
                           "Go visibility-by-capitalization. {adherence:.0%} adherence.",
    "naming_cs_interface": "Interfaces use I prefix (e.g., IRepository) in `{scope}`. "
                           "{adherence:.0%} of {count} interfaces follow this pattern.",
    "naming_cs_async":     "Async methods use Async suffix in `{scope}`. "
                           "{adherence:.0%} of {count} async methods follow this pattern.",
    "naming_react_component": "React components use PascalCase in `{scope}`. "
                              "{adherence:.0%} of {count} components follow this pattern.",
    "naming_react_hook":   "Custom hooks use `use` prefix in `{scope}`. "
                           "{adherence:.0%} of {count} hooks follow this pattern.",
    "naming_bool_prefix":  "Boolean functions/variables use {prefixes} prefix in `{scope}`. "
                           "{adherence:.0%} of {count} boolean names follow this pattern.",
    "naming_ruby_predicate": "Predicate methods end with `?` in `{scope}`. "
                             "{adherence:.0%} of {count} boolean methods follow this pattern.",
    "naming_ruby_bang":    "Mutating methods end with `!` in `{scope}`. "
                           "{adherence:.0%} of {count} mutating methods follow this pattern.",

    # ── Naming: test file/function patterns ───────────────────────────
    "naming_test_prefix":  "Test files use `{prefix}` prefix in `{scope}`. "
                           "{adherence:.0%} of {count} test files follow this pattern.",
    "naming_test_suffix":  "Test files use `{suffix}` suffix in `{scope}`. "
                           "{adherence:.0%} of {count} test files follow this pattern.",

    # ── Imports ───────────────────────────────────────────────────────
    "import_relative":     "Use relative imports within `{directory}`. "
                           "Absolute imports elsewhere. {adherence:.0%} adherence.",

    # ── Test framework ────────────────────────────────────────────────
    "test_framework":      "Use {framework} for tests in `{scope}`. "
                           "Detected in {count}/{total} test files.",

    # ── Config-derived ────────────────────────────────────────────────
    "config_rule":         "{description} (from `{config_file}`).",

    # ── Dependency usage ──────────────────────────────────────────────
    "wrapper_module":      "Use `{wrapper}` for {library} calls. "
                           "Never import {library} directly. {importers} files use the wrapper.",
}
```

Template selection is keyed on the pattern `type` field emitted by Phase A. Patterns with no matching template go to `conventions-candidates.json` for human review rather than being silently dropped.

Config-derived conventions (from Phase 0) bypass template formatting. They arrive as fully-formed `ConventionEntry` objects and only pass through the quality bar for consistency.

**What templates can't do:** Structural patterns ("where does validation live"), error handling strategies ("per-layer approach"), and dependency wrapper purposes require understanding that templates can't provide. These categories will either be absent from conventions.json or require the human to author them as project-knowledge entries. Phase B partially compensates: repeated reviewer observations about the same structural issue eventually become an emerging convention.

#### Quality bar **[NEW]**

Every entry must pass all six checks. The first four evaluate convention quality. The last two are structural filters applied during template formatting.

| Check | Criterion | Failure → `rejection_reason` |
|-------|-----------|------------------------------|
| Actionable | An agent can follow it without interpretation | `not_actionable` ("Use meaningful names") |
| Project-specific | Not a generic best practice | `not_project_specific` ("Write unit tests") |
| Evidenced | Points to 2+ concrete examples in the codebase | `not_evidenced` (no canonical_example) |
| Scoped | Specifies where it applies (file paths or cluster) | `not_scoped` (no `scope` field) |
| Not redundant | No existing convention covers the same pattern in the same scope | `redundant` (duplicate of an established convention) |
| Template matched | A `CONVENTION_TEMPLATES` key exists for this pattern type | `no_matching_template` (novel pattern type with no formatter) |

Entries failing any check go to `conventions-candidates.json` with the corresponding `rejection_reason`.

#### Confidence assignment **[NEW]**

Confidence is assigned from enriched evidence, never from a single data source:

```python
def _assign_confidence(pattern: RawPattern) -> str:  # NEW
    if pattern.code_adherence >= 0.9 and pattern.observation_support >= 1:
        return "established"
    if pattern.code_adherence >= 0.6 or pattern.observation_support >= 3:
        return "emerging"
    if pattern.recent_trend == "away":
        return "decaying"
    return "emerging"  # default for observation-derived patterns
```

`established` always requires two data sources (code adherence AND at least one observation or git history corroboration). A single AST scan finding 95% adherence is not enough: the 5% might be the intended direction.

#### Evolution tracking **[NEW]**

When both old and new patterns exist for the same scope, the entry includes an `evolution` field:

```json
{
  "evolution": {
    "old_pattern": "Return-code error handling",
    "old_files": ["lib/api/legacy.py", "lib/api/auth.py"],
    "new_pattern": "Exception-based error handling",
    "transition_started": "feature 4",
    "note": "Do not follow old pattern. Do not refactor old code unless task requires it."
  }
}
```

#### Conflict handling **[NEW]**

Contradictory patterns in the same scope produce a `conflict` entry if observation evidence cannot auto-resolve. When observation evidence is available (reviewer flagged one pattern as wrong), auto-resolution assigns `decaying` to the losing pattern and `emerging` or `established` to the winner.

### Incremental discovery **[NEW]**

After the first full scan, subsequent runs are incremental **[NEW: incremental logic]**:

1. Read `conventions-meta.json` **[NEW]** for last run state
2. Compute current cluster checksums from CSG **[EXISTING: CSG cluster data]**
3. Compare files modified since last run (`git diff --name-only` **[EXISTING: git]** against `conventions-meta.json.last_run`)

| Condition | Action |
|-----------|--------|
| Fewer than 10 files changed, no cluster restructuring | Re-run Phase A extractors only on changed files. Phase B on new observations only. Re-run Phase C formatting on affected conventions. |
| 10-49 files changed, clusters unchanged | Re-run Phase A on changed clusters. Full Phase B. Full Phase C. |
| 50+ files changed OR cluster structure changed | Full rescan (all phases on all files) |
| Trigger: 5+ convention_violation observations since last run | Re-run Phases A-C on the categories those violations relate to |

### Trigger conditions **[NEW]**

```python
def _should_run_discovery(memory_dir: Path, project_root: Path) -> tuple[bool, str]:  # NEW
    """Check if any trigger condition is met. Returns (should_run, trigger_reason)."""
```

| Trigger | Check |
|---------|-------|
| First run | `conventions-meta.json` does not exist |
| 50+ files changed | `git diff --name-only` since last run timestamp |
| 3+ features completed | Count feature JSONL files in `observations/` since `conventions-meta.json.last_run` timestamp |
| CSG restructuring | Compare cluster checksums |
| 5+ convention violations | Count `convention_violation` observations since last run |
| Manual | `speed learn --conventions` |

## Project Knowledge Pipeline

### Module: `lib/learn/project_knowledge.py` **[NEW]**

#### Seeding **[NEW]**

```python
def seed_knowledge(project_root: Path, memory_dir: Path) -> list[DraftEntry]:  # NEW
    """Scan project artifacts for existing knowledge. Write to project-knowledge-drafts.json."""
```

Scans:
- `README.md`, `CLAUDE.md`, `CONTRIBUTING.md`
- `docs/adr/` or `docs/decisions/` (ADR documents)
- Inline comments containing: `IMPORTANT:`, `NOTE:`, `HACK:`, `ASSUMPTION:`, `DO NOT`, `NEVER`, `ALWAYS`
- `.env.example` for environment variable documentation

Each discovered piece of knowledge becomes a draft entry with `source: "seeded"`. Written to `project-knowledge-drafts.json`, never directly to `project-knowledge.json`.

#### System-prompted gaps **[NEW]**

```python
def detect_knowledge_gaps(memory_dir: Path) -> list[DraftEntry]:  # NEW
    """Generate questions from unexplained recurring failures."""
```

Read observations. Group retries by codebase area. For areas with 3+ retries and no matching convention or existing project-knowledge entry, generate a draft question:

```json
{
  "id": "pk-draft-payments-retries",
  "knowledge": "[QUESTION] The Developer consistently retries when tasks touch lib/api/payments.py. No convention or code pattern explains why. Is there an external API contract or dependency constraint the system should know about?",
  "applies_to": ["lib/api/payments.py"],
  "agents": ["developer"],
  "tags": ["dependency", "footgun"],
  "source": "system-prompted"
}
```

#### Staleness detection **[NEW]**

```python
def check_staleness(project_root: Path, memory_dir: Path) -> list[DraftEntry]:  # NEW
    """Cross-reference project-knowledge entries against current codebase."""
```

For each entry in `project-knowledge.json`:
- Check `applies_to` file paths still exist
- Check dependency versions mentioned in `knowledge` text against lock files
- Check `last_verified` age (flag if > 90 days)

Stale entries produce draft flags in `project-knowledge-drafts.json` with `source: "stale-flag"`.

## Per-Agent Formatting **[NEW]**

Conventions and project knowledge are formatted differently for each consuming agent. Per-agent convention views are pre-formatted at discovery time and stored in `conventions.json`. Project knowledge is formatted at injection time (in the bridge functions) since it's human-maintained and may change between discovery runs.

### Developer view (implementation guidance)

```markdown
### Project Conventions

**Implementation patterns:**
- Use relative imports within `lib/context/`. Absolute imports everywhere else. (ref: `lib/context/assembly.py:12`)
- HTTP calls go through `lib/api/client.py:fetch()`, never raw httpx. (ref: `lib/api/client.py:12`)
- New pipeline stages follow: cmd → agent prompt → assembly function → tests. (ref: `lib/cmd/review.sh`)

**Known pitfalls:**
- Validate dict types with isinstance before `.get()` calls. (emerging — 3 reviewer findings)
- Always update `templates/speed-toml.toml` when modifying `lib/toml.py`. (established — co-modified 12/12 commits)

**Project knowledge:**
- Payment service returns 202 for async operations. Poll `/status/{id}` until terminal state. Do not retry on 202.
```

### Reviewer view (flag/don't-flag checklist)

```markdown
### Convention Checklist

**Flag if:**
- [ ] Direct httpx calls outside `lib/api/client.py`
- [ ] `unittest.TestCase` subclass (project uses bare pytest functions)
- [ ] Absolute imports within `lib/context/` (except known cross-boundary cases)
- [ ] Missing isinstance check before `.get()` on untrusted dicts

**Do NOT flag:**
- Return-code error handling in `lib/api/legacy.py` (known old pattern, not yet migrated)
- `__init__.py` import additions (cascading from new modules)
```

### Architect view (structural constraints)

```markdown
### Structural Conventions

- New pipeline stages require files in three locations: `lib/cmd/`, `agents/`, `lib/context/assembly.py`
- The context layer (`lib/context/`) uses relative imports. Tasks spanning context and cmd need to account for the boundary.
- Error handling conventions differ by layer (API: exceptions, CLI: exit codes). Don't bundle cross-layer error handling in the same task.
- `lib/toml.py` and `templates/speed-toml.toml` are always co-modified. Bundle them.
```

## Injection **[MODIFIED (adds to EXISTING assembly/bridge pattern)]**

Follows the existing pattern from synthesis injection. Each bridge function in `lib/context_bridge.sh` gains a conventions + project knowledge preparation step.

```python
# In context_assemble_developer's Python block:  # MODIFIED — new imports added to EXISTING bridge function
from lib.learn.conventions import format_conventions_for_agent, format_knowledge_for_agent  # NEW
from pathlib import Path

memory_dir = Path(project_root) / ".speed" / "memory"
conventions_path = memory_dir / "conventions.json"
knowledge_path = memory_dir / "project-knowledge.json"
task_files = task.get("files_to_modify", []) + task.get("files_to_create", [])

conventions_md = format_conventions_for_agent(conventions_path, "developer", task_files)
knowledge_md = format_knowledge_for_agent(knowledge_path, "developer", task_files)
```

Assembly functions gain two new optional parameters. Conventions and knowledge sections are inserted **before** learnings in all three functions (static/deterministic knowledge ranks above observation-derived learnings). The placement follows the module's ordering principle: constraints before material.

### `assemble_developer` **[MODIFIED]**

```python
def assemble_developer(
    task: dict,
    code_context: dict,
    task_context: dict,
    spec_context: dict,
    budget: dict | None = None,
    cross_cutting_concerns: list[str] | None = None,
    branch_name: str = "",
    worktree_path: str = "",
    feature_name: str = "",
    config: dict | None = None,
    learnings: str = "",
    conventions: str = "",          # NEW
    project_knowledge: str = "",    # NEW
) -> str:
    ...
    # After "Cross-Cutting Constraints" section,
    # before "Learned Patterns":

    # ── Project Conventions ──────────────────────────────  # NEW
    if conventions:
        sections.append(f"### Project Conventions\n\n{conventions}\n")
        total_budget -= estimate_tokens_from_text(conventions)

    # ── Project Knowledge ────────────────────────────────  # NEW
    if project_knowledge:
        sections.append(f"### Project Knowledge\n\n{project_knowledge}\n")
        total_budget -= estimate_tokens_from_text(project_knowledge)

    # ── Learned Patterns ─────────────────────────────────  # EXISTING (unchanged)
    if learnings:
        sections.append(f"### Learned Patterns\n\n{learnings}\n")
        total_budget -= estimate_tokens_from_text(learnings)
```

### `assemble_reviewer` **[MODIFIED]**

```python
def assemble_reviewer(
    task: dict,
    diff: str,
    task_context: dict,
    spec_context: dict,
    csg: dict | None = None,
    cross_cutting_concerns: list[str] | None = None,
    criteria_results: list[dict] | None = None,
    config: dict | None = None,
    learnings: str = "",
    conventions: str = "",          # NEW
    project_knowledge: str = "",    # NEW
) -> str:
    ...
    # After "Assumptions to Verify" section,
    # before "Review Calibration":

    # ── Convention Checklist ─────────────────────────────  # NEW
    if conventions:
        sections.append(f"### Convention Checklist\n\n{conventions}\n")
        total_budget -= estimate_tokens_from_text(conventions)

    # ── Project Knowledge ────────────────────────────────  # NEW
    if project_knowledge:
        sections.append(f"### Project Knowledge\n\n{project_knowledge}\n")
        total_budget -= estimate_tokens_from_text(project_knowledge)

    # ── Review Calibration ───────────────────────────────  # EXISTING (unchanged)
    if learnings:
        sections.append(f"### Review Calibration\n\n{learnings}\n")
        total_budget -= estimate_tokens_from_text(learnings)
```

### `assemble_architect` **[MODIFIED]**

```python
def assemble_architect(
    project_map: dict,
    csg: dict,
    spec_alignment: dict | None = None,
    config: dict | None = None,
    learnings: str = "",
    conventions: str = "",          # NEW
    project_knowledge: str = "",    # NEW
) -> str:
    ...
    # After "Directory Structure" section,
    # before "Project History":

    # ── Structural Conventions ───────────────────────────  # NEW
    if conventions:
        sections.append(f"### Structural Conventions\n\n{conventions}\n")
        total_budget -= estimate_tokens_from_text(conventions)

    # ── Project Knowledge ────────────────────────────────  # NEW
    if project_knowledge:
        sections.append(f"### Project Knowledge\n\n{project_knowledge}\n")
        total_budget -= estimate_tokens_from_text(project_knowledge)

    # ── Project History ──────────────────────────────────  # EXISTING (unchanged)
    if learnings:
        sections.append(f"### Project History\n\n{learnings}\n")
        total_budget -= estimate_tokens_from_text(learnings)
```

### Token budgets **[NEW]**

Every stage already allocates a 10% reserve in `STAGE_ALLOCATIONS` (`lib/context/budget.py:30-68`). `apply_budget()` computes the reserve as a single number and returns it in the budget dict, but does not subdivide it. The actual subdivision happens inside the assembly functions themselves: each `sections.append(...)` call is followed by a `total_budget -= estimate_tokens_from_text(...)` deduction, so later sections naturally receive whatever remains.

Conventions and project knowledge share this reserve with learnings. No changes to `STAGE_ALLOCATIONS` or `get_context_budgets()` are required.

**Reserve pool by agent:**

| Agent | Total budget | Reserve (10%) | Conventions | Knowledge | Learnings (remainder) |
|-------|-------------|---------------|-------------|-----------|----------------------|
| Developer | 80,000 | 8,000 | up to 2,000 | up to 1,500 | up to 4,500 |
| Reviewer | 60,000 | 6,000 | up to 2,000 | up to 1,500 | up to 2,500 |
| Architect | 60,000 | 6,000 | up to 2,000 | up to 1,500 | up to 2,500 |

**Priority when the reserve is exceeded** (enforced by insertion order in the assembly functions):

1. **Conventions** (deterministic, config-backed) — appended first, deducts from `total_budget`
2. **Project knowledge** (human-curated) — appended second, deducts from what remains
3. **Learnings** (observation-derived) — appended last, gets whatever is left

Because the assembly functions call `_truncate()` on the final output against `total_budget`, any content that collectively exceeds the budget gets trimmed from the end. Learnings sit at the end of the section order, so they are the first to be cut. `format_conventions_for_agent` and `format_knowledge_for_agent` (in `lib/learn/conventions.py`) also accept a `max_tokens` parameter to pre-truncate before the string reaches assembly, preventing over-allocation at the source.

## CLI Integration

### `speed learn --conventions` **[MODIFIED (new flag in EXISTING learn.sh)]**

```bash
# In lib/cmd/learn.sh:  # MODIFIED
if [[ "$1" == "--conventions" ]]; then
    learn_conventions
    return $?
fi
```

Bridge function in `lib/learn_bridge.sh`:

```bash
learn_conventions() {  # NEW
    $(_learn_python) <<PYTHON_EOF
import sys, os
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))
from pathlib import Path
from lib.learn.conventions import discover_conventions

project_root = Path(os.environ.get("PROJECT_ROOT", "."))
memory_dir = project_root / ".speed" / "memory"
csg_path = project_root / ".speed" / "context" / "semantic-graph.json"

result = discover_conventions(project_root, memory_dir, csg_path)
print(result.summary())
PYTHON_EOF
}
```

### `speed learn --seed-knowledge` **[MODIFIED (new flag in EXISTING learn.sh)]**

```bash
learn_seed_knowledge() {  # NEW
    # ... calls project_knowledge.seed_knowledge()
    # Prints: "Generated N draft entries in project-knowledge-drafts.json. Review and promote to project-knowledge.json."
}
```

### Automatic trigger **[MODIFIED (new hook in EXISTING learn flow)]**

Convention discovery checks trigger conditions during `speed learn` (post-integrate). If any trigger is met, discovery runs automatically after observation extraction.

## Data Model

```python
@dataclass
class RawPattern:  # NEW
    type: str          # "comodification", "naming", "import", "test_framework", "dependency"
    files: list[str]
    scope: list[str]
    adherence: float   # 0.0-1.0, fraction of files in scope following the pattern
    evidence: str
    observation_support: int = 0
    recent_trend: str = "stable"  # "stable", "toward", "away"

@dataclass
class ConventionEntry:  # NEW
    id: str
    convention: str
    scope: list[str]
    confidence: str     # "established", "emerging", "decaying", "conflict"
    canonical_example: str
    exceptions: str | None
    evolution: dict | None
    tags: list[str]
    evidence: dict
    source: str         # "config" or "discovered"

@dataclass
class ConventionResult:  # NEW
    conventions: list[ConventionEntry]
    conflicts: list[dict]
    candidates: list[ConventionEntry]  # failed quality bar
    meta: dict

    def summary(self) -> str:
        """Format summary for CLI output."""
```

## State Machine

Three stateful entities with defined transitions.

### Convention confidence lifecycle

```
                    ┌─────────────────────────────────────────────┐
                    │                                             │
                    ▼                                             │
  ┌─────────┐   ┌──────────┐   ┌─────────────┐   ┌───────────┐  │
  │ (new     │──▶│ emerging │──▶│ established │   │ conflict  │  │
  │  pattern)│   │          │◀──│             │   │           │  │
  └─────────┘   └──────────┘   └─────────────┘   └───────────┘  │
                    │                │                  │         │
                    │                │                  │         │
                    ▼                ▼                  │         │
                ┌──────────┐                           │         │
                │ decaying │◀──────────────────────────┘         │
                │          │                                     │
                └──────┬───┘                                     │
                       │ (removed when adherence hits 0%)        │
                       └─────────────────────────────────────────┘
```

| Transition | Trigger | Conditions |
|------------|---------|------------|
| new → `emerging` | First detection by Phase A or Phase B | Pattern passes quality bar. Code adherence 60-89%, or observation_support ≥ 3, or observation-only (no code pattern). |
| new → `established` | First detection from config (Phase 0) | Config-derived conventions start at `established` with `source: config`. |
| `emerging` → `established` | Subsequent discovery run | Code adherence reaches ≥ 90% AND observation_support ≥ 1 (two corroborating sources). |
| `established` → `emerging` | Subsequent discovery run | Code adherence drops below 90%, or the corroborating observation is invalidated by a newer `human_override`. |
| `established` → `decaying` | Subsequent discovery run | Recent code (last 3 features) deviates while older code follows. Evolution field populated with old/new pattern. |
| `emerging` → `decaying` | Subsequent discovery run | Same as above. Recent trend is "away". |
| any → `conflict` | Subsequent discovery run | Two competing patterns detected in the same scope. Neither is dominant. No observation evidence to auto-resolve. |
| `conflict` → `established` or `emerging` | Subsequent discovery run | Observation evidence arrives (e.g., reviewer flags one pattern as wrong). Winning pattern gets `established` or `emerging`; losing pattern gets `decaying`. |
| `decaying` → removed | Subsequent discovery run | Code adherence drops to 0% in scope (all files migrated). Entry removed from conventions.json. |

### Discovery run state (conventions-meta.json)

```
  ┌────────────┐     trigger met      ┌────────────┐
  │  no meta   │────────────────────▶│  running    │
  │  (first    │                      │  (full      │
  │   run)     │                      │   scan)     │
  └────────────┘                      └──────┬─────┘
                                             │ completes
                                             ▼
                ┌──────────┐          ┌────────────┐
                │ running  │◀─────── │   idle      │
                │ (partial │ trigger  │  (meta      │
                │  or full)│  met     │   exists)   │
                └────┬─────┘          └──────┬─────┘
                     │ completes              │
                     └───────────────────────▶│
                                              │ no trigger
                                              ▼
                                      ┌────────────┐
                                      │  skipped   │
                                      └────────────┘
```

| State | Condition | Action |
|-------|-----------|--------|
| No meta (first run) | `conventions-meta.json` does not exist | Full scan: all phases, all files |
| Idle | Meta exists, no trigger condition met | Skip. Return immediately. |
| Running (full) | 50+ files changed, cluster restructure, or manual `--conventions` | Re-run all phases on all files |
| Running (partial) | < 50 files changed, no cluster restructure | Phase A on changed files/clusters only. Phase B on new observations. Phase C on affected conventions. |

### Draft entry lifecycle (project-knowledge-drafts.json)

```
  ┌──────────────┐      ┌───────────────┐      ┌──────────────────┐
  │   seeded     │      │ system-       │      │   stale-flag     │
  │  (from docs) │      │ prompted      │      │  (existing entry │
  │              │      │ (from gaps)   │      │   flagged stale) │
  └──────┬───────┘      └───────┬───────┘      └────────┬─────────┘
         │                      │                        │
         ▼                      ▼                        ▼
  ┌─────────────────────────────────────────────────────────────┐
  │              project-knowledge-drafts.json                   │
  │              (staging area, never reaches agents)            │
  └──────────────────────────┬──────────────────────────────────┘
                             │
              human reviews  │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐  ┌──────────┐  ┌───────────┐
        │ promote  │  │  edit +  │  │  discard  │
        │ (accept  │  │ promote  │  │  (delete  │
        │  as-is)  │  │          │  │   from    │
        └────┬─────┘  └────┬─────┘  │   drafts) │
             │              │        └───────────┘
             ▼              ▼
  ┌─────────────────────────────────────────────────────────────┐
  │              project-knowledge.json                          │
  │              (canonical, reaches agent prompts)              │
  └─────────────────────────────────────────────────────────────┘
```

| Source | Entry arrives in drafts | Path to canonical file |
|--------|------------------------|----------------------|
| `seeded` | `speed learn --seed-knowledge` scans README, CLAUDE.md, etc. | Human reviews, edits if needed, moves to project-knowledge.json |
| `system-prompted` | `detect_knowledge_gaps()` finds 3+ unexplained retries | Human answers the question, writes knowledge entry |
| `stale-flag` | `check_staleness()` finds broken path, old version, or 90d age | Human verifies, updates applies_to/knowledge text, or removes |

Promotion and discard are manual operations in v1 (direct JSON editing). No automated path from drafts to canonical file exists.

## API Surface

Six public entry points across two modules. All are pure functions (no side effects beyond file I/O to `.speed/memory/`). No LLM calls.

### `discover_conventions()` — `lib/learn/conventions.py`

```python
def discover_conventions(
    project_root: Path,
    memory_dir: Path,
    csg_path: Path | None = None,
    incremental: bool = True,
) -> ConventionResult:
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_root` | `Path` | Yes | Repository root. Used for git log, config file scanning, lock file reading. |
| `memory_dir` | `Path` | Yes | `.speed/memory/` directory. Reads observations, writes conventions.json, conventions-meta.json, conventions-candidates.json. |
| `csg_path` | `Path \| None` | No | Path to `semantic-graph.json`. If None, Phase A2 name analysis uses tree-sitter only (no CSG symbol lookup), Phase A3 is skipped entirely. |
| `incremental` | `bool` | No | If True (default), check trigger conditions and skip unchanged clusters. If False, full rescan. |

**Returns:** `ConventionResult` with `.conventions`, `.conflicts`, `.candidates`, `.meta` fields.

**Side effects:** Writes `conventions.json`, `conventions-meta.json`, `conventions-candidates.json` to `memory_dir`.

**Error cases:**

| Condition | Behavior |
|-----------|----------|
| `project_root` does not exist | Raises `FileNotFoundError` |
| `memory_dir` does not exist | Creates it (including parents) |
| `csg_path` provided but file missing | Logs warning, proceeds without CSG (Phases A2 naming-only, A3 skipped) |
| Git not available or not a git repo | Phase A1 (co-modification) skipped with warning. Other phases proceed. |
| No config files found | Phase 0 returns empty list. Phases A-C proceed. |
| Malformed observation JSONL line | Line skipped with warning. Other lines processed. |

### `seed_knowledge()` — `lib/learn/project_knowledge.py`

```python
def seed_knowledge(
    project_root: Path,
    memory_dir: Path,
) -> list[DraftEntry]:
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_root` | `Path` | Yes | Repository root. Scans README.md, CLAUDE.md, CONTRIBUTING.md, ADR directories, `.env.example`, inline code comments. |
| `memory_dir` | `Path` | Yes | Writes to `project-knowledge-drafts.json`. |

**Returns:** List of `DraftEntry` objects written to drafts file.

**Side effects:** Writes or appends to `project-knowledge-drafts.json`. Never touches `project-knowledge.json`.

**Error cases:**

| Condition | Behavior |
|-----------|----------|
| No scannable files found | Returns empty list. Writes empty array to drafts file. |
| `project-knowledge-drafts.json` already exists | Merges: skips entries with duplicate `id`, appends new entries. |
| File read error on a source file | Skips file with warning, continues with others. |

### `detect_knowledge_gaps()` — `lib/learn/project_knowledge.py`

```python
def detect_knowledge_gaps(
    memory_dir: Path,
) -> list[DraftEntry]:
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `memory_dir` | `Path` | Yes | Reads `observations/*.jsonl` and existing `project-knowledge.json`. Writes to `project-knowledge-drafts.json`. |

**Returns:** List of `DraftEntry` objects with `source: "system-prompted"`.

**Error cases:**

| Condition | Behavior |
|-----------|----------|
| No observation files | Returns empty list. |
| Fewer than 3 retries in any area | No gaps detected, returns empty list. |
| `project-knowledge.json` missing | Proceeds (no existing entries to compare against). |

### `check_staleness()` — `lib/learn/project_knowledge.py`

```python
def check_staleness(
    project_root: Path,
    memory_dir: Path,
) -> list[DraftEntry]:
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_root` | `Path` | Yes | Used to verify `applies_to` file paths exist and check dependency versions in lock files. |
| `memory_dir` | `Path` | Yes | Reads `project-knowledge.json`. Writes stale flags to `project-knowledge-drafts.json`. |

**Returns:** List of `DraftEntry` objects with `source: "stale-flag"`.

**Error cases:**

| Condition | Behavior |
|-----------|----------|
| `project-knowledge.json` missing | Returns empty list (nothing to check). |
| `project-knowledge.json` malformed | Raises `json.JSONDecodeError`. |
| Lock file missing for dependency check | Skips version check for that entry, only checks file existence and age. |

### `format_conventions_for_agent()` — `lib/learn/conventions.py`

```python
def format_conventions_for_agent(
    conventions_path: Path,
    agent: str,
    task_files: list[str],
    max_tokens: int = 2000,
) -> str:
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `conventions_path` | `Path` | Yes | Path to `conventions.json`. |
| `agent` | `str` | Yes | One of `"developer"`, `"reviewer"`, `"architect"`. Selects the pre-built view from `views.{agent}`. |
| `task_files` | `list[str]` | Yes | Files the current task touches. Used to filter conventions by scope overlap. |
| `max_tokens` | `int` | No | Token budget for output. Default 2,000. Truncates from end if exceeded. |

**Returns:** Markdown string ready for injection into assembly, or empty string if no conventions apply.

**Error cases:**

| Condition | Behavior |
|-----------|----------|
| `conventions_path` missing | Returns `""` (graceful degradation). |
| `conventions_path` malformed JSON | Logs warning, returns `""`. |
| `agent` not in views | Returns `""`. |
| `task_files` empty | Returns full agent view (no scope filtering). |

### `format_knowledge_for_agent()` — `lib/learn/conventions.py`

```python
def format_knowledge_for_agent(
    knowledge_path: Path,
    agent: str,
    task_files: list[str],
    max_tokens: int = 1500,
) -> str:
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `knowledge_path` | `Path` | Yes | Path to `project-knowledge.json`. |
| `agent` | `str` | Yes | One of `"developer"`, `"reviewer"`, `"architect"`. Filters entries where `agents[]` contains this value. |
| `task_files` | `list[str]` | Yes | Files the current task touches. Filters entries where `applies_to[]` overlaps with `task_files`. |
| `max_tokens` | `int` | No | Token budget for output. Default 1,500. Truncates from end if exceeded. |

**Returns:** Markdown string ready for injection into assembly, or empty string if no knowledge applies.

**Error cases:**

| Condition | Behavior |
|-----------|----------|
| `knowledge_path` missing | Returns `""` (graceful degradation). |
| `knowledge_path` malformed JSON | Logs warning, returns `""`. |
| No entries match agent + task_files | Returns `""`. |

## Validation Rules

| Field | Constraints |
|-------|-------------|
| `ConventionEntry.id` | Must match `^conv-`. Unique within conventions.json. |
| `ConventionEntry.convention` | Minimum 10 characters. Must be a complete sentence. |
| `ConventionEntry.scope` | Non-empty array of file paths or directory globs. Each must start with a path segment (no bare wildcards). |
| `ConventionEntry.confidence` | One of: `established`, `emerging`, `decaying`, `conflict`. |
| `ConventionEntry.source` | One of: `config`, `discovered`. Config-derived entries must have `confidence: established`. |
| `ConventionEntry.evidence.code_adherence` | String describing adherence (e.g., "18 of 20 test files"). `"N/A"` only for observation-derived or config entries. |
| `ConventionEntry.evidence.observation_support` | Non-negative integer. `established` requires ≥ 1 (unless `source: config`). |
| `ConventionEntry.canonical_example` | File path with optional line number (e.g., `tests/test_toml.py:45`). Null only for config-derived entries where the config file itself is the example. |
| `ConventionEntry.evolution` | If present, `old_pattern`, `new_pattern`, `old_files`, and `transition_started` are all required. |
| `RawPattern.adherence` | Float 0.0-1.0. Cannot be negative. |
| `RawPattern.type` | One of: `comodification`, `naming`, `import`, `test_framework`, `dependency`. Must have a matching key in `CONVENTION_TEMPLATES` or the pattern goes to candidates. |
| Co-modification threshold | File pair must be co-modified in ≥ 80% of commits touching either file. Below threshold: not emitted. |
| `established` confidence | Requires `code_adherence ≥ 0.9` AND (`observation_support ≥ 1` OR `source == "config"`). A single data source at 95% adherence is NOT sufficient. |
| Quality bar: redundancy | A convention is redundant if an existing entry covers the same pattern type in an overlapping scope. The newer entry is rejected. |
| Quality bar: template match | Patterns with no matching `CONVENTION_TEMPLATES` key are rejected with `no_matching_template`. Novel pattern types require adding a template before they can become conventions. |
| `DraftEntry.id` | Must match `^pk-draft-`. Unique within project-knowledge-drafts.json. |
| `DraftEntry.source` | One of: `seeded`, `system-prompted`, `stale-flag`. Never `human` (drafts are system-generated). |
| `project-knowledge.json` entries | `source` must be `human` or `seeded`. Only entries in this file reach agent prompts. |
| Token budget: conventions | ≤ 2,000 tokens per agent. Enforced by `format_conventions_for_agent(max_tokens=2000)`. |
| Token budget: knowledge | ≤ 1,500 tokens per agent. Enforced by `format_knowledge_for_agent(max_tokens=1500)`. |

## File Impact

| File | Status | Change |
|------|--------|--------|
| `lib/learn/conventions.py` | **NEW** | Convention discovery pipeline: Phase 0, A-C (~500 lines estimated) |
| `lib/learn/project_knowledge.py` | **NEW** | Seeding, gap detection, staleness (~300 lines estimated) |
| `lib/learn_bridge.sh` | **MODIFIED** | Add `learn_conventions()` and `learn_seed_knowledge()` bridge functions |
| `lib/cmd/learn.sh` | **MODIFIED** | Add `--conventions` and `--seed-knowledge` flag handling |
| `lib/context/assembly.py` | **MODIFIED** | Add `conventions` and `project_knowledge` parameters to 3 assembly functions |
| `lib/context_bridge.sh` | **MODIFIED** | Add convention/knowledge loading to `context_assemble_developer`, `_reviewer`, `_architect` |
| `tests/test_conventions.py` | **NEW** | Unit tests for convention discovery |
| `tests/test_project_knowledge.py` | **NEW** | Unit tests for seeding, staleness, gap detection |

## Testing

### Acceptance Criteria

Verifiable behaviors that gate ship. A reviewer can confirm each without reading implementation code.

1. `speed learn --conventions` on a project with linter configs produces `conventions.json` with at least one `source: config` entry per detected config file
2. `speed learn --conventions` on a project with 20+ files and git history produces conventions covering naming patterns, co-modification pairs, and import conventions
3. Every convention entry in `conventions.json` passes the 6-check quality bar. No entry is generic ("write tests"), unscoped, or unevidenced
4. `established` conventions always have two corroborating data sources (or `source: config`). A single AST scan at 95% adherence alone never reaches `established`
5. Developer, Reviewer, and Architect each see conventions formatted for their role (implementation guidance, flag/don't-flag checklist, structural constraints respectively)
6. `project-knowledge.json` entries reach agent prompts filtered by `agents[]` and `applies_to[]` fields. An entry with `agents: ["developer"]` never appears in the Reviewer prompt
7. Missing `conventions.json` or `project-knowledge.json` at assembly time produces no crash, no error, and no conventions/knowledge section in the prompt. Pipeline continues normally
8. Incremental run after zero file changes completes in < 100ms (trigger check only, no extraction)
9. `speed learn --seed-knowledge` produces draft entries in `project-knowledge-drafts.json`, never writes directly to `project-knowledge.json`

### Risks and Coverage

| Risk | Severity | Test Approach |
|------|----------|---------------|
| Shallow git clone (CI) has truncated history, co-modification counts are wrong | High | Unit test: synthetic git log with < 10 commits. Verify co-modification still detects pairs and doesn't divide by zero |
| Malformed config file (invalid TOML/JSON/YAML) crashes Phase 0 | High | Unit test: each config parser receives malformed input. Verify warning logged + empty result, no exception propagated |
| CSG not yet generated on first run (`semantic-graph.json` missing) | Medium | Integration test: run `discover_conventions()` with `csg_path=None`. Verify Phase A2 uses tree-sitter only, Phase A3 skipped, other phases produce results |
| Observation log empty or corrupted JSONL line | Medium | Unit test: Phase B with empty observations dir, and with a JSONL file containing one valid + one malformed line. Verify malformed line skipped, valid line processed |
| Concurrent writes to conventions.json (two `speed learn --conventions` in parallel) | Low | Out of scope for v1. Document that concurrent runs produce last-writer-wins. Atomic write (write to temp, rename) mitigates partial corruption |
| Token budget exhausted by conventions alone, learnings get zero tokens | Medium | Unit test: format_conventions_for_agent with max_tokens=100 and a large conventions view. Verify output truncated to budget. Integration test: assembly with conventions exceeding reserve, verify learnings still get appended (truncated by _truncate) |
| Config parser misreads a valid config (wrong rules extracted) | Medium | Unit test per config type: known config content → expected convention entries. Regression suite |
| Project with no git history, no configs, no observations | Low | Integration test: discover_conventions on empty project. Verify empty conventions.json written, no crash |

### Test Plan

**Unit tests** (`tests/test_conventions.py`)

Phase 0 config reading:
- Each of the 16 config types: known config content → expected ConventionEntry with `source: config`, `confidence: established`
- Missing config files: no conventions from that source, no error
- Malformed config files: warning logged, empty result

Phase A extractors:
- A1 co-modification: detects pairs at 80%+ co-occurrence, skips below threshold. Asymmetric pairs detected (A→B but not B→A). Handles < 10 commits gracefully
- A2 import + naming: test framework detected (vitest vs jest vs pytest). camelCase vs snake_case adherence per directory. PascalCase for classes
- A3 import graph: relative vs absolute classified per CSG cluster. Hub files detected. Skipped when CSG missing
- A4 dependency usage: wrapper modules detected from import chain analysis

Phase B observation integration:
- Convention violations strengthen raw patterns (3+ violations → observation_support incremented)
- Human overrides create new patterns when code analysis alone didn't find them
- Patterns without observation match pass through unchanged
- Empty observation directory: returns patterns unchanged

Phase C template formatting and validation:
- Templates produce convention text from raw patterns (all 20 template keys)
- Patterns without matching template go to conventions-candidates.json with `rejection_reason: no_matching_template`
- Quality bar rejects: generic, unscoped, unevidenced, redundant
- Confidence assignment: 90%+ adherence + observation → established; 60%+ or 3+ observations → emerging
- Evolution tracking: old + new patterns in same scope → evolution field populated
- Conflict handling: contradictory patterns → conflict entry; observation evidence → auto-resolution

Incremental discovery:
- First run: full scan, conventions-meta.json created
- Second run with no changes: skipped (trigger check returns false)
- Second run with 5 changed files: Phase A on changed files only
- Cluster restructuring: full rescan triggered

**Unit tests** (`tests/test_project_knowledge.py`)

- Seeding: README with "IMPORTANT:" comments produces draft entries
- Seeding: entries go to project-knowledge-drafts.json, not project-knowledge.json
- Seeding: duplicate run merges (no duplicate IDs)
- Gap detection: 3+ unexplained retries in same area → draft question generated
- Gap detection: fewer than 3 retries → no gaps detected
- Staleness: entry referencing deleted file → flagged
- Staleness: entry referencing old dependency version → flagged
- Staleness: entry with last_verified > 90 days → flagged
- Staleness: project-knowledge.json missing → empty result
- Format for developer: conventions as implementation guidance
- Format for reviewer: conventions as flag/don't-flag checklist
- Format for architect: conventions as structural constraints

**Integration tests**

- Full pipeline on a small project (synthetic fixture): Phases 0→C produce valid conventions.json conforming to JSON schema
- Assembly functions with conventions + knowledge → sections present in prompt at correct insertion points
- Missing conventions.json → assembly continues without conventions section
- Malformed conventions.json → graceful degradation, warning logged, no crash
- CSG missing → pipeline completes with reduced output (no A3, A2 naming-only)
- `speed learn --conventions` CLI invocation → bridge function called → output files written

**End-to-end tests**

Deferred to post-Phase 2. Requires a real project with git history, config files, and observation log entries from prior SPEED runs. The integration tests with synthetic fixtures cover the critical paths.

**Visual/UI tests**

Not applicable. Convention discovery has no UI. Output is JSON files and markdown strings injected into agent prompts.

### Edge Cases

- Project with no git history (fresh init, no commits): Phase A1 returns empty list. Other phases proceed
- Project with no supported config files: Phase 0 returns empty list. Phases A-C proceed normally
- CSG exists but has zero clusters: Phase A3 runs but finds no cluster-scoped patterns. Phase A2 naming still works from symbol names
- Observation log has zero `convention_violation` entries: Phase B passes patterns through unchanged (no strengthening, no new patterns)
- conventions.json corrupted mid-write (partial JSON): `format_conventions_for_agent` catches `json.JSONDecodeError`, returns `""`, logs warning. Assembly continues without conventions
- Token budget exhausted by conventions before knowledge is appended: `_truncate()` on final output clips from end. Learnings trimmed first (last in section order), then knowledge, then conventions. Pre-truncation in formatters prevents this in practice
- Single file in project (trivial codebase): co-modification produces nothing (need 2+ files), naming produces one data point (insufficient for adherence %), import graph is empty. Only config-derived conventions survive
- Config file exists but is empty (0 bytes): parser returns empty dict, no conventions emitted, no error
- Observation JSONL with 10,000+ lines: Phase B reads all lines. Performance bounded by file I/O, not computation (no LLM calls). Acceptable for v1
- `applies_to` paths in project-knowledge.json use globs (`lib/api/*.py`): `format_knowledge_for_agent` must expand globs against `task_files` using `fnmatch`

### Out of Scope

- Performance benchmarking of the discovery pipeline on large repos (1,000+ files). Optimization deferred until real-world usage data exists
- Multi-project / monorepo setups where conventions differ per sub-project. v1 treats the entire project_root as one scope
- Languages beyond the 16 listed in the Phase 0 config table. Adding a language requires a new tree-sitter grammar in `treesitter_extract.py` (existing process via `speed add-language`)
- Convention discovery for formatting rules (tabs vs spaces, semicolons, quote style). These are fully handled by formatters (Black, Prettier, gofmt). Phase 0 reads the config; SPEED does not rediscover formatting from code
- Automated promotion of drafts from `project-knowledge-drafts.json` to `project-knowledge.json`. v1 requires manual human review and file editing
- Dashboard integration for convention visualization. Conventions are JSON files; dashboard can read them later without changes to this spec

## Security & Controls

**No new PII surfaces.** Convention discovery reads source code file paths, function names, config file contents, and git commit metadata. No user data, credentials, or personal information. Project knowledge entries are human-authored and the operator controls what goes in.

**Shell injection prevention.** Phase A1 invokes `git log --numstat --pretty=format:"%H"` via `subprocess.run()` with argument list (not shell string). The `project_root` path is validated as an existing directory before use. No user-supplied strings are interpolated into shell commands.

**Path traversal prevention.** All file paths are resolved relative to `project_root` and `memory_dir`. `Path.resolve()` is called before any file read/write to prevent `../` traversal. Config file scanning only reads files matching known config file names (allowlist, not blocklist).

**Credential exposure in seeding.** `seed_knowledge()` scans `.env.example` for environment variable documentation, not `.env` (which contains actual values). The seeding function reads only comment lines and variable names from `.env.example`, never values. If `.env` is accidentally present in the scan list, it is excluded by an explicit denylist: `.env`, `.env.local`, `*.key`, `*.pem`, `credentials.*`.

**Append-only observation reading.** Phase B reads observation JSONL files but never writes to them. Convention discovery only writes to `conventions.json`, `conventions-meta.json`, and `conventions-candidates.json`. No cross-contamination with the observation log.

**Local-only storage.** All data stays in `.speed/memory/`. No network calls. No LLM API calls. The entire pipeline is deterministic and offline.

**Atomic writes.** All output files are written via write-to-temp-then-rename to prevent partial corruption if the process is interrupted mid-write.

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Convention formatting | Deterministic templates (20 `CONVENTION_TEMPLATES` entries) | LLM-based formatting (send raw patterns to Claude for natural language output), rule-based sentence generators | Templates are zero-cost, deterministic, and auditable. LLM formatting would add latency, cost, and non-determinism for a task that follows rigid patterns. Adding a new convention type requires adding one template entry, not retraining a model. |
| Confidence threshold for `established` | 90%+ code adherence AND corroboration from a second data source | Single-source threshold (90% adherence alone), three-source requirement, LLM-assessed confidence | A single AST scan at 95% might be measuring the old pattern in a codebase that's migrating. Requiring a second signal (observation, config, or git history) prevents premature `established` status. Three sources would be too strict for config-derived conventions. |
| Co-modification pair threshold | 80% co-occurrence in commits touching either file | 50% (too noisy), 95% (too strict), absolute count (≥ 5 co-commits) | 80% balances signal quality with discovery coverage. Below 80%, coincidental co-commits in large PRs create false pairs. Above 90%, legitimate pairs with occasional independent changes are missed. Percentage-based scales better than absolute counts across repos of different sizes. |
| Token budget priority order | Conventions → project knowledge → learnings | Equal priority (round-robin truncation), learnings first (observation-derived has recency advantage), user-configurable ordering | Conventions are deterministic and config-backed (highest reliability). Project knowledge is human-curated (high reliability). Learnings are observation-derived (useful but noisier). Truncating in reverse reliability order preserves the most trustworthy context when budgets are tight. |
| Phase B reads observations, not synthesis output | Read raw observation JSONL directly | Read `developer-learnings.json` (already synthesized), read both raw and synthesized | Raw observations preserve the original signal (type, category, file scope). Synthesized learnings have already been routed, weighted, and deduplicated for a different purpose (agent learnings). Convention discovery needs the raw signal to correlate with code patterns independently. |
| Config-derived conventions skip quality bar | Direct to `established` with `source: config` | Run through full quality bar like discovered conventions | The config file IS the evidence. A team that configured Ruff's import ordering rules has already made the decision. Running it through "is this actionable? is this project-specific?" adds processing for a guaranteed-yes answer. |
| Project knowledge is human-maintained only | System generates drafts; humans promote to the canonical file | Fully automated (system writes directly), fully manual (no drafts), LLM-curated (LLM reviews drafts) | Automated knowledge injection risks polluting agent prompts with incorrect or stale information. The draft → review → promote workflow keeps the human in the loop for knowledge that code analysis can't verify. The cost is manual effort; the benefit is trust. |

## Drawbacks

**Template taxonomy requires maintenance.** The 20-entry `CONVENTION_TEMPLATES` dictionary covers current pattern types, but new pattern types (e.g., error handling conventions if tree-sitter grammar expands) require adding a template before they can surface as conventions. Patterns without a matching template go to `conventions-candidates.json` and are invisible to agents until a developer adds the template. The taxonomy is a gatekeeper, not just a formatter.

**Mechanical extraction surfaces noise for small codebases.** A project with 15 files may produce co-modification pairs that reflect the small file count (everything touches everything) rather than genuine architectural coupling. The quality bar and 80% threshold mitigate this, but small projects may see more candidates than accepted conventions.

**No structural convention discovery.** Templates cannot express "validation lives in the middleware layer" or "error handling follows a per-layer strategy." These require understanding that deterministic extraction can't provide. The project-knowledge.json escape hatch exists for this, but it requires manual authoring. Phase B partially compensates over time as reviewer observations accumulate.

**Observation dependency for full confidence.** Without observation history (cold start), `established` confidence is only available for config-derived conventions. Code-only analysis maxes out at `emerging`. Projects that haven't run SPEED for several features will see weaker convention signals until observations accumulate.

**Convention staleness after major refactors.** A large refactor may invalidate multiple conventions simultaneously, but conventions-meta.json only tracks file-level changes and cluster checksums. If a refactor changes patterns within the same files (e.g., switching from return codes to exceptions), the trigger system detects file changes but the old conventions persist until a full rescan. The convention violation feedback loop eventually catches this, but there's a lag.

## Dependencies

| Dependency | What must exist | What happens if absent |
|------------|----------------|----------------------|
| **Observation Infrastructure** (`lib/learn/extract.py`, `.speed/memory/observations/*.jsonl`) | Observation JSONL files from prior `speed learn` runs. Phase B reads `convention_violation`, `reviewer_finding`, and `human_override` observation types. | Phase B returns patterns unchanged (no strengthening, no observation-derived patterns). Discovery produces weaker confidence signals. All `discovered` conventions max out at `emerging` unless config-derived. |
| **CSG infrastructure** (`lib/context/csg.py`, `semantic-graph.json`) | CSG must have been built at least once (`context_build_layer1` run). Phase A2 reads symbol names for naming analysis. Phase A3 reads edges and clusters for import graph analysis. | Phase A2 falls back to tree-sitter-only name extraction (no CSG symbol lookup). Phase A3 is skipped entirely (no cluster-scoped import conventions). Other phases unaffected. |
| **Tree-sitter infrastructure** (`lib/context/treesitter_extract.py`) | ast-grep rules for the project's languages must exist. Phase A2 reads structured import data and function/class names. | Phase A2 import analysis unavailable. Naming analysis falls back to CSG symbols only (if available) or is skipped. Phase A1 (git), A4 (lock files), and Phase 0 (configs) still work. |
| **Assembly/bridge pattern** (`lib/context/assembly.py`, `lib/context_bridge.sh`) | The 3 assembly functions (`assemble_developer`, `assemble_reviewer`, `assemble_architect`) and their bridge wrappers must exist in their current form. Convention injection adds parameters to these functions. | Build failure. The assembly modifications are additive (new optional parameters with defaults), so existing callers continue working. But the bridge functions must exist to add the convention/knowledge loading code. |

## Unresolved Questions

| Question | What it blocks | Proposed resolution |
|----------|---------------|---------------------|
| Decorator and fixture extraction are unsupported by current ast-grep rules. Is this acceptable for v1, or a pre-ship blocker? | Scope of Phase A2. Without decorators, testing convention discovery misses `@pytest.fixture`, `@pytest.mark.parametrize`, `@app.route` patterns. | Acceptable for v1. These patterns surface through Phase B (reviewer observations about missing fixtures) and Phase 0 (pytest config in pyproject.toml). Add decorator extraction as a follow-up when ast-grep rules expand. |
| `project-knowledge.json` requires a human workflow for promoting drafts. No CLI or UI exists for this. | Usability of the project knowledge pipeline. Operators must manually edit JSON files. | v1: operators edit JSON directly (or use `jq`). v2: add `speed learn --promote-draft <id>` CLI command that moves a draft entry to the canonical file. |
| Should convention discovery run automatically during `speed plan` (before the Architect), or only via explicit `speed learn --conventions`? | Integration point. Running during plan would ensure fresh conventions for every planning session, but adds latency. | v1: explicit only (`speed learn --conventions`). The trigger check in `speed learn` (post-integrate) handles automatic runs. Conventions are relatively stable; they don't need refreshing on every plan. |
