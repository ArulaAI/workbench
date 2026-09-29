# Business-domain Discover design

Status: Proposed

> Product requirements: [Business Domain Discovery](../product/speed-business-domain-discovery.md)
> Technical contract: [Business Domain Discovery RFC](../tech/speed-business-domain-discovery.md)
> Existing dashboard tokens: [globals.css](../../dashboard/frontend/app/globals.css)

## Summary

Discover explains what an unfamiliar repository does for the business, how its
responsibilities relate, how behavior is implemented and which source evidence
supports every conclusion. The experience must remain useful with 10, 100 or
1,000 proposed domains without hiding them behind status filters or presenting
inferred architecture as fact.

A developer can search for refund, preview **Payments**, read a plain-language
brief, inspect its proposed boundary and business behavior, follow an activity
through its implementation and open the exact source evidence. If browser and
API rules disagree, Discover preserves both observations and any unknown
production override.

All Payments examples in this document are hypothetical UI contract examples.
They are not executed output and do not claim that a repository contains those
facts.

## Current problem and expected result

The existing product problem is a structural file cluster presented as a business
domain. A technical label such as repository/pet does not explain the business
responsibility and can imply a boundary the evidence does not establish.

The expected result separates four questions:

| View | Question | Primary reader |
| --- | --- | --- |
| Brief | What does this business area do? | Any repository user |
| Domain model | What language, responsibilities, behavior and boundaries are proposed? | Domain expert, lead or engineer |
| Implementation | Which applications, operations, stores and source symbols implement it? | Engineer |
| Evidence | What exactly supports or limits each claim? | Reviewer or engineer |

These are projections of one canonical artifact, not separately authored truths.

## Verified contracts and design limits

The product and RFC establish these facts:

- Domains are proposed business responsibilities and remain open to human review.
- The artifact records a name, summary, activity memberships, business concepts,
  rules, information ownership, boundary rationale, exclusions, alternatives,
  relationships, claims, evidence support and review state.
- Evidence support is supported, partial or insufficient. It is not a probability.
- Review state is proposed, accepted, rejected or needs review.
- Business boundaries, deployment boundaries and code-module boundaries are
  distinct and require separate evidence.
- Reads never invoke synthesis, and failed or cancelled builds preserve the last
  valid published result.
- Rename, merge, split and membership changes are explicit review operations.

The current canonical artifact does not define aggregates, aggregate roots,
entities, value objects or DDD strategic classification. Therefore:

- Discover may present a DDD-informed strategic view from existing domain,
  concept, ownership, relationship and boundary records.
- It must not call every business domain a bounded context.
- It must not classify a domain as core, supporting or generic without a future
  authoritative contract or an explicit human decision.
- It must not promote similarly named classes into tactical DDD elements.
- The Tactical view must say **Not established** until the contract supports it.

## Research-backed representation model

DDD has no single universal diagram. Established approaches use complementary
representations:

| Representation | Use in Discover |
| --- | --- |
| Bounded Context Canvas | Human-readable purpose, language, decisions, communication, assumptions and open questions |
| Domain Storytelling | Actor-centered business scenarios and work objects |
| Context map | Small strategic views of domain relationships for a specific question |
| Tactical model | Aggregates, entities, value objects, services and domain events only when explicitly supported |
| C4-inspired trace | Evidenced technical implementation boundaries |
| Source navigator | Exact evidence, revision, location and unresolved gaps |

The design uses small maps for explicit questions. A 100-node graph is never the
default catalog or the only navigation path.

## Information architecture

```text
/discover/domains
├── ?selected=:domainId
└── :domainId
    ├── brief
    ├── model
    │   ├── strategic
    │   ├── behavior
    │   └── tactical
    ├── implementation
    ├── evidence
    └── history
/discover/activities
/discover/rules
/discover/context-map
/discover/unresolved
/discover/history
```

Search, filters, sort, selected item and active inspector are URL state.
Selection replaces URL state; opening a dedicated page pushes history.

## Shared adaptive shell

Desktop uses navigation, collection and detail panes. Mobile uses list-to-detail
navigation rather than compressing three panes.

```text
Desktop: global navigation → searchable collection → preview or inspector
Mobile:  collection → detail → full-height inspector sheet
```

```text
┌───────────────────────────────────────────────────────────────────────────────────────────────┐
│ ☰   Discover                                  ⌘K Search    PetClinic · main@abc1234 ▾    •••│
├────────────────┬──────────────────────────────────────────────────────────────────────────────┤
│ DISCOVER       │ Current destination                                                          │
│                │                                                                              │
│ ● Domains      │ Destination content                                                          │
│   Activities   │                                                                              │
│   Rules        │                                                                              │
│   Context map  │                                                                              │
│                │                                                                              │
│ REVIEW         │                                                                              │
│   Unresolved 12│                                                                              │
│                │                                                                              │
│ ANALYSIS       │                                                                              │
│   History      │                                                                              │
└────────────────┴──────────────────────────────────────────────────────────────────────────────┘
```

