# Design: {Feature Name}

> See [{product-spec}]({product-spec}) for product context.

<!--
  WHO READS THIS SPEC
  This spec is consumed by AI coding agents as their primary implementation
  reference. Humans review it, but agents execute from it. Every section is
  structured for literal, unambiguous interpretation.

  THE #1 AGENT FAILURE MODE
  Agents fabricate design tokens. They generate plausible-looking variable
  names that don't exist in your design system. Every visual property in this
  spec must reference a token from the project's closed token set. If the
  token doesn't exist, flag it for addition to the design system. Never write
  a raw hex, pixel value, or font name outside of the token definitions.

  HOW TO USE THIS TEMPLATE
  Fill in every section. Sections left blank become implementation decisions
  made by an agent with no context. That agent will default to its training
  data (Inter, 16px, purple gradients, predictable layouts). If a section
  genuinely doesn't apply, write "N/A — [reason]" so the agent knows the
  omission is intentional.

  MULTI-RFC FEATURES
  When a PRD maps to multiple child RFCs, the design spec typically stays
  as one document (UI is experienced holistically, not in implementation
  phases). If the design is genuinely too large (20+ components across 5+
  pages), split by page group and use the same Parent RFC / Depends on
  headers as the RFC template. Each child design spec should cover complete
  pages, not partial components.
-->


## Design Intent

<!-- Two to three sentences. Not a feature description (that belongs in the
     PRD). This answers: what should using this feel like? What's the visual
     tone? What existing product or reference captures the vibe?

     Then list negative constraints. Agents default to training-data patterns
     unless you explicitly exclude them. Negative constraints prevent drift
     more reliably than positive direction alone.

     EXAMPLE:
     Dense, calm, information-first. Feels like a Bloomberg terminal
     designed by someone who reads Monocle.

     DO NOT: rounded playful elements, gradients, card shadows deeper than
     the elevation scale allows, skeleton loaders that pulse (use opacity
     fade instead). -->

**Direction:**

**Do not:**


## Pages / Routes

<!-- Map each URL to a user flow from the PRD. If a user flow has no route,
     something is missing. If a route has no user flow, it shouldn't exist. -->

| Route | User Flow | Description |
|-------|-----------|-------------|
| | | |


## Layout Structure

<!-- Decompose the page into three layers. Agents can't interpret a holistic
     mockup. Explicit layering (Global → Region → Component) significantly
     improves implementation accuracy.

     AGENT FAILURE MODE: Without this decomposition, agents produce flat
     layouts where everything sits at the same visual level, or they invent
     a grid structure from training data that doesn't match your intent. -->

### Global Layout

<!-- The outermost page shell. Defines the grid system, max-width, and
     persistent UI (nav, sidebar, footer).

     Specify:
     - Column system (e.g., 12-column, content + sidebar, single column)
     - Max content width and centering behavior
     - Persistent elements (nav rail, header bar, footer)
     - How the grid relates to your spacing scale -->

### Regions

<!-- Named content areas within the global layout. Each region is a
     self-contained layout zone with its own internal rules.

     Use a flat list with IDs — not nested prose. Agents parse flat
     structures more reliably than tree descriptions.

     EXAMPLE:
     | Region ID    | Position         | Width       | Internal Layout | Scroll |
     |--------------|------------------|-------------|-----------------|--------|
     | header       | top, fixed       | full        | flex, space-between | no |
     | sidebar      | left, sticky     | 240px fixed | flex-col, gap-sm    | yes |
     | main-content | right of sidebar | fluid       | stack, gap-lg       | yes |
     | footer       | bottom           | full        | flex, center        | no  | -->

| Region ID | Position | Width | Internal Layout | Scroll |
|-----------|----------|-------|-----------------|--------|
| | | | | |


## Component Inventory

<!-- Flat list. The Parent ID column references a Region ID from above or
     another Component ID. This creates an unambiguous containment hierarchy
     without prose descriptions of nesting.

     AGENT FAILURE MODE: Without explicit parent references, agents place
     components at the wrong nesting level or duplicate container wrappers. -->

| Component ID | Type | Parent ID | Description |
|--------------|------|-----------|-------------|
| | new / modified | region or component ID | |

### Component Props

<!-- For each new component, list its props interface. Agents use this to
     generate type definitions and wire up data binding.

     EXAMPLE:
     #### MetricCard
     | Prop | Type | Default | Description |
     |------|------|---------|-------------|
     | label | string | required | Display name above the value |
     | value | number | required | The metric value |
     | trend | "up" \| "down" \| "flat" | "flat" | Arrow indicator direction |
     | format | "number" \| "percent" \| "currency" | "number" | Value display format | -->


## Spacing

