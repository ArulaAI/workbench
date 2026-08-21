# Phase 6: FigmaMCP Adapter

> Parent RFC: [Unified Intake & Defect Pipeline](../unified-intake.md)
> Depends on: [Phase 1: Spec Templates](speed-templates.md), [Phase 2: Audit Agent](speed-audit.md)

## Problem

Design specs are written by hand. A designer creates a Figma file with precise component hierarchies, spacing tokens, color values, and breakpoint layouts — then manually transcribes all of that into a markdown design spec. This transcription is slow, error-prone, and immediately stale. The moment someone updates the Figma file, the spec drifts.

Worse, there's no way to verify that the implemented frontend matches the Figma source of truth. Design review happens visually — someone screenshots the running app and squints at the Figma side-by-side. Token mismatches (a hardcoded `#ffffff` instead of `surface-elevated`), missing component states, and incorrect responsive behavior slip through because the comparison is manual and subjective.

SPEED has a design spec template (Phase 1) and can audit it for structural completeness (Phase 2), but neither can bridge the gap between what's in Figma and what's in the spec or the code. The FigmaMCP adapter closes this loop: extract structured design data from Figma, scaffold specs from it, and verify implementations against it.

## Users

### Design
Creates Figma files as the visual source of truth. Wants the design spec to be scaffolded directly from Figma data — component trees, tokens, states — rather than transcribed by hand. Wants confidence that the implemented UI matches the Figma file, not just "close enough."

### Engineering
Implements designs from specs. Wants the design spec to contain accurate, machine-extracted tokens and component hierarchies — not a designer's best recollection of what's in the Figma file. Wants to know during review whether the implementation actually matches the Figma source, with specific discrepancies called out.

### Product
Owns the feature end-to-end. Wants assurance that what was designed is what was built. Wants design fidelity to be a verifiable quality gate, not a subjective call.

## User Stories

| ID | Story | Acceptance Criteria | Priority |
|----|-------|---------------------|----------|
| S1 | As a designer, I want to scaffold a design spec from a Figma file so that the Component Inventory and Design Tokens sections are pre-filled with accurate data | Given a Figma URL and frame name, when I run `speed intake figma`, then a design spec is created with Component Inventory and Design Tokens sections populated from Figma data | Must |
| S2 | As a designer, I want the scaffolded spec to flag token mismatches against `globals.css` so I know which Figma values don't map to existing design tokens | Given a scaffolded spec with extracted tokens, when a Figma token has no match in `globals.css`, then the token is flagged with a `<!-- TOKEN MISMATCH -->` comment | Must |
| S3 | As an engineer, I want to verify my implementation against the Figma source of truth so that design discrepancies are caught before merge | Given an implemented component and a Figma URL, when I run `speed figma-verify`, then a report lists specific component, token, state, and breakpoint discrepancies | Must |
| S4 | As a designer, I want to target a specific frame within a Figma file so that I can scaffold specs for individual pages or components | Given a Figma file with multiple frames, when I pass `--frame "Frame Name"`, then only that frame's data is extracted | Must |
| S5 | As an engineer, I want the verification output to list specific mismatches (wrong token, missing state, incorrect spacing) so I can fix them without guessing | Given a verification report with mismatches, when I read the report, then each mismatch includes the component, file path, line number, expected value, and actual value | Must |
| S6 | As a designer, I want the scaffolded spec to include component composition (nesting hierarchy) extracted from the Figma frame | Given a Figma frame with nested components, when the spec is scaffolded, then the Component Composition section shows the tree hierarchy using indented notation | Should |
| S7 | As a designer, I want breakpoint hints extracted from Figma so the Responsive Behavior section is pre-filled | Given a Figma file with breakpoint frames, when the spec is scaffolded, then the Responsive Behavior section lists each breakpoint with width and `<!-- TODO -->` markers for layout descriptions | Should |
| S8 | As a designer, I want to re-run intake on an updated Figma file and see what changed since the last extraction | Given a previously scaffolded spec and an updated Figma file, when I re-run intake, then the output shows which components were added, removed, or modified since the last extraction | Could |

## User Flows

### Scaffold a design spec from Figma (happy path)

1. Designer has a Figma file with a frame named "Profile Page"
2. Designer runs `./speed/speed intake figma "https://figma.com/file/abc123" --frame "Profile Page"`
3. SPEED connects to the FigmaMCP server at the configured endpoint
4. FigmaMCP extracts the component tree, design tokens, component states, and breakpoint hints from the specified frame
5. SPEED scaffolds `specs/design/profile-page.md` from the design template
6. SPEED pre-fills:
   - Component Inventory table with extracted components, types, and nesting
   - Component Composition section with the tree hierarchy
   - Design Tokens section with extracted color, spacing, and typography tokens
   - Responsive Behavior section with breakpoint hints (if present)
   - Figma Reference section with the source URL and frame name
7. SPEED compares extracted tokens against `globals.css` and flags mismatches:
   - Tokens that map to existing design system values (mapped)
   - Tokens that have no match in `globals.css` (unmapped — flagged with `<!-- TOKEN MISMATCH -->`)
8. SPEED opens the file in `$EDITOR` for human editing (states, interactions, data binding, accessibility still need human authorship)
9. Designer fills in the sections that require human judgment, removes `<!-- TODO -->` markers
10. Designer runs `./speed/speed audit specs/design/profile-page.md` to validate completeness

### Verify implementation against Figma (during review)

