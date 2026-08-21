# RFC: FigmaMCP Adapter

> See [product spec](../product/speed-figma.md) for product context.
> Depends on: [Phase 1: Spec Templates](speed-templates.md), [Phase 2: Audit Agent](speed-audit.md)
> Parent RFC: [Unified Intake & Defect Pipeline](../unified-intake.md)

## FigmaMCP Integration Architecture

### Adapter definition

**File:** `speed/integrations/figma.sh`
**Dependencies:** FigmaMCP server (MCP protocol over HTTP), Figma API access token
**Sync direction:** One-directional (read from Figma only)

The FigmaMCP adapter is structurally different from the other external adapters (GitHub, Linear, JIRA). Those adapters fetch text metadata (titles, descriptions, labels) and scaffold specs by filling in template fields. The Figma adapter extracts structured visual data — component hierarchies, design tokens, spatial relationships, and breakpoint configurations — and maps them to design spec sections that no other adapter touches (Component Inventory, Component Composition, Design Tokens, Responsive Behavior).

### Communication with FigmaMCP

The adapter communicates with the FigmaMCP server over HTTP using the MCP (Model Context Protocol) request format. FigmaMCP exposes Figma's file data as structured tool responses.

**Request flow:**
```
speed CLI → figma.sh → HTTP POST to mcp_endpoint → FigmaMCP server → Figma API → structured response
```

The adapter does not call the Figma REST API directly. All Figma data access goes through FigmaMCP, which handles authentication, pagination, and data normalization.

## CLI Commands

### Command 1: `speed intake figma`

```bash
./speed/speed intake figma <url> --frame <frame-name> [--name <spec-name>] [--no-cache]
```

**Arguments:**
| Argument | Required | Description |
|----------|----------|-------------|
| `<url>` | Yes | Figma file URL (e.g., `https://figma.com/file/abc123`) |
| `--frame` | Yes | Frame name within the Figma file to extract |
| `--name` | No | Output spec name. Defaults to kebab-cased frame name (e.g., "Profile Page" -> `profile-page`) |
| `--no-cache` | No | Bypass FigmaMCP response cache, force fresh extraction |

**Implementation: `cmd_intake_figma()`**

Add to `speed/speed` command dispatch. Delegates to `speed/integrations/figma.sh`.

1. **Validate configuration:**
   - Check `[integrations.figma]` section exists in `speed.toml`
   - Check `mcp_endpoint` is set (default: `http://localhost:3845`)
   - Check environment variable named in `token_env` is set and non-empty
   - If any check fails: print specific error, exit `EXIT_CONFIG_ERROR` (3)

2. **Validate arguments:**
   - URL is required and must match `https://.*figma\.com/(file|design)/[a-zA-Z0-9]+`
   - `--frame` is required
   - If `--name` provided, must match `^[a-z0-9]([a-z0-9-]*[a-z0-9])?$`
   - Output file path: `specs/design/${name}.md`
   - If output file exists: warn and exit `EXIT_CONFIG_ERROR` (3) (no overwrite)

3. **Connect to FigmaMCP:**
   - Send health check to `${mcp_endpoint}/health` (or equivalent)
   - If unreachable: print "Cannot reach FigmaMCP server at ${mcp_endpoint}. Is the server running?", exit `EXIT_CONFIG_ERROR` (3)
   - Timeout: 10 seconds for connection, 60 seconds for extraction

4. **Extract design data:**
   - Call `figma_extract_frame()` (see Adapter Functions below)
   - Response is structured JSON with component tree, tokens, states, breakpoints

5. **Parse `globals.css` for token comparison:**
   - Call `figma_parse_design_tokens()` to extract all `@theme` tokens from `src/frontend/src/app/globals.css`
   - Build a lookup map: `{ token_name: value, ... }`