The sidebar contains destinations, not filters. Only actionable exceptions use a
badge. Command-K opens repository-wide search; slash focuses the current list.

## Shared interaction model

| Input | Result |
| --- | --- |
| Click or arrow to a row | Select it and update the adjacent preview without navigation |
| Return on a selected row | Open its dedicated page |
| Double-click a row on desktop | Same as Return; never the only open gesture |
| Click a disclosure | Expand or collapse detail without navigation |
| Escape | Close the topmost popover, sheet or inspector and restore focus |
| Browser Back | Restore route, query, filters, selection and scroll |
| Share | Copy a canonical URL containing the current view state |

Browse screens are read-only. Rename, merge, split, membership and boundary
decisions exist only in Review. No required interaction depends on drag, hover,
double-click or long press.

## 1. Domain catalog

The catalog is the default screen. It uses compact rows and virtual scrolling,
not cards or pagination. All domains remain in one predictable list.

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ☰   Discover                                      ⌘K Search    PetClinic · main@abc1234 ▾   •••│
├────────────────┬─────────────────────────────────────────────────┬────────────────────────────────┤
│ DISCOVER       │ Domains                                     100 │ DOMAIN PREVIEW                 │
│                │                                                 │ Payments                       │
│ ● Domains      │ ┌─────────────────────────────────────────────┐ │ Responsibility proposal        │
│   Activities   │ │ 🔍 Search domains…                        │ │                                │
│   Rules        │ └─────────────────────────────────────────────┘ │ Moves and reverses money between│
│   Context map  │ Filter                            Sort: Name ▾ │ customers and merchants.       │
│                │                                                 │                                │
│ REVIEW         │ ALL DOMAINS                                     │ ◐ Partial · Needs review       │
│   Unresolved 12│                                                 │ [ Open domain ]            Hide│
│                │   Merchant settlement                          › │                                │
│ ANALYSIS       │   Notifications                               › │ WHY GROUPED                    │
│   History      │   Orders                                      › │ Shared payment purpose, rules  │
│                │                                                 │ and maintained information.  → │
│                │ ┌─────────────────────────────────────────────┐ │                                │
│                │ │ Payments                                    │ │ PRIMARY BEHAVIOR               │
│                │ │ Moves and reverses money                    │ │ Capture payment             → │
│                │ │ Needs review                              › │ │ Issue refund                → │
│                │ └─────────────────────────────────────────────┘ │ Settle merchant funds        → │
│                │                                                 │                                │
│                │   Pricing                                     › │ LANGUAGE                       │
│                │   Promotions                                  › │ Payment · Charge · Refund    → │
│                │   Reporting                                   › │                                │
│                │   Returns                                     › │ 14 evidence records          → │
│                │                                             ▐   │ Published 8 minutes ago        │
└────────────────┴─────────────────────────────────────────────────┴────────────────────────────────┘
```

Interaction contract:

- Click selects the entire row and updates selected-domain URL state and preview.
- Return, double-click or **Open domain** opens the Brief and preserves catalog state.
- Search matches name, purpose, activity, concept, rule and source path; it uses
  Name sorting without a query and Relevance while searching.
- Filter opens an anchored popover. Applied filters become removable tokens.
- Sort preserves selection and scrolls the selected row into view.
- Hide collapses the preview and gives its width to the catalog per device.
- Why grouped opens the strategic boundary rationale.
- Behavior, language and evidence links open their corresponding domain view.
- Changing repository or revision restores that context's last published state.

If filtering removes the selected domain, selection clears and the preview says
“Select a domain to preview.” Arrow Down from search selects the first result.

### Catalog empty states

No published discovery collapses the unused collection and preview into one
focused surface:

```text
┌────────────────┬──────────────────────────────────────────────────────────────────────────────┐
│ DISCOVER       │                                                                              │
│                │                         ◇                                                    │
│   Domains    — │                 Discover this repository                                     │
│   Activities — │                                                                              │
│   Rules      — │     Build a business view of responsibilities, behavior and evidence.        │
│   Context map  │     Source code is not changed.                                              │
│                │                                                                              │
│ REVIEW         │                  [ Discover repository ]                                      │
│   Unresolved — │                                                                              │
│                │               What will be analyzed?  ›                                      │
│ ANALYSIS       │               Current revision: main@abc1234                                 │
│   History      │                                                                              │
└────────────────┴──────────────────────────────────────────────────────────────────────────────┘
```

A successful zero result says **No supported business domains found** and offers
**Review analyzed scope**. A search-empty state preserves the query and filters,
offers **Clear filters**, and can hand the query to repository-wide search.
Failures are not empty states; they explain what stayed unchanged and offer Retry.

## 2. Domain brief

Brief is the human-readable document. It avoids DDD abbreviations, implementation
types and class names. The selected example continues from Payments in the catalog.

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ‹ Domains    Payments                                      Share       Review proposal ▾     •••│
├────────────────┬─────────────────────────────────────────────────────────┬────────────────────────┤
│ DISCOVER       │ Payments                                                │ DOMAIN STATUS          │
│                │ Business responsibility proposal                        │                        │
│ ● Domains      │                                                         │ Review                 │
│   Activities   │ Brief   Domain model   Implementation   Evidence        │ Needs review           │
│   Rules        │ ─────                                                   │                        │
│   Context map  │                                                         │ Evidence support       │
│                │ PURPOSE                                                 │ ◐ Partial              │
│ REVIEW         │ Moves and reverses money between customers, merchants   │                        │
│   Unresolved 12│ and payment providers.                                  │ Published              │
│                │                                                         │ 8 minutes ago          │
│ ANALYSIS       │ WHAT IT DOES                                            │                        │
│   History      │ • Captures customer payments                            │ 6 activities           │
│                │ • Issues full or partial refunds                        │ 9 rules                │
│                │ • Settles merchant funds                                │ 14 evidence records    │
│                │                                                         │                        │
│                │ IMPORTANT LANGUAGE                                      │                        │
│                │ Payment   Money movement tracked through its lifecycle →│                        │
│                │ Refund    Reversal of some or all of a payment         →│                        │
│                │ Settlement Transfer of funds to a merchant             →│                        │
│                │                                                         │                        │
│                │ TYPICAL SCENARIO                                        │                        │
│                │ Customer requests payment → provider returns outcome →  │                        │
│                │ merchant receives settlement                            │                        │
│                │                                                         │                        │
│                │ NEEDS ATTENTION                                         │                        │
│                │ Browser and API refund-window observations conflict.  → │                        │
└────────────────┴─────────────────────────────────────────────────────────┴────────────────────────┘
```

