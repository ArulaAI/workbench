# SPEED — Project Conventions

## Folder conventions

- `docs/` — User-facing documentation. Published to the docs site. Only put content here that end users should read.
- `working-docs/` — Internal working documents: audits, research, session handoffs, design explorations. Never published.
- `site/` — Astro project for the landing page and docs site.

## Writing style

When writing documentation, prose, or any user-facing text, follow these rules. They exist because the default output patterns are recognizable, repetitive, and hard to read.

### Banned patterns

**Structural crutches to avoid:**

- Em-dashes. Do not use them as parenthetical filler. Rewrite the sentence to not need one, or use parentheses if you must. One em-dash per page is a maximum, not a target.
- Sentence mirroring. Never repeat the same grammatical skeleton across consecutive sentences. "X does Y. Z does W. A does B." reads like a template, not writing. Vary the structure.
- The "**Bold claim.** Then explanation." pattern. Using it once is fine. Using it for every item in a section is a formatting tic. Mix it up: lead with the explanation sometimes, use a different emphasis mechanism, or just write a paragraph.
- Defaulting to three. Not everything comes in threes. If there are two points, write two. If there are five, write five. Do not pad to three or trim to three.
- "This means:" or "This enables:" followed by a bullet list. Find another way to elaborate. Write a sentence. Use a table. Draw a diagram. The colon-then-bullets pattern is a crutch.
- Starting paragraphs with "This". ("This is...", "This goal...", "This extends..."). It creates a monotone cadence across paragraphs. Vary your openings.

**Filler and hedging to delete on sight:**

- "It's worth noting that" / "It's important to understand that" / "It should be noted that". Just state the thing.
- "In other words" / "To put it another way" / "Said differently". If you need to restate, the first version was unclear. Fix it instead of doubling.
- Summary sentences that restate the paragraph. If the paragraph said SPEED does X, do not end with "In short, SPEED does X." The reader just read it.
- "Let's look at" / "Let me explain" / "Let's dive into". Just start.

**Tone to avoid:**

- "Not X, but Y" as a rhetorical device ("not into hoping agents figure it out, but into pre-computing context"). Once is fine. Repeating it is a verbal tic.
- Sycophantic preambles. No "Great question!", "You're right!", "Good point!" before answering.
- Faux-conversational transitions between sections.

### Formatting rules

- No walls of text. If a paragraph exceeds 4-5 sentences, it probably needs to be broken up, restructured as a list, or split into subsections.
- Numbered and bulleted lists that exceed ~5 items need a mini table of contents or section header preceding them so the reader knows what they're scanning.
- Long pages (5+ sections) need a brief orientation at the top: what the page covers, who it's for, or how it's structured. Not a generic intro paragraph. A sentence or two that helps the reader decide whether to keep reading.
- Use a table when comparing items across dimensions. Do not write "X has property A. Y has property B. Z has property C." when a three-row table communicates the same thing at a glance.
- Use a diagram or ASCII figure when describing flows, pipelines, or relationships between components. If you find yourself writing "A feeds into B, which produces C, which is consumed by D", draw it instead.
- Cross-reference, don't restate. If another page explains a concept, link to it. Do not re-explain it in abbreviated form that will inevitably drift from the source.

### Content approach

- Lead with the concrete, not the abstract. A specific example, a real scenario, or a data point lands faster than a principle statement. State the principle after the reader has something to anchor it to.
- Write for the reader's question, not the system's structure. Organize by what someone wants to know, not by how the internals are arranged.
- Every claim that references external research or prior work should include the specific finding, not just the attribution. "Meta's CCA ablation study found context management alone added +6.6pp to resolve rate" carries weight. "Meta proved this empirically" does not.

## Dashboard design language

The design system lives in `dashboard/frontend/app/globals.css`. All tokens, surfaces, typography ladder, and component base classes are defined there. Read that file before making any UI changes to the dashboard.

Reference vibe: Linear meets a spacecraft HUD. Information-dense, calm under load, depth that guides the eye.

### Rules that CSS cannot enforce

- **Accent is for hero metrics and primary actions only.** A KPI card's main value, an active nav link, a primary button. Applying accent to secondary text, borders everywhere, or decorative elements dilutes it into noise.
- **IBM Plex Mono is for numbers and technical content.** KPI values, metric columns, code references, the brand mark, table column headers. Inter handles everything else. Mixing them outside these roles breaks the visual hierarchy.
- **Never set font size without also setting weight and color.** Random combinations of size/weight create the "no layering" feeling. Use the `.type-*` classes from globals.css or follow the exact role definitions in the typography ladder comment.
- **Depth comes in pairs: border + shadow.** No flat background-only cards. No borders without shadow. No shadows without borders. The `.surface` class in globals.css enforces this; use it on every elevated element.
- **Tertiary text is decorative only.** Timestamps, dividers, disabled labels. If someone needs to read it to use the dashboard, it should be `--text-secondary` at minimum.
- **No pure white (#fff).** The brightest text token is `--text` (#e4e4e9). Pure white is harsh against the deep backgrounds.
- **4px spacing grid.** All spacing values should be multiples of 4. Page padding 24px, card gaps 16px, card internal padding 20px, table row height 40px.