6. **Map tokens:**
   - Call `figma_map_tokens()` to compare Figma-extracted tokens against `globals.css` tokens
   - Exact matches: map Figma value to design system token name
   - Near matches (color distance < threshold): map with a warning comment
   - No match: flag as `<!-- TOKEN MISMATCH: Figma value {value} has no match in globals.css -->`

7. **Scaffold design spec:**
   - Load `speed/templates/design.md`
   - Replace standard placeholders (`{Feature Name}`, `{name}`, `{product-spec}`)
   - Call `figma_fill_spec()` to populate sections from extracted data:
     - Component Inventory table
     - Component Composition tree
     - Design Tokens section
     - Responsive Behavior section
     - Figma Reference section
   - Write to `specs/design/${name}.md`

8. **Open for editing:**
   - Open in `$EDITOR` if set, otherwise print file path
   - Print summary: component count, token count, mismatch count

### Command 2: `speed figma-verify`

```bash
./speed/speed figma-verify <url> --frame <frame-name> [--spec <spec-path>] [--no-cache]
```

**Arguments:**
| Argument | Required | Description |
|----------|----------|-------------|
| `<url>` | Yes | Figma file URL |
| `--frame` | Yes | Frame name to verify against |
| `--spec` | No | Path to the design spec. Auto-resolved from frame name if not provided |
| `--no-cache` | No | Bypass FigmaMCP response cache |

**Implementation: `cmd_figma_verify()`**

1. **Validate configuration and arguments:** same as `intake figma` steps 1-3

2. **Resolve design spec:**
   - If `--spec` provided, use it
   - Otherwise derive: `specs/design/${kebab_frame_name}.md`
   - If spec doesn't exist: warn "No design spec found. Run `speed intake figma` first or provide `--spec`.", exit `EXIT_CONFIG_ERROR` (3)

3. **Extract current Figma data:**
   - Call `figma_extract_frame()` — same as intake

4. **Extract implementation data:**
   - Parse the design spec's Component Inventory for component file paths
   - Read component source files from `src/frontend/`
   - Extract:
     - Component names and hierarchy from import/export structure
     - Token references from Tailwind classes and CSS custom properties
     - State handling from conditional rendering logic
     - Breakpoint usage from responsive Tailwind prefixes (`sm:`, `md:`, `lg:`, etc.)

5. **Compare:**
   - Call `figma_verify_components()` — compare Figma component tree vs. implementation tree
   - Call `figma_verify_tokens()` — compare Figma tokens vs. tokens used in component source
   - Call `figma_verify_states()` — compare Figma component variants (states) vs. code state handling
   - Call `figma_verify_breakpoints()` — compare Figma breakpoint frames vs. responsive prefixes in code

6. **Generate verification report:**
   ```
   Figma Verification: Profile Page
   Source: https://figma.com/file/abc123 (frame: Profile Page)
   Spec: specs/design/profile-page.md

   Components:
     ✓ ProfileCard — matches src/frontend/components/features/profile-card.tsx
     ✓ Avatar — matches src/frontend/components/features/avatar.tsx
     ✗ StatRow — not found in implementation
     ⚠ NameBlock — exists but missing "loading" variant

   Tokens:
     ✓ surface-elevated — used correctly (12 occurrences)
     ✗ ink-secondary — Figma uses #57534e, code uses hardcoded #6b7280 (line 42, profile-card.tsx)
     ⚠ accent-DEFAULT — Figma uses #6366f1, nearest code token is accent-hover (#4f46e5)

   States:
     ✓ Empty state — handled
     ✗ Error state — no error handling found in ProfileCard
     ✓ Loading state — skeleton present

   Breakpoints:
     ✓ Desktop (1024px+) — layout matches
     ⚠ Mobile (< 640px) — Figma shows stacked layout, code uses side-by-side below sm:

   Result: FAIL (2 errors, 3 warnings)
   ```

7. **Exit code:**
   - Errors present: `EXIT_GATE_FAILURE` (2)
   - Warnings only: `EXIT_OK` (0) with warnings printed
   - Clean: `EXIT_OK` (0)