Interactions:

- Local tabs preserve the selected domain and change only the domain subroute.
- A language term opens its definition and supporting concept evidence.
- A scenario opens Domain model → Behavior at that scenario.
- Needs attention opens the relevant unresolved record.
- Review opens the quick-review sheet; structural changes continue in the editor.
- Share copies the canonical Brief URL.

## 3. Domain model — Strategic

Strategic is a DDD-informed view of the existing contract. It calls the record a
business responsibility proposal, not a bounded context.

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ‹ Payments    Domain model                                      Share      Review proposal ▾   •••│
├────────────────┬─────────────────────────────────────────────────────────┬────────────────────────┤
│ DOMAIN MODEL   │ Strategic   Behavior   Tactical                         │ INTERPRETATION         │
│                │ ─────────                                               │                        │
│ ● Strategic    │ RESPONSIBILITY                                          │ Business domain        │
│   Behavior     │ Moves and reverses money between customers and merchants│ Proposed               │
│   Tactical     │                                                         │                        │
│                │ UBIQUITOUS LANGUAGE                                     │ Bounded context        │
│                │ Payment · Charge · Refund · Settlement · Merchant      │ Not established        │
│                │                                                         │                        │
│                │ INFORMATION RESPONSIBILITY                              │ Classification         │
│                │ Payment lifecycle        maintains · partial evidence  →│ Not established        │
│                │ Refund record            creates · supported evidence  →│                        │
│                │                                                         │ Evidence support       │
│                │ WHY THESE ACTIVITIES BELONG TOGETHER                     │ ◐ Partial              │
│                │ They share payment purpose, rules and maintained data. →│                        │
│                │                                                         │ Review state           │
│                │ BOUNDARY QUESTIONS                                      │ Needs review           │
│                │ Included: Capture, refund and settlement behavior       │                        │
│                │ Excluded: Generic navigation                            │                        │
│                │ Alternative: Settlement may be a separate responsibility│                       │
│                │                                                         │                        │
│                │ RELATIONSHIPS                                            │                        │
│                │ Orders   ─ requests action from ─▶ Payments            │                        │
│                │ Payments ─ publishes event to ───▶ Ledger              │                        │
│                │                              Open focused context map  → │                        │
└────────────────┴─────────────────────────────────────────────────────────┴────────────────────────┘
```

Interactions:

- Strategic, Behavior and Tactical are stable, linkable subroutes.
- A language or information record opens an inspector with meaning and evidence.
- Boundary rationale, exclusion or alternative opens its supporting claims.
- A relationship selects it; the inspector shows direction, activities and evidence.
- **Open focused context map** opens the same domain and relationship filters.
- No context-map pattern appears unless a contract or reviewer establishes it.

## 4. Domain model — Behavior

Behavior combines a searchable activity list with a Domain Storytelling
projection. It represents one evidenced scenario, not every possible branch.

```text
┌────────────────┬─────────────────────────────────────┬───────────────────────────────────────────┐
│ DOMAIN MODEL   │ Behavior                         6 │ Request a refund                          │
│                │ ┌─────────────────────────────────┐ │ Customer submits a payment and reason.    │
│   Strategic    │ │ 🔍 Search behavior…           │ │                                           │
│ ● Behavior     │ └─────────────────────────────────┘ │ STORY                                     │
│   Tactical     │                                     │ 1                       2                 │
│                │ ● Request a refund               › │ Customer ─ submits ─▶ Refund request     │
│                │   Customer → decision → outcome    │                          │ evaluates       │
│                │                                     │                    ┌────▼─────┐            │
│                │   Check refund eligibility       › │                    │ Policy   │            │
│                │   Policy → eligible or rejected    │                    └──┬────┬──┘            │
│                │                                     │                     ▼          ▼          │
│                │   Issue refund                    › │                  Receipt    Rejection      │
│                │   Agent → reversal → confirmation  │                                           │
│                │                                     │ INPUTS                                    │
│                │   Settle merchant funds          › │ Payment reference · Reason                │
│                │                                     │                                           │
│                │                                     │ RULES                                     │
│                │                                     │ Refund window · Payment status          → │
│                │                                     │                                           │
│                │                                     │ ◐ Remote payment outcome not established. │
└────────────────┴─────────────────────────────────────┴───────────────────────────────────────────┘
```

Interactions:

- Clicking an activity updates the story without leaving the page; Return opens
  a shareable activity route.
- Selecting an actor, work object or activity highlights connected steps and
  updates the inspector.
- Story, Steps and Rules are synchronized textual and visual projections.
- A rule opens its comparison view. An unresolved note opens its evidence gap.
- **View implementation** opens the same activity in Implementation.

## 5. Domain model — Tactical

The current contract cannot truthfully populate a tactical DDD model. The screen
must explain that distinction rather than manufacture one from the code.

```text
┌────────────────┬──────────────────────────────────────────────────────────────────────────────┐
│ DOMAIN MODEL   │ Tactical model                                                               │
│                │                                                                              │
│   Strategic    │                              ◇                                               │
│   Behavior     │                                                                              │
│ ● Tactical     │                 No tactical DDD model established                             │
│                │                                                                              │
│                │ Discovery identified business concepts, rules and information responsibility,│
│                │ but it did not establish aggregates, entities, value objects or domain        │
│                │ services. Class and table names are not sufficient evidence.                  │
│                │                                                                              │
│                │             [ View business concepts ]   [ View implementation ]               │
│                │                                                                              │
│                │ What would be required?  ›                                                    │
└────────────────┴──────────────────────────────────────────────────────────────────────────────┘
```

**What would be required?** explains the missing canonical fields and evidence.
If a future contract supplies reviewed tactical elements, this screen becomes an
aggregate-centered navigator. That future state is out of scope for this design
and must not be mocked as existing production capability.

## 6. Focused context map

The map is strategic DDD navigation. It opens around one selected proposal and
its immediate neighbors. List is an equivalent accessible representation.

```text
┌────────────────┬──────────────────────────────────────────────────────┬─────────────────────────┐
│ DISCOVER       │ Context map     [Map | List]   Focus: Payments ▾   │ RELATIONSHIP            │
│                │                                                      │                         │
│   Domains      │ 🔍 Find domain…     Depth: 1 ▾   − 100% +  Fit    │ Orders → Payments       │
│   Activities   │                                                      │ requests action from    │
│   Rules        │                 ┌──────────────┐                     │                         │
│ ● Context map  │                 │ Orders       │                     │ From activity           │
│                │                 └──────┬───────┘                     │ Submit order            │
│ REVIEW         │                        │ requests action             │                         │
│   Unresolved 12│                        ▼                             │ To activity             │
│                │ ┌──────────────┐  ┌══════════════┐  ┌─────────────┐│ Capture payment         │
│ ANALYSIS       │ │ Refunds      │─▶│ Payments     │─▶│ Ledger      ││                         │
│   History      │ └──────────────┘  └══════╤═══════┘  └─────────────┘│ DDD pattern             │
│                │                          │ publishes event           │ Not established         │
│                │                          ▼                           │                         │
│                │                   ┌──────────────┐                   │ 3 evidence records    → │
│                │                   │ Reporting    │                   │ Open domain           → │
│                │                   └──────────────┘                   │                         │
│                │ ─── supported  ╌╌ partial  Showing 4 of 100       │                         │
└────────────────┴──────────────────────────────────────────────────────┴─────────────────────────┘
```

Interactions:

- Click a node to select it; double-click or **Open domain** opens its Brief.
- Click an edge to inspect direction, participating activities and evidence.
- Map/List preserves focus, depth, selection and filters.
- Search selects and centers a result. Depth reveals one level at a time.
- Pan and zoom never change selection. Fit frames the visible graph.
- Nodes stop moving after layout. Browse mode cannot drag or reposition them.

## 7. Implementation

Implementation is a C4-inspired activity trace, not the DDD model. C4 labels
appear only where deployment boundaries are established; otherwise neutral terms
such as application, entry point and source operation are used.

```text
┌────────────────┬──────────────────────────────────────────────────────┬─────────────────────────┐
│ PAYMENTS       │ Implementation                                       │ SELECTION               │
│                │ Activity: Request a refund ▾   Trace  Files  Calls   │                         │
│   Brief        │                                                      │ Refund policy operation │
│   Domain model │ ① Browser application                                │ Checks repository-local │
│ ● Implementation│ ┌────────────────────────────────────────────────┐  │ eligibility.            │
│   Evidence     │ │ CustomerRefundRequestForm.tsx                  │  │                         │
│                │ └─────────────────────┬──────────────────────────┘  │ Boundary                │
│                │                       │ POST /refund-requests        │ Code component          │
│                │                       ▼                             │                         │
│                │ ② API entry point                                    │ Evidence                │
│                │ ┌────────────────────────────────────────────────┐  │ 4 files · 7 symbols     │
│                │ │ create_refund_request()                       │  │                         │
│                │ └────────────┬──────────────────────┬────────────┘  │ Open evidence        → │
│                │              │ checks               │ writes         │                         │
│                │              ▼                      ▼                │                         │
│                │ ┌────────────────────┐  ┌────────────────────────┐  │                         │
│                │ │ Policy operation   │  │ Refund repository      │  │                         │
│                │ └─────────┬──────────┘  └────────────────────────┘  │                         │
│                │           ┊ delegates                                │                         │
│                │           ▼                                          │                         │
│                │    External policy · unresolved                      │                         │
└────────────────┴──────────────────────────────────────────────────────┴─────────────────────────┘
```

Interactions:

- Changing Activity replaces the trace and preserves the projection.
- Trace, Files and Calls are synchronized projections of the same records.
- Clicking a node or edge updates the inspector without navigation.
- A source or **Open evidence** action opens the exact Evidence record.
- Business-domain, deployment and code boundaries use distinct labels.

## 8. Evidence

Evidence is the authoritative source navigator for every displayed claim. Source
text is inert, selectable text pinned to a revision.

```text
┌────────────────┬────────────────────────────────┬─────────────────────────────────────────────┐
│ PAYMENTS       │ Evidence                    14 │ API refund-window enforcement              │
│                │ ┌────────────────────────────┐ │ Supported observation                       │
│   Brief        │ │ 🔍 Search evidence…       │ │                                             │
│   Domain model │ └────────────────────────────┘ │ src/refunds/policy.py                        │
│   Implementation│ Group: Claim ▾   Filter      │ Lines 42–48 · main@abc1234                   │
│ ● Evidence     │                                │                                             │
│                │ REFUND REQUEST WINDOW       3 │ 42  if purchase_age > refund_window:        │
│                │ ● API enforcement           › │ 43      raise NotEligible(                   │
│                │   Browser declaration       › │ 44          "expired"                        │
│                │   Default configuration     › │ 45      )                                    │
│                │                                │                                             │
│                │ PAYMENT MUST EXIST         2 │ SUPPORTS                                    │
│                │   Repository lookup         › │ “API rejects requests older than the        │
│                │   Missing-payment branch    › │ configured refund window.”                   │
│                │                                │                                             │
│                │                                │ Previous       1 of 14       Next            │
│                │                                │ Open file     Copy link                      │
└────────────────┴────────────────────────────────┴─────────────────────────────────────────────┘
```

Interactions:

- Click an observation to update evidence URL state and inspector.
- Search matches source path, symbol, excerpt and supported claim.
- Previous and Next follow current filtered order.
- Open file opens the source viewer at the pinned revision and line.
- Copy link confirms passively. Filter changes retain a matching selection.

## 9. Cross-domain activities

The global activity catalog answers “what can this repository do?” Domain-local
behavior reuses the same collection component with its domain filter locked.

```text
┌────────────────┬──────────────────────────────────────────────────┬─────────────────────────────┐
│ DISCOVER       │ Activities                                  284 │ Request a refund            │
│                │ ┌──────────────────────────────────────────────┐  │                             │
│   Domains      │ │ 🔍 Search activities…                     │  │ Customer submits a payment │
│ ● Activities   │ └──────────────────────────────────────────────┘  │ and reason for review.      │
│   Rules        │ Filter    Group: Domain ▾   Sort: Relevance ▾ │                             │
│   Context map  │                                                  │ Domain                      │
│                │ PAYMENTS                                      6 │ Payments                    │
│ REVIEW         │ ● Request a refund                           › │                             │
│   Unresolved 12│   Check refund eligibility                  › │ Actor · outcome             │
│                │   Issue refund                               › │ Customer · Receipt          │
│ ANALYSIS       │   Settle merchant funds                      › │                             │
│   History      │                                                  │ 3 rules · 6 evidence records│
│                │ ORDER FULFILLMENT                           8 │                             │
│                │   Place order · Reserve inventory · Ship …     │ Open behavior            →  │
└────────────────┴──────────────────────────────────────────────────┴─────────────────────────────┘
```

Click updates the preview; Return opens Behavior. Search covers activity, actor,
outcome, rule and domain. Grouping changes headers, not results. Navigation
preserves filters, selection and scroll.

## 10. Cross-domain rules

Rules use collection-detail comparison. Observations remain separate by source,
scope and enforcement behavior.

```text
┌────────────────┬───────────────────────────────┬──────────────────────────────────────────────┐
│ DISCOVER       │ Rules                    167 │ Refund request window                        │
│                │ ┌───────────────────────────┐ │ ◐ Conflict · Effective value unknown         │
│   Domains      │ │ 🔍 Search rules…         │ │                                              │
│   Activities   │ └───────────────────────────┘ │ Location     Value      Behavior    Evidence │
│ ● Rules        │ [Conflicts ×]     Filter 1   │ Browser UI   30 days    Declared    Open →   │
│   Context map  │                               │ API          14 days    Enforced    Open →   │
│                │ ATTENTION                  2 │ Config       Override   Effective   Open →   │
│ REVIEW         │ ● Refund request window    › │                          unknown             │
│   Unresolved 12│   Payment authorization    › │                                              │
│                │                               │ WHY UNRESOLVED                               │
│ ANALYSIS       │ OTHER RULES              165 │ Deployment override is outside this          │
│   History      │   Payment must exist      › │ repository.                                  │
│                │   Reason is required      › │                                              │
│                │   One active request      › │ Review conflict                          →   │
└────────────────┴───────────────────────────────┴──────────────────────────────────────────────┘
```

Click updates comparison; Return opens the rule route. Open on an observation
opens exact Evidence. Review conflict opens quick review. Unknown values remain
labels unless a supported next action exists.

## 11. Unresolved queue

Unresolved is a triage list, not a wall of warnings. It states consequence,
evidence gap and next useful action.

```text
┌────────────────┬────────────────────────────────────┬──────────────────────────────────────────┐
│ REVIEW         │ Unresolved                    12 │ Refund request window                    │
│                │ ┌────────────────────────────────┐ │ Conflict                                 │
│   Domains      │ │ 🔍 Search unresolved work…   │ │                                          │
│   Activities   │ └────────────────────────────────┘ │ WHY IT MATTERS                           │
│   Rules        │ Type ▾ Domain ▾ Sort: Impact ▾ │ Users may receive different decisions.   │
│   Context map  │                                    │                                          │
│                │ CONFLICTS                       2 │ OBSERVED                                 │
│ ● Unresolved 12│ ● Refund request window       › │ Browser: 30 days · API: 14 days          │
│                │   Domain boundary alternative › │ Production override: Unknown              │
│                │                                    │                                          │
│ ANALYSIS       │ MISSING EVIDENCE               4 │ NEXT STEP                                │
│   History      │   External refund policy      › │ Confirm deployed configuration or record │
│                │   Tax provider                › │ it as externally managed.                 │
│                │                                    │                                          │
│                │ EXCLUDED                       6 │ Review conflict                       →  │
│                │   Static asset pipeline       › │                                          │
└────────────────┴────────────────────────────────────┴──────────────────────────────────────────┘
```

Click updates detail. Filters update counts and URL state. Evidence values open
their source. Review returns focus and selection to the queue when closed.
Pending live work is never presented as a published unresolved record.

## 12. Quick review

Accept or reject is a short sheet. No decision is preselected. Structural changes
open a dedicated editor.

```text
                       ┌──────────────────────────────────────────────────┐
                       │ Review “Payments”                           ×   │
                       ├──────────────────────────────────────────────────┤
                       │ Business responsibility proposal                 │
                       │ 6 activities · Partial evidence                  │
                       │                                                  │
                       │ Decision                                         │
                       │ ○ Accept proposal                                │
                       │ ○ Reject proposal                                │
                       │                                                  │
                       │ Reason                                           │
                       │ ┌──────────────────────────────────────────────┐ │
                       │ │ Add evidence or business context…           │ │
                       │ └──────────────────────────────────────────────┘ │
                       │                                                  │
                       │ Need to rename, merge, split or change behavior? │
                       │ Open structure editor →                          │
                       │                                                  │
                       │                            Cancel   Save decision │
                       └──────────────────────────────────────────────────┘
