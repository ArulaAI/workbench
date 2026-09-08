# Reusable guided artifact editor design QA

## Evidence

- Source visual truth: `/Users/mohitpatel/.codex/generated_images/01a07ce3-33a4-78d3-9107-ffa679b63c91/exec-0cacf73c-3432-4463-a516-f460ffb0676f.png`.
- Source pixels: 1484 × 1060. It was normalized to 1488 × 1060 for comparison, a 0.27% horizontal adjustment with no crop.
- Browser-rendered implementation: `http://127.0.0.1:3000/define/due-date-for-the-individual-task/authoring/prd`.
- Implementation screenshot: `.qa/embedded-editor-selection-v3.png` at 1488 × 1060 pixels and a 1488 × 1060 CSS viewport (device scale factor 1).
- Full-view comparison: `.qa/embedded-editor-comparison-v2.png`; source and implementation are horizontally paired at equal normalized dimensions.
- Focused-region evidence: the full-view source and implementation are legible at original size and both show the selected-text comment composer, so a second crop was unnecessary.
- State: dark theme, connected, generated PRD revision 6, current version selected, Summary text selected, anchored-comment composer open.

## Findings

No actionable P0, P1, or P2 findings remain.

- Fonts and typography: the existing Inter/IBM Plex Mono design-system pairing is preserved. Heading scale, toolbar labels, metadata, counts, and body copy have a clear hierarchy. Markdown punctuation remains visible in the editable body by design; this is a P3 fidelity difference from the richer source editor, but it keeps the implementation lightweight and predictable.
- Spacing and layout rhythm: the 40/60 chat-and-editor split, fixed toolbar, document header, scrollable editing surface, and lower-right selection composer follow the source composition. Panel borders, radii, gutters, and dense control spacing match the established SPEED dashboard.
- Colors and visual tokens: existing SPEED background, surface, border, secondary text, and teal accent tokens are reused. Selection highlighting and the comment composer clearly share the same anchored-review state.
- Image quality and asset fidelity: the target contains no product imagery. Existing navigation and Lucide toolbar icons remain sharp; no placeholder art or approximate asset was introduced.
- Copy and content: real persisted PRD content is shown. The live fixture has a longer legacy intake description than the mock, so its chat history is denser; this is test-data variance, not layout drift. New intake is now capped at 500 characters.
- Affordances and accessibility: version, Save, undo, redo, text style, bold, italic, lists, link, and table controls have accessible names. The global change composer and selected-text composer communicate their distinct scopes.
- Responsiveness: desktop was the supplied target. The existing authoring breakpoint stacks the regions below 1150px without hiding persistent editor controls.

## Comparison history

1. First capture `.qa/embedded-editor-v1.png` exposed a P2 document-header mismatch: the PRD title and metadata table were compressed and visually unstructured. The header now uses the existing rendered Markdown treatment, producing the post-fix title and table visible in `.qa/embedded-editor-selection-v3.png` and `.qa/embedded-editor-comparison-v2.png`.
2. The post-fix comparison found no remaining P0/P1/P2 mismatch. The raw Markdown editing body and floating rather than line-tethered composer are intentional lightweight-editor choices; the exact selected text, section, offsets, and revision are retained as the comment anchor.

## Primary interactions tested

- Opened an existing generated PRD in the new embedded right-panel editor.
- Selected document text and verified the anchored comment composer captured the quote and owning section.
- Added the anchored comment to the pending review queue without regenerating immediately.
- Typed into the editor, verified Save became enabled, used Undo, and verified Save returned to disabled.
- Verified the new intake truncates programmatic input at 500 characters and renders `500 / 500`.
- Checked the browser console after the final interaction pass; no warnings or errors were recorded.

## Follow-up polish

- P3: a future richer editor could visually suppress Markdown markers while retaining Markdown persistence.
- P3: the selected-text composer could track the exact selection rectangle instead of using a stable lower-right position.

## Reusable lifecycle extension

- Final browser state: `http://127.0.0.1:3000/define/let-workspace-owners-add-optional-approval-rules-t/authoring/prd`.
- Final screenshot: `.qa/reusable-authoring-final-v3.png`.
- Equal-canvas source comparison: `.qa/reusable-authoring-comparison.png`, with the approved source on the left and the implementation on the right.
- Intake now exposes PRD, Design, and Technical RFC as one compact artifact switcher. Design and RFC select an upstream PRD before opening the same interview/editor shell.
- A real 229-character PRD brief produced two model-selected clarification questions. The browser run then covered draft generation, direct editor save, global in-chat feedback, model-backed regeneration, publishing, and historical version selection.
- The same feature generated and published a linked Design document and Technical RFC. Both use their own question banks while preserving the shared editor, comments, counts, formatting controls, publish action, and version dropdown.
- Published state is shown consistently in the workspace bar, version option, action button, and rendered document metadata.
- The final side-by-side comparison found no actionable P0, P1, or P2 visual regressions. The implementation preserves the target's dark split layout, dense chat history, embedded document surface, teal state accents, compact editor controls, and readable hierarchy.

## Release verification

- Fresh intake capture: `.qa/release-new-authoring.png`.
- Fresh selected-text review capture: `.qa/release-inline-comment.png`.
- Fresh immutable-history capture: `.qa/release-version-history-final.png`.
- The historical-version state now distinguishes `Draft history` from `Published history`, disables all editing controls, and keeps the current published revision untouched.
- Publishing is idempotent at the helper boundary and synchronizes the compatibility draft record plus the Define package index with the published revision and history.
- Release gate: optimized Next.js build passed; 148 feature-adjacent backend tests and 44 guided frontend tests passed.

## Editor header and rendered-view refinement

- Source visual truth: `/var/folders/xt/5jbmrqfj4rv1cjxk9v8nxm_h0000gq/T/codex-clipboard-1e3b82c4-75b2-4870-b891-ad0e8dcf5463.png` at 3006 × 1810 pixels.
- The source app viewport was cropped below the browser chrome and normalized to 1280 × 720. The in-app implementation was captured at 1280 × 720 CSS pixels with device scale factor 1.
- Final Edit state: `.qa/editor-topbar-edit-final.png`.
- Final View state: `.qa/editor-topbar-view-final.png`.
- Equal-canvas comparison: `.qa/editor-topbar-comparison-final.png`, source on the left and implementation on the right.
- Focused comparison was unnecessary because the top-bar actions, editor toolbar, metadata, and first document sections are legible at original comparison size.
- State: dark theme, connected, current PRD draft v6, no unsaved changes.
- No actionable P0, P1, or P2 findings remain. Typography, spacing, SPEED color tokens, Lucide control icons, and app-specific copy stay consistent with the existing authoring surface. The source contains no raster product imagery.
- Interaction verification covered Edit → View → Edit, complete Markdown rendering, a real `Review & commit` handoff to the existing Define commit workspace, and one shared scroll container containing both metadata and CodeMirror content (`1661px` content in a `498px` viewport).

### Comparison history

1. The first implementation capture `.qa/editor-topbar-edit.png` revealed a P2 toolbar wrap at 1280px: the final table-format control dropped to a second row. Word and character counts moved into the editor header and the formatting toolbar became a single horizontal row.
2. The post-fix capture `.qa/editor-topbar-edit-final.png` keeps every control aligned at the supplied viewport. The final comparison found no remaining P0/P1/P2 mismatch.

final result: passed