## Adapter Functions

### Adapter Contract: `figma_fetch()` / `figma_sync()`

Per the [parent RFC's adapter architecture](../unified-intake.md), every external adapter implements two entry-point functions: `adapter_fetch()` and `adapter_sync()`. The Figma adapter exposes these as `figma_fetch()` and `figma_sync()`.

#### `figma_fetch()`

**File:** `speed/integrations/figma.sh`

Entry-point wrapper called by `cmd_intake_figma()`. Orchestrates the Figma-specific extraction functions in sequence:

1. Calls `figma_extract_frame()` to pull structured data from FigmaMCP
2. Calls `figma_parse_design_tokens()` to build the `globals.css` token lookup map
3. Calls `figma_map_tokens()` to compare extracted tokens against the design system
4. Calls `figma_fill_spec()` to populate the design spec template with extracted data
5. Returns the populated spec content and a summary (component count, token count, mismatch count)

**Input:** Figma URL, frame name, MCP endpoint, access token, template path, globals.css path
**Output:** Populated design spec content (string), extraction summary (JSON)

#### `figma_sync()`

**File:** `speed/integrations/figma.sh`

**This is a no-op.** The Figma adapter is one-directional by design — SPEED reads from Figma but never writes back. The function exists solely to satisfy the adapter contract so that the integration dispatch logic in `speed/speed` can call `adapter_sync()` uniformly across all adapters without special-casing Figma.

```bash
figma_sync() {
  # No-op: Figma integration is read-only (one-directional).
  # SPEED does not push status updates back to Figma.
  return 0
}
```

---

### `figma_extract_frame()`

**File:** `speed/integrations/figma.sh`

Connects to FigmaMCP and extracts structured data from a Figma frame.

**Input:** Figma URL, frame name, MCP endpoint, access token
**Output:** JSON structure:

```json
{
  "file_key": "abc123",
  "frame_name": "Profile Page",
  "extracted_at": "2026-02-22T14:30:00Z",
  "components": [
    {
      "name": "ProfileCard",
      "type": "COMPONENT",
      "children": [
        {
          "name": "Avatar",
          "type": "COMPONENT",
          "children": [],
          "properties": { "width": 64, "height": 64, "cornerRadius": 32 },
          "tokens": { "fill": "#ffffff", "stroke": "none" }
        },
        {
          "name": "NameBlock",
          "type": "FRAME",
          "children": [
            { "name": "DisplayName", "type": "TEXT", "children": [], "tokens": { "fontFamily": "DM Serif Display", "fontSize": 24, "fill": "#1c1917" } },
            { "name": "Handle", "type": "TEXT", "children": [], "tokens": { "fontFamily": "DM Sans", "fontSize": 14, "fill": "#57534e" } }
          ]
        }
      ],
      "variants": ["Default", "Loading", "Empty", "Error"],
      "autoLayout": { "direction": "VERTICAL", "spacing": 16, "padding": { "top": 24, "right": 24, "bottom": 24, "left": 24 } }
    }
  ],
  "breakpoints": [
    { "name": "Desktop", "width": 1280 },
    { "name": "Tablet", "width": 768 },
    { "name": "Mobile", "width": 375 }
  ],
  "raw_tokens": {
    "colors": { "#1c1917": 14, "#57534e": 8, "#f9f8f6": 3, "#6366f1": 2 },
    "fonts": { "DM Serif Display": 4, "DM Sans": 18, "IBM Plex Mono": 2 },
    "spacing": [4, 8, 12, 16, 24, 32, 48],
    "radii": [4, 8, 12, 16, 9999]
  }
}
```

**MCP interaction:**

The adapter sends MCP tool-use requests to the FigmaMCP server. The exact MCP tool names depend on the FigmaMCP implementation, but the adapter expects to call:

1. `get_file` — fetch file metadata, resolve frame node ID from frame name
2. `get_node` — fetch the component tree for the resolved frame node
3. `get_styles` — fetch local styles (colors, text styles, effects) from the file

If a tool call fails, the adapter retries once, then exits with an error message indicating which extraction step failed.

**Caching:**

Responses are cached in `.speed/cache/figma/<file_key>-<frame_hash>.json` with a configurable TTL (default: 5 minutes, set in `speed.toml`). The `--no-cache` flag bypasses the cache.

### `figma_parse_design_tokens()`

**File:** `speed/integrations/figma.sh`

Parses `globals.css` to build a lookup map of all design system tokens.

**Input:** Path to `globals.css` (auto-resolved from project root)
**Output:** Token lookup map (associative array in bash or JSON):

```json
{
  "colors": {
    "surface-primary": "#f9f8f6",
    "surface-secondary": "#f2f0ed",
    "surface-elevated": "#ffffff",
    "surface-inverse": "#1c1917",
    "ink-DEFAULT": "#1c1917",
    "ink-secondary": "#57534e",
    "ink-tertiary": "#a8a29e",
    "accent-DEFAULT": "#6366f1",
    "accent-hover": "#4f46e5",
    "shipped-DEFAULT": "#16a34a"
  },
  "fonts": {
    "font-serif": "DM Serif Display",
    "font-sans": "DM Sans",
    "font-mono": "IBM Plex Mono"
  }
}
```

**Implementation:** Parse the `@theme` block in `globals.css` using `grep`/`awk` to extract `--color-*` and `--font-*` custom properties. This is a static parse — no CSS engine required.

### `figma_map_tokens()`

**File:** `speed/integrations/figma.sh`

Compares Figma-extracted tokens against the `globals.css` token map.

**Input:** Figma raw tokens (from extraction), design system token map (from parse)
**Output:** Token mapping with match status:

```json
{
  "mapped": [
    { "figma_value": "#1c1917", "token": "ink-DEFAULT", "type": "color", "match": "exact" },
    { "figma_value": "#57534e", "token": "ink-secondary", "type": "color", "match": "exact" },
    { "figma_value": "DM Serif Display", "token": "font-serif", "type": "font", "match": "exact" }
  ],
  "unmapped": [
    { "figma_value": "#c4775a", "type": "color", "nearest_token": null, "comment": "TOKEN MISMATCH" },
    { "figma_value": "#e5e7eb", "type": "color", "nearest_token": "ink-tertiary (#a8a29e)", "distance": 47, "comment": "TOKEN MISMATCH (nearest: ink-tertiary, distance: 47)" }
  ]
}
```

**Color distance:** Use CIE76 Delta E (Euclidean distance in Lab color space) for comparing color proximity. Threshold for "near match" warning: Delta E < 25. Implementation: convert hex to RGB to Lab, compute distance. This can be done in `awk` or delegated to a small helper.

### `figma_fill_spec()`

**File:** `speed/integrations/figma.sh`

Populates the design spec template sections from extracted Figma data.

**Input:** Template content, extracted frame data, token mapping
**Output:** Populated spec content (string)

**Section mappings:**

| Design spec section | Source data | Fill strategy |
|---------------------|-------------|---------------|
| Component Inventory | `components[]` | One row per component: name, type, parent component name, properties summary, Figma variant count. **Note:** Initial scaffolding always marks the Type column as `new` since there is no prior spec to diff against. Diffing logic to detect `modified` components on re-run is deferred to the "Could" priority story (S8: re-run intake on updated Figma file). |
| Component Composition | `components[]` (tree) | Indented tree using `→` notation (e.g., `ProfileCard → Avatar + NameBlock → DisplayName + Handle`) |
| Design Tokens | `token_mapping.mapped[]` + `unmapped[]` | Grouped by type (colors, typography, spacing). Mapped tokens show: "Card background: `surface-elevated`". Unmapped tokens show: `<!-- TOKEN MISMATCH: ... -->` |
| Responsive Behavior | `breakpoints[]` | List each breakpoint with width. Layout hints from auto-layout data. Mark with `<!-- TODO: Describe layout changes -->` for human completion |
| Figma Reference | URL, frame name, timestamp | Auto-filled: `Source: [Profile Page](https://figma.com/file/abc123), Frame: Profile Page, Extracted: 2026-02-22` |

**Sections left for human authoring** (template guidance comments preserved):
- Pages / Routes
- States (Empty, Loading, Populated, Error) — Figma variants are listed as hints but states need human description
- Data Binding
- Interactions
- Accessibility

### `figma_verify_components()`

**File:** `speed/integrations/figma.sh`

Compares the Figma component tree against implemented components.

**Input:** Figma component tree, component file paths from design spec or glob pattern
**Output:** List of match/mismatch/missing entries

**Matching logic:**
1. Normalize Figma component names to PascalCase (project convention)
2. Search for matching `.tsx` files in `src/frontend/components/` using glob
3. For each Figma component:
   - Found in code with matching name: `match`
   - Found in code but missing variants: `partial` (list missing variants)
   - Not found: `missing`
4. For each code component not in Figma: `extra` (informational, not an error)

### `figma_verify_tokens()`

**File:** `speed/integrations/figma.sh`

Compares tokens specified in Figma against tokens actually used in component source files.

**Input:** Figma token mapping, component source files
**Output:** List of match/mismatch entries

**Matching logic:**
1. For each mapped Figma token, search component source for the token name in Tailwind classes
   - e.g., Figma `#1c1917` maps to `ink-DEFAULT` → search for `text-ink`, `bg-ink`, etc.
2. Flag: hardcoded hex values in component source that should be tokens
   - Search for `#[0-9a-fA-F]{3,8}` patterns in `.tsx` files (excluding comments and imports)
3. Flag: token references that don't match what Figma specifies for that component

### `figma_verify_states()`

**File:** `speed/integrations/figma.sh`

Compares Figma component variants (states) against state handling in code.

**Input:** Figma component variants, component source files
**Output:** List of handled/missing states

**Matching logic:**
1. Extract variant names from Figma data (e.g., "Default", "Loading", "Empty", "Error")
2. Search component source for state-related patterns:
   - Loading: `skeleton`, `loading`, `isLoading`, `Suspense`
   - Empty: `empty`, `no data`, `nothing`, `fallback`
   - Error: `error`, `Error`, `catch`, `ErrorBoundary`
3. Report which states have code coverage and which don't

### `figma_verify_breakpoints()`

**File:** `speed/integrations/figma.sh`

Compares Figma breakpoint frames against responsive handling in code.

**Input:** Figma breakpoints, component source files
**Output:** List of breakpoint coverage

**Matching logic:**
1. Map Figma breakpoints to Tailwind breakpoint prefixes:
   - Mobile (< 640px): default (no prefix)
   - Tablet (~768px): `md:`
   - Desktop (~1024px): `lg:`
2. Search component source for responsive prefixes
3. Report which breakpoints have responsive handling

## Configuration

### `speed.toml`

```toml
[integrations.figma]
mcp_endpoint = "http://localhost:3845"
token_env = "FIGMA_ACCESS_TOKEN"
cache_ttl = 300                          # seconds, default 5 minutes
color_distance_threshold = 25            # CIE76 Delta E, default 25
globals_css = "src/frontend/src/app/globals.css"  # path to design tokens
```

**Field descriptions:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `mcp_endpoint` | string | Yes | `http://localhost:3845` | FigmaMCP server URL |
| `token_env` | string | Yes | `FIGMA_ACCESS_TOKEN` | Environment variable name holding the Figma API token |
| `cache_ttl` | integer | No | `300` | Cache TTL in seconds for FigmaMCP responses |
| `color_distance_threshold` | integer | No | `25` | Maximum Delta E for "near match" color comparison |
| `globals_css` | string | No | `src/frontend/src/app/globals.css` | Path to the CSS file containing design system tokens |

### Environment variables

| Variable | Description |
|----------|-------------|
| `FIGMA_ACCESS_TOKEN` | Figma personal access token with read access (name is configurable via `token_env`) |

## Cache

### Directory structure

```
.speed/cache/figma/
  <file_key>-<frame_hash>.json     # Cached extraction response
  <file_key>-<frame_hash>.meta     # Cache metadata (timestamp, TTL)
```

`frame_hash` is the MD5 of the frame name (avoids filesystem issues with spaces/special characters).

### Cache behavior

- `intake figma` and `figma-verify` check the cache before calling FigmaMCP
- If cached response exists and age < `cache_ttl`: use cached data
- If expired or `--no-cache`: fetch fresh data, update cache
- Cache is per file+frame, not global

## Verification Report Format

### Structured output (JSON)

```json
{
  "status": "pass | warn | fail",
  "figma_url": "https://figma.com/file/abc123",
  "frame": "Profile Page",
  "spec": "specs/design/profile-page.md",
  "verified_at": "2026-02-22T14:35:00Z",
  "components": {
    "matched": ["ProfileCard", "Avatar"],
    "partial": [{ "name": "NameBlock", "missing_variants": ["Loading"] }],
    "missing": ["StatRow"],
    "extra": []
  },
  "tokens": {
    "correct": 12,
    "mismatched": [
      { "component": "profile-card.tsx", "line": 42, "figma_token": "ink-secondary", "code_value": "#6b7280" }
    ],
    "hardcoded": [
      { "component": "avatar.tsx", "line": 18, "value": "#e5e7eb" }
    ]
  },
  "states": {
    "handled": ["empty", "loading"],
    "missing": ["error"]
  },
  "breakpoints": {
    "covered": ["desktop", "mobile"],
    "missing": [],
    "warnings": ["mobile layout may not match Figma — code uses side-by-side, Figma shows stacked"]
  }
}
```

### Status rules

- `fail` — any `missing` components or `mismatched` tokens (implementation disagrees with Figma)
- `warn` — only `partial` matches, `hardcoded` values, or breakpoint warnings
- `pass` — everything matches

The JSON report is written to `.speed/cache/figma/<file_key>-<frame_hash>-verify.json` for later reference.

## Integration with Review Pipeline

The `figma-verify` command is designed to be called during the review stage of the feature pipeline. It can be:

1. **Run manually** by the engineer before submitting for review
2. **Called by the Reviewer Agent** if the design spec has a Figma Reference section with a URL — the Reviewer's prompt can include: "If a Figma reference exists, run `speed figma-verify` and include the results in your review"
3. **Added as a quality gate** in `speed.toml` subsystem config:
   ```toml
   [subsystems.frontend]
   gates = ["lint", "typecheck", "test", "figma-verify"]
   figma_verify_url = "https://figma.com/file/abc123"
   ```

Integration with the review pipeline is opt-in. The adapter provides the tooling; the project configures whether it's a gate or advisory.

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| **CIE76 (Delta E) for color distance** | Simpler than CIEDE2000 and sufficient for design token comparison where we're matching exact or near-exact values. The precision difference between CIE76 and CIEDE2000 matters for perceptual color science but not for detecting "is this `#57534e` or `#6b7280`?" token mismatches. |
| **Bash for hex-to-RGB-to-Lab color conversion** | Avoids introducing a Python dependency into the SPEED CLI, which is pure bash. The conversion is a handful of arithmetic operations per color, not a hot loop. Acceptable trade-off for keeping the toolchain minimal. |
| **File-based cache with configurable TTL** | FigmaMCP extraction is the slowest operation in the pipeline (network round-trip to Figma API). Caching per file+frame with a 5-minute default TTL avoids redundant extraction during iterative workflows (scaffold, edit, re-audit) without risking stale data across sessions. |
| **One-directional sync (no write-back to Figma)** | Figma is the designer's source of truth. SPEED consuming Figma data is safe; SPEED modifying Figma data would create conflicts and trust issues. The `figma_sync()` no-op satisfies the adapter contract without introducing risk. |
| **Frame-level extraction (not file-level)** | A Figma file can contain dozens of unrelated frames. Frame-level targeting keeps extraction focused and spec output manageable. Multi-frame extraction is out of scope. |

## Drawbacks

- **Bash-based JSON and color processing performance.** Parsing large FigmaMCP responses and computing color distances in bash/awk will be slow compared to a purpose-built tool. Acceptable for the expected data size (dozens of components, not thousands), but could become a bottleneck for very large Figma files.
- **FigmaMCP API instability.** FigmaMCP is a third-party MCP server with no stability guarantees. The exact tool names (`get_file`, `get_node`, `get_styles`) may change between versions, requiring adapter updates. Mitigated by schema validation on responses and pinning to a known version.
- **No support for Figma files without Auto Layout.** The adapter relies on Auto Layout data for spacing tokens and layout hierarchy extraction. Figma files using absolute positioning will produce sparse or misleading specs. Documented as a prerequisite, but no graceful degradation beyond a warning message.
- **Token matching is syntactic, not semantic.** The `figma_verify_tokens()` function searches for token names in Tailwind classes using string matching. It cannot detect tokens applied via CSS custom properties, `cn()` utility composition, or dynamically computed class strings.

## Unresolved Questions

- **Exact MCP tool names.** The spec assumes `get_file`, `get_node`, `get_styles` based on current FigmaMCP documentation, but these depend on the FigmaMCP version deployed. Needs validation against the actual server before implementation.
- **Handling Figma files with no components.** If a frame contains only raw shapes and text (no Figma components), the Component Inventory will be empty. Should the adapter warn? Refuse to scaffold? Currently unspecified.
- **Figma variants vs. component states.** Figma "variants" are a property-based system (e.g., `State=Loading, Size=Large`). The adapter currently treats variant names as flat state labels. Mapping multi-dimensional variants to component props (not just states) needs further design.
- **Cache invalidation on `globals.css` changes.** The current cache is keyed on Figma file+frame, but token mapping also depends on `globals.css`. If the design system tokens change, cached extraction is still valid but the token mapping is stale. Should `globals.css` mtime be part of the cache key?

## File Impact

| File | Change |
|------|--------|
| `speed/speed` | Add `cmd_intake_figma()`, add `cmd_figma_verify()`, add `intake figma` and `figma-verify` to command dispatch and `speed_help()` |
| `speed/integrations/figma.sh` | New file — adapter contract wrappers: `figma_fetch()`, `figma_sync()` (no-op); extraction functions: `figma_extract_frame()`, `figma_parse_design_tokens()`, `figma_map_tokens()`, `figma_fill_spec()`; verification functions: `figma_verify_components()`, `figma_verify_tokens()`, `figma_verify_states()`, `figma_verify_breakpoints()` |
| `speed/lib/cache.sh` | New file (or addition to existing lib) — generic cache read/write/invalidate functions used by the Figma adapter |
| `speed/templates/design.md` | No change — existing template, used as scaffold target |

## Dependencies

- Phase 1 (Spec Templates) — design spec template must exist at `speed/templates/design.md`
- Phase 2 (Audit Agent) — scaffolded design specs should pass `speed audit` after human editing
- FigmaMCP server — external dependency, must be running during `intake figma` and `figma-verify`
- `globals.css` — must exist and contain `@theme` tokens for comparison
- `jq` — for JSON parsing of MCP responses (already a common SPEED dependency)
- `curl` — for HTTP requests to MCP endpoint (standard)