```

Save enables only for a valid decision and rationale. Dirty dismissal confirms.
Successful save refreshes affected projections and restores invoking focus. Human
acceptance changes review state but never upgrades evidence support.

## 13. Structure editor

Rename, membership, merge and split are consequential review operations. Edit and
impact preview remain side by side before one atomic save.

```text
┌───────────────────────────────────────────────────────────────────────────────────────────────┐
│ Cancel                  Split responsibility                          Save review decision   │
├──────────────────────────────────────────────┬────────────────────────────────────────────────┤
│ PROPOSED RESPONSIBILITIES                    │ IMPACT PREVIEW                                 │
│                                              │                                                │
│ Payment authorization                        │ BEFORE                  AFTER                  │
│ Name [Payment authorization_______________] │                                                │
│ ☑ Capture payment                            │ Payments          ───▶ Payment authorization   │
│ ☑ Check authorization                        │ ├ Capture payment       ├ Capture payment      │
│ ☐ Issue refund                               │ ├ Issue refund          └ Check authorization  │
│                                              │ └ Settle funds                                  │
│ Payment settlement                           │                         Payment settlement      │
│ Name [Payment settlement__________________] │                         ├ Issue refund         │
│ ☐ Capture payment                            │                         └ Settle funds         │
│ ☐ Check authorization                        │                                                │
│ ☑ Issue refund                               │ PRESERVED                                      │
│ ☑ Settle funds                               │ Activity IDs · Evidence · Review history       │
│                                              │                                                │
│ Reason [__________________________________] │ AFFECTED: 3 relationships · 4 references      │
│                                              │ No activity is left unassigned.                │
└──────────────────────────────────────────────┴────────────────────────────────────────────────┘
```

Changing membership updates impact live. Validation preserves edits and focuses
the first issue. Save is disabled while an activity is unassigned. Browse screens
never expose these controls.

## 14. Discovery progress

Discovery is nonblocking. The last published result remains usable.

```text
┌───────────────────────────────────────────────────────────────────────────────────────────────┐
│ Discover                                                       Analysis running  ◐          │
├───────────────────────────────────────────────────────────────────────────────────────────────┤
│                         ┌──────────────────────────────────────────────┐                      │
│                         │ Discovering business behavior               │                      │
│                         │ 38 of 52 scopes                              │                      │
│                         │ ███████████████████████████░░░░░░░░░░      │                      │
│                         │                                              │                      │
│                         │ Analyzing refund and payment behavior.       │                      │
│                         │ The published result remains available.      │                      │
│                         │                                              │                      │
│                         │ ▸ Technical details          Cancel analysis │                      │
│                         └──────────────────────────────────────────────┘                      │
│ Published views remain interactive behind this nonmodal surface.                            │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