<!-- Reference your project's spacing scale by token name. Specify
     relationships, not just values. The goal: an agent should be able to
     pick the right spacing token without guessing.

     RULES TO DEFINE:
     - Internal padding (inside a component) ≤ external margin (around it).
       Violating this makes grouped elements feel cramped inside and
       disconnected from each other.
     - Related elements get tighter spacing. Unrelated elements get looser
       spacing. Spacing communicates grouping.
     - Vertical rhythm: line-heights should land on the spacing grid.

     EXAMPLE:
     | Context | Token | Usage |
     |---------|-------|-------|
     | Page margin | space-6 | Outer page padding on all sides |
     | Section gap | space-8 | Between major page sections |
     | Card padding | space-5 | Internal padding for card surfaces |
     | Card gap | space-4 | Between cards in a grid |
     | Inline element gap | space-2 | Between icon and label, badge and text |
     | Form field gap | space-3 | Between stacked form inputs |

     AGENT FAILURE MODE: Without explicit spacing assignments, agents
     default to arbitrary padding/margin values per element. By session
     five, the layout feels "off" but the inconsistency is spread across
     dozens of files. -->

| Context | Token | Usage |
|---------|-------|-------|
| | | |


## Typography

<!-- Assign a type role to every text element in the design. Reference
     your project's typography scale (named roles, not raw font sizes).

     Each role should specify: font family token, size, weight, line-height,
     letter-spacing, and color token. If your design system already defines
     roles (e.g., "page-title", "body", "caption"), reference those.

     RULES TO DEFINE:
     - Which font family handles which content type (e.g., monospace for
       numbers and code, sans-serif for body, serif for editorial headlines)
     - Weight discipline: fewer weights = hierarchy comes from size and
       spacing instead of a grab-bag of bold/semibold/medium that
       developers interpret differently
     - Size contrast: jumps should be noticeable (3x+ for hero elements),
       not incremental (1.2x steps that blur together)

     EXAMPLE:
     | Element | Role | Family | Size | Weight | Line-Height | Color |
     |---------|------|--------|------|--------|-------------|-------|
     | Page title | type-page-title | font-heading | 3xl | 700 | tight | text-primary |
     | KPI value | type-kpi | font-mono | 2xl | 600 | none | text-accent |
     | Body text | type-body | font-sans | base | 400 | relaxed | text-secondary |
     | Caption | type-caption | font-sans | xs | 400 | normal | text-tertiary |

     AGENT FAILURE MODE: Without role assignments, agents set font-size
     and font-weight ad hoc per element. The result looks like three
     different products. -->

| Element | Role | Family | Size | Weight | Line-Height | Color |
|---------|------|--------|------|--------|-------------|-------|
| | | | | | | |


## Color Application

<!-- Map every surface, text, and interactive element to a color token.
     Do not list the full palette here. Instead, show how tokens are
     applied in this specific feature.

     EXAMPLE:
     | Element | Property | Token | Notes |
     |---------|----------|-------|-------|
     | Page background | background | bg-primary | |
     | Card surface | background | bg-elevated | Pair with shadow-sm + border |
     | Primary action button | background | accent | Hero actions only |
     | Destructive action | background | status-error | Delete, remove, revoke |
     | Disabled text | color | text-disabled | Non-interactive elements only |

     AGENT FAILURE MODE: Agents over-apply accent colors. Accent is for
     hero metrics and primary actions only. Applying it to borders,
     secondary text, or decorative elements dilutes it into noise. Call
     out explicitly where accent is and isn't used. -->

| Element | Property | Token | Notes |
|---------|----------|-------|-------|
| | | | |


## Elevation & Depth

<!-- Define which elements are elevated and how. If your design system
     uses border + shadow pairs, surface classes, or z-index layers,
     specify the mapping here.

     EXAMPLE:
     | Element | Elevation Level | Treatment |
     |---------|----------------|-----------|
     | Page background | 0 (base) | Flat, no shadow |
     | Content card | 1 | surface class (border + shadow-sm) |
     | Dropdown menu | 2 | shadow-md, higher z-index than cards |
     | Modal overlay | 3 | shadow-lg, backdrop blur |
     | Toast notification | 4 | shadow-xl, highest z-index |

     AGENT FAILURE MODE: Agents either make everything flat (no depth cues)
     or apply shadows inconsistently. Specify elevation as a ranked system
     so relative depth is unambiguous. -->

| Element | Elevation Level | Treatment |
|---------|----------------|-----------|
| | | |


## States

<!-- Every component must account for ALL states. The most common spec
     failure is only showing the happy path. If you only design for
     "user has avatar, full name, 3 projects, and a bio," the agent will
     improvise the empty states. That improvisation will be wrong.

     Use a state matrix for interactive elements. Use prose descriptions
     for page-level states (empty, loading, populated, error). -->

### Page-Level States