1. Engineer has implemented the Profile Page and the branch is ready for review
2. Engineer (or Reviewer Agent) runs `./speed/speed figma-verify "https://figma.com/file/abc123" --frame "Profile Page"`
3. SPEED connects to FigmaMCP and extracts the current component tree and tokens from the specified frame
4. SPEED reads the implemented components from the codebase (file paths derived from the design spec or `--spec` flag)
5. SPEED compares:
   - Component names and hierarchy (Figma tree vs. implemented component tree)
   - Design tokens used in code vs. tokens in Figma (catches hardcoded values, wrong token references)
   - Component states defined in Figma vs. states handled in code
   - Responsive breakpoints in Figma vs. breakpoint handling in code
6. SPEED prints a verification report:
   - Matches (green): components and tokens that align
   - Mismatches (yellow/red): specific discrepancies with file paths and line numbers
   - Missing (red): Figma components or states with no implementation counterpart
7. SPEED exits successfully if no mismatches, or exits with failure status indicating mismatches found
8. Engineer fixes discrepancies, re-runs verification

### FigmaMCP server not reachable

1. User runs either `intake figma` or `figma-verify`
2. SPEED attempts to connect to the configured `mcp_endpoint`
3. Connection fails (server not running, wrong port, network issue)
4. SPEED prints error: "Cannot reach FigmaMCP server at http://localhost:3845. Is the server running?"
5. SPEED exits with a configuration error

### Figma token not configured

1. User runs either `intake figma` or `figma-verify`
2. SPEED checks for `FIGMA_ACCESS_TOKEN` environment variable (name from `token_env` config)
3. Variable is empty or unset
4. SPEED prints error: "FIGMA_ACCESS_TOKEN is not set. Configure your Figma API token."
5. SPEED exits with a configuration error

## Success Criteria

- [ ] `speed intake figma <url> --frame <name>` scaffolds a design spec with pre-filled Component Inventory and Design Tokens
- [ ] Component Inventory table is populated with component names, types (new/modified), parent nesting, and props extracted from Figma
- [ ] Component Composition section shows the Figma frame's component tree hierarchy
- [ ] Design Tokens section lists extracted tokens mapped to `globals.css` names where possible
- [ ] Unmapped tokens are flagged with `<!-- TOKEN MISMATCH: Figma value #xyz has no match in globals.css -->`
- [ ] Responsive Behavior section includes breakpoint hints from Figma (if breakpoint frames exist)
- [ ] Figma Reference section is auto-filled with the source URL, frame name, and extraction timestamp
- [ ] Sections requiring human judgment (States, Interactions, Data Binding, Accessibility) retain template guidance comments
- [ ] `speed figma-verify <url> --frame <name>` compares implementation against Figma and prints a discrepancy report
- [ ] Verification report lists specific mismatches: wrong tokens, missing components, absent states
- [ ] Verification exits with failure status when mismatches are found, exits successfully when clean
- [ ] Both commands fail gracefully with a configuration error when FigmaMCP is unreachable or token is missing
- [ ] Configuration lives in `[integrations.figma]` section of `speed.toml`
- [ ] Sync is one-directional: SPEED reads from Figma, never writes back

## Scope

### In Scope
- `speed intake figma` CLI command (scaffold design spec from Figma via FigmaMCP)
- `speed figma-verify` CLI command (verify implementation against Figma source of truth)
- FigmaMCP integration adapter (`speed/integrations/figma.sh`)
- Component tree extraction and mapping to Component Inventory table
- Design token extraction and comparison against `globals.css`
- Token mismatch flagging in scaffolded specs
- Breakpoint hint extraction
- Verification report generation with specific discrepancies
- Configuration in `speed.toml` under `[integrations.figma]`
- Error handling for connectivity and authentication failures

### Out of Scope (and why)
- Pushing changes back to Figma — sync is one-directional by design; Figma is the source of truth for visual design
- Auto-fixing token mismatches in code — verification reports problems, the engineer fixes them
- Extracting interaction/animation specs from Figma — Figma's interaction data is too loosely structured for reliable extraction; humans write this
- Extracting accessibility annotations — Figma has no standardized accessibility layer; humans write this
- Figma comment sync — out of scope for the adapter; comments are a collaboration feature, not a design data source
- Multi-file Figma extraction (extracting all frames at once) — one frame per command keeps the scope focused
- Real-time Figma webhook integration — on-demand extraction is sufficient for the spec-driven workflow

## Dependencies

- Phase 1 (Spec Templates) — design spec template must exist as the scaffold target
- Phase 2 (Audit Agent) — `speed audit` validates the scaffolded design spec after human editing
- FigmaMCP server — must be running and accessible at the configured endpoint
- Figma API access — requires a valid Figma access token with read permissions
- `globals.css` — must exist for token mismatch comparison

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| FigmaMCP extracts an incomplete or inaccurate component tree | Medium | The scaffolded spec is a starting point, not a final product. The designer reviews and corrects before the spec enters the pipeline. Audit Agent catches structural gaps. |
| Token mismatch comparison produces false positives (Figma uses similar but not identical values) | Medium | Use fuzzy matching with a configurable threshold for color proximity. Flag near-matches as warnings, not errors. |
| FigmaMCP server API changes break the adapter | Medium | Pin to a known FigmaMCP version in docs. Adapter validates the response schema before processing. |
| Figma files use inconsistent naming conventions that don't map cleanly to component names | Low | Adapter normalizes names (PascalCase for components, kebab-case for files). Designer corrects any mismatches during editing. |
| Verification step is too slow for iterative development (fetches from Figma every run) | Low | Cache FigmaMCP responses for a configurable TTL (default 5 minutes). `--no-cache` flag for fresh extraction. |
| Design teams don't use Figma in a structured way (flat layers, no components, no auto-layout) | High | Document minimum Figma structure requirements. Adapter warns if the frame lacks components or auto-layout. Garbage in → garbage out is an acceptable failure mode with a clear error message. |