Determinate progress appears only when the total is known. Cancel stops only the
active run after confirmation. Completion offers **View changes**; failure offers
Retry and diagnostics without replacing the published result.

## 15. History and comparison

```text
┌────────────────┬────────────────────────────────────┬──────────────────────────────────────────┐
│ ANALYSIS       │ History                       18 │ Analysis abc1234                         │
│                │                                    │ Published Sept. 10 at 10:42 a.m.         │
│   Domains      │ TODAY                              │                                          │
│   Activities   │ ● abc1234 · main                 › │ 100 domains · 284 activities             │
│   Rules        │   Published · 8 minutes ago        │ 167 rules · 12 unresolved                │
│   Context map  │                                    │                                          │
│                │   Review: Accepted Payments      › │ COMPARED WITH PREVIOUS                   │
│   Unresolved 12│   Sanjay · 24 minutes ago          │ +2 domains · +7 activities               │
│                │                                    │ −3 unresolved                             │
│ ● History      │ YESTERDAY                          │                                          │
│                │   9f8e721 · main                 › │ View changes                          →  │
│                │   Published · Yesterday            │ Export summary                           │
│                │                                    │ More actions                          ••• │
└────────────────┴────────────────────────────────────┴──────────────────────────────────────────┘
```

Click updates the inspector. Compare requires exactly two compatible published
runs. Restore is in overflow, shows impact and requires confirmation.