#### Empty State
<!-- What the user sees with no data. Must look intentional, not broken.
     Include the fallback chain (e.g., no avatar → initials → generic icon).
     Sparse data is the common case. Design for it first. -->

#### Loading State
<!-- Skeleton, spinner, or progressive reveal? Which regions load first?
     Does the skeleton preserve layout shape or show a centered spinner?
     Specify the sequence and any stagger timing between regions. -->

#### Populated State
<!-- Primary view with typical data. Use realistic content: real names,
     real numbers, real content lengths. "Lorem ipsum" hides layout
     problems that surface with actual data. -->

#### Error State
<!-- What happens when things fail. Specify: full-page error vs. inline
     error vs. partial failure (some regions loaded, some didn't). Show
     what the user can DO about it (retry, navigate away, contact support),
     not just a red banner. -->

### Interactive Element States

<!-- Matrix format. One row per interactive component, one column per state.
     Specify which visual properties change (background, border, text color,
     opacity, cursor, shadow) using token names.

     AGENT FAILURE MODE: Agents implement hover and forget focus. Or they
     implement disabled as "same as enabled but greyed out" without removing
     pointer events. The matrix forces complete coverage.

     EXAMPLE:
     | Component | Enabled | Hover | Focus | Pressed | Disabled | Loading |
     |-----------|---------|-------|-------|---------|----------|---------|
     | PrimaryButton | bg: accent, text: on-accent | bg: accent-hover | ring: focus-ring, offset: 2px | bg: accent-active, scale: 0.98 | bg: accent, opacity: 0.4, cursor: not-allowed | spinner replaces label, width locked | -->

| Component | Enabled | Hover | Focus | Pressed | Disabled | Loading |
|-----------|---------|-------|-------|---------|----------|---------|
| | | | | | | |


## Data Binding

<!-- Map each dynamic element to its data source. This prevents agents
     from inventing field names or guessing at truncation behavior.

     EXAMPLE:
     | Element | Source Field | Format | Constraints |
     |---------|-------------|--------|-------------|
     | User name | user.displayName | string | Truncate at 24 chars with ellipsis |
     | Member count | tribe.members.length | number | Comma-separated thousands |
     | Avatar | user.avatarUrl | image | Fallback: initials → generic icon |
     | Timestamp | item.createdAt | relative | "2h ago", "3d ago", then full date |
     | Bio | user.bio | string | Max 280 chars, line clamp at 3 lines | -->

| Element | Source Field | Format | Constraints |
|---------|-------------|--------|-------------|
| | | | |


## Interactions & Motion

<!-- Separate trigger/response pairs from motion specification.

     AGENT FAILURE MODE: Agents produce technically functional animations
     that create unusable visual results. "Smooth transition" means nothing.
     Specify duration token, easing curve, and what property animates.

     If your project doesn't tokenize motion, define the values here and
     note that they should be extracted into tokens. -->

### Interactions

<!-- For each user action, specify the trigger, response, and any
     conditions or debounce behavior.

     EXAMPLE:
     | Trigger | Target | Response | Notes |
     |---------|--------|----------|-------|
     | Click row | DataTable row | Navigate to detail view | Entire row is clickable, not just text |
     | Hover card | ProjectCard | Elevate from level-1 to level-2 | 150ms ease-out |
     | Scroll past header | PageHeader | Shrink to compact variant, sticky | Threshold: 64px scroll offset |
     | Type in search | SearchInput | Filter results after 300ms debounce | Show inline spinner during filter | -->

| Trigger | Target | Response | Notes |
|---------|--------|----------|-------|
| | | | |

### Motion

<!-- Define animation tokens used in this feature. Each entry needs
     duration, easing, and the property that animates.

     EXAMPLE:
     | Name | Duration | Easing | Property | Usage |
     |------|----------|--------|----------|-------|
     | state-change | 150ms | ease-out | background, border-color | Hover/focus transitions |
     | enter | 200ms | ease-out | opacity, transform | Elements appearing |
     | exit | 150ms | ease-in | opacity | Elements disappearing |
     | expand | 250ms | ease-in-out | height, opacity | Accordion, drawer open |

     Reduced motion policy: replace all animations with instant state
     changes (opacity crossfade at most). Never remove the state change
     itself, only the motion. -->

| Name | Duration | Easing | Property | Usage |
|------|----------|--------|----------|-------|
| | | | | |

**Reduced motion policy:**


## Responsive Behavior

<!-- Specify what changes at each breakpoint. Not "it stacks on mobile."
     Which regions reorder? Which hide entirely? Which components switch
     variants (e.g., full table → card list)? What's the minimum viable
     mobile experience?

     EXAMPLE:
     | Breakpoint | Columns | Behavior |
     |------------|---------|----------|
     | < 640px | 1 | Sidebar hidden, nav collapses to hamburger. Cards stack vertically. Table switches to card list. KPI grid: 1 column. |
     | 640–1024px | 2 | Sidebar overlay on toggle. Cards: 2-column grid. Table: horizontal scroll. |
     | 1024–1280px | 3 | Sidebar visible, fixed width. Full table. Cards: 3-column grid. |
     | > 1280px | 3 | Same as above, max-width container, margins grow. |

     AGENT FAILURE MODE: Agents implement desktop layout and add a single
     media query that sets everything to width: 100%. Specify the actual
     layout changes per breakpoint, including which components swap to
     a mobile variant vs. which simply reflow. -->

| Breakpoint | Columns | Behavior |
|------------|---------|----------|
| | | |


## Accessibility

<!-- Embed accessibility per component, not as a separate afterthought.
     If this section is empty, the implementation won't be accessible.

     AGENT FAILURE MODE: Agents add aria-label to everything and call it
     done. Specify the actual keyboard model, focus management, and
     screen reader behavior per interactive component. -->

### Keyboard Navigation

<!-- Tab order through interactive elements. Which components trap focus
     (modals, dropdowns)? Which keyboard shortcuts exist?

     EXAMPLE:
     | Component | Keys | Behavior |
     |-----------|------|----------|
     | DataTable | Arrow Up/Down | Move row focus |
     | Modal | Tab | Cycle within modal, trap focus |
     | Modal | Escape | Close, return focus to trigger |
     | Dropdown | Enter/Space | Open; arrow keys navigate items | -->

| Component | Keys | Behavior |
|-----------|------|----------|
| | | |

### ARIA & Screen Reader

<!-- Roles, labels, and live regions. Specify what gets announced and when.

     EXAMPLE:
     | Component | Role | ARIA | Announcement |
     |-----------|------|------|--------------|
     | StatusBadge | status | aria-live="polite" | "Build status: passing" |
     | SearchInput | search | aria-label="Search projects" | Results count announced on update |
     | Toast | alert | aria-live="assertive" | Full message text read immediately | -->

| Component | Role | ARIA | Announcement |
|-----------|------|------|--------------|
| | | | |

### Contrast & Targets

<!-- Call out any elements near the 4.5:1 contrast threshold or touch
     targets below 44x44px. If all tokens are contrast-safe by design,
     state that and reference where the guarantees are documented. -->


## Content Constraints

<!-- Text length limits, truncation rules, and placeholder requirements.
     Agents need these to handle edge cases (very long names, empty fields,
     single-character values) correctly.

     EXAMPLE:
     | Element | Min | Max | Overflow | Placeholder |
     |---------|-----|-----|----------|-------------|
     | Project name | 1 char | 64 chars | Ellipsis after 1 line | "Untitled Project" |
     | Description | — | 280 chars | Line clamp at 3 lines | "No description" |
     | Tag | 1 char | 24 chars | Truncate with ellipsis | — |
     | Avatar alt text | — | — | — | "{User's first name}'s avatar" | -->

| Element | Min | Max | Overflow | Placeholder |
|---------|-----|-----|----------|-------------|
| | | | | |


## Implementation Notes

<!-- Platform-specific guidance, known gotchas, performance considerations.
     This is the "save the agent from the pitfalls you already know about"
     section.

     EXAMPLES:
     - "This component uses `position: sticky`, which breaks inside
       elements with `overflow: hidden`. Ensure no ancestor sets overflow."
     - "The virtualized list requires `estimatedItemSize` for smooth
       scrolling. Without it, the scrollbar jumps on first render."
     - "Safari doesn't support `gap` in flexbox before 14.1. If supporting
       older Safari, use margin-based spacing as a fallback."
     - "Do: use the `surface` class for elevated elements. Don't: apply
       shadow without a corresponding border." -->


## Verification Criteria

<!-- How does a reviewer (human or agent) confirm the implementation
     matches this spec? List measurable, binary checks.

     EXAMPLE:
     - [ ] Token audit passes with zero hardcoded color/spacing/font values
     - [ ] All interactive components have visible focus indicators
     - [ ] Tab order matches the sequence defined in Accessibility section
     - [ ] Empty, loading, and error states render correctly for every region
     - [ ] Layout matches breakpoint table at 640px, 1024px, and 1280px
     - [ ] No text element uses a raw font-size; all use typography role classes
     - [ ] Reduced motion: all animations replaced with instant transitions
           when `prefers-reduced-motion: reduce` is active -->


## Figma / Visual Reference

<!-- Link to Figma file/frame, screenshot, or reference image.
     Figma is the source of truth for visual design. This spec is the
     source of truth for behavior, states, data binding, and spatial
     relationships. The two should agree. If they conflict, this spec wins
     for behavior; Figma wins for pixel-level aesthetics. -->