## Responsive delivery

Responsive behavior begins in Phase 1; it is not a desktop retrofit.

| Phase | Desktop and mobile scope |
| --- | --- |
| 1 | Catalog, Brief, strategic and behavior model, activities, rules, Evidence and quick review |
| 2 | Mobile-optimized context map, Implementation, History comparison and structure editor |

```text
┌──────────────────────────────┐  ┌──────────────────────────────┐
│ ☰  Domains              100 │  │ ‹ Domains                 •••│
├──────────────────────────────┤  ├──────────────────────────────┤
│ 🔍 Search domains…          │  │ Payments                     │
│ Filter          Sort: Name  │  │ Business responsibility      │
├──────────────────────────────┤  │ proposal                     │
│ ALL DOMAINS                  │  │                              │
│   Merchant settlement     › │  │ Brief                    ▾   │
│   Notifications           › │  ├──────────────────────────────┤
│   Orders                  › │  │ PURPOSE                      │
│ ● Payments                › │  │ Moves and reverses money    │
│   Needs review              │  │ between customers and       │
│   Pricing                 › │  │ merchants.                   │
│   Promotions              › │  │                              │
│   Reporting               › │  │ WHAT IT DOES                 │
│   …                       ▐  │  │ • Captures payments         │
│                              │  │ • Issues refunds             │
├──────────────────────────────┤  ├──────────────────────────────┤
│ 100 domains                  │  │ Review proposal              │
└──────────────────────────────┘  └──────────────────────────────┘
       Catalog screen                    Brief screen
```

On mobile, a row tap opens the Brief because there is no preview. Back restores
query, selection and scroll. Filters and Evidence use full-height sheets. Domain
views use a labeled section menu. Context map defaults to List. No action depends
on hover, double-click or long press.

## Visual language

- Use a dark neutral canvas with three tonal elevation levels, not bordered cards.
- Use hairline separators, restrained corner radii and an 8-pixel spacing system.
- Use one accent color for focus and selection; reserve semantic colors for status.
- Use 13–15-pixel body text and tabular numerals for counts.
- Keep toolbars to three logical groups and put lesser actions in overflow.
- Use a full-row selection fill, not a status-like selection dot.
- Keep motion between 120 and 180 milliseconds and honor reduced motion.
- Avoid gradients, oversized metric cards, floating glass panels and moving graph
  nodes. Apple-like means clarity, continuity and restraint, not imitation chrome.

## Accessibility and keyboard contract

- Slash focuses collection search; Command-K opens repository-wide search.
- Arrow keys move selection; Return opens; Escape closes the top surface.
- Search results announce their count without moving focus.
- Every graph has an equivalent ordered list or table.
- Status uses an icon and text, never color alone.
- Relationships have visible verbs and textual alternatives.
- Source excerpts remain selectable text with readable line order.
- Closing a sheet or inspector restores invoking focus.
- Controls meet contrast and target-size requirements at 200% zoom.

## Research basis

- [Eric Evans’ DDD reference](https://www.domainlanguage.com/wp-content/uploads/2016/05/DDD_Reference_2015-03.pdf)
  defines bounded contexts, ubiquitous language and context maps.
- [DDD Crew Bounded Context Canvas](https://github.com/ddd-crew/bounded-context-canvas)
  separates business purpose, language, decisions, communication, assumptions and
  open questions.
- [DDD Crew context mapping](https://github.com/ddd-crew/context-mapping)
  recommends small maps for explicit questions and explaining every pattern.
- [Domain Storytelling](https://domainstorytelling.org/quick-start-guide)
  represents who does what with which work object in concrete scenarios.
- [Context Mapper](https://contextmapper.org/) separates strategic and tactical
  DDD and generates graphical maps, PlantUML and service contracts from one model.
- [Microsoft domain analysis](https://learn.microsoft.com/en-nz/azure/architecture/microservices/model/domain-analysis)
  distinguishes informal domain description, strategic design and tactical design.
- [Apple split-view guidance](https://developer.apple.com/design/human-interface-guidelines/split-views?changes=_6)
  supports navigation, collection and detail panes with persistent selection.
- [Apple sidebar guidance](https://developer.apple.com/design/human-interface-guidelines/sidebars?changes=_8)
  recommends broad, shallow navigation.
- [Apple toolbar guidance](https://developer.apple.com/design/human-interface-guidelines/toolbars?changes=la)
  recommends controls near the content they affect.
- [Linear search](https://linear.app/docs/search) and
  [Linear filters](https://linear.app/docs/filters) support fast scoped search and
  composable URL-backed filters.
- [Network visualization scalability research](https://vcg.seas.harvard.edu/publications/20201001-scalability-of-network-visualisation-from-a-cognitive-load-perspective)
  supports aggregation and filtering for dense node-link diagrams.
- [Dribbble knowledge-graph examples](https://dribbble.com/search/knowledge-graph-ui)
  inform visual polish only, not interaction or usability decisions.

## Acceptance criteria

- A new user can locate any domain through search or one continuous catalog.
- Brief contains no unexplained DDD or implementation terminology.
- Strategic model never labels a bounded context or classification without authority.
- Tactical model never derives DDD elements from names or code shape alone.
- Every displayed claim opens versioned evidence or an explicit unresolved reason.
- Browse views expose no mutation controls outside Review.
- Context map remains usable as a list and never defaults to the full 100-node graph.
- Desktop and mobile preserve navigation state across list-to-detail transitions.
- Failed and cancelled discovery never remove the last published result.
