# Defect: Implementation units are promoted to anchors without entry-point evidence

Severity: P0
Related Feature: speed-business-domain-discovery
Finding: F-07
Status: Resolved
Related Findings: F-02, F-03, F-04, F-06
Tags: anchors, eligibility, registration, visibility, ui, routes, actions, jsx, react, sql, packages, triggers, language-agnostic

## Summary

Business-domain discovery promotes implementation units to activity anchors without first establishing how external behavior reaches them. It substitutes implementation syntax for entry-point evidence.

The failure is language-agnostic and directly reproduced by both trials:

- In PetClinic, selected functions and `render` methods become UI anchors merely because they contain JSX. Registered routes and user actions remain nested details disconnected from their implementations.
- In Grocery, every recognized procedure, function and trigger body becomes an SQL anchor. Public package declarations are discarded, a private body-only helper becomes an anchor, and triggers lose their firing registration identity.

The RFC defines entry points through roles such as route registration, user action, exported callable contract, message subscription, schedule, command registration or database trigger. A component or callable body is supporting implementation until registration, visibility or externally invocable contract evidence establishes otherwise.

This creates both sides of an inventory failure:

- internal implementation units can be promoted to independent activity candidates; and
- actual registrations/contracts can be omitted or stored only as disconnected nested evidence.

Consequently, neither PetClinic's 24 TSX anchors nor Grocery's 29 SQL anchors is a defensible entry-point count.

## Corrected scope of the claim

The implementation does **not** extract every React function that renders JSX.

The `tsx-jsx-entrypoint` rule selects these syntax forms when they contain JSX:

- `function_declaration`;
- `arrow_function`; and
- a `method_definition` named `render`.

An anchor is attached only when another extraction rule also created a `Unit` with the same source span. JSX can therefore exist in helper functions or component declarations that do not become units or anchors. PetClinic examples such as separately declared JSX helpers in `OwnersTable.tsx` demonstrate that the result is not “every JSX function.”

The verified defect is narrower and stronger: JSX presence is used as the anchor-eligibility predicate, while registration, user action and reachability are not required.

## Evidence from the PetClinic trial

The trial repository is `/private/tmp/speed-domain-petclinic`.

Its persisted `.speed/context/business-domain-facts.json` contains 24 `ui` candidate anchors. Their source roles include:

- route-target page components;
- form-owning components;
- reusable form controls;
- feedback and loading-state components;
- application/menu shells; and
- the route-configuration function itself.

Every one of the 24 anchor records is marked `resolved`, even though their root UI view records have no linked route. The route-configuration function contains routes only as nested elements. This shared success-by-default problem is covered by F-03.

### Route-registration evidence

`client/src/configureRoutes.tsx` declares 11 path-bearing routes:

```tsx
<Route path='/' component={WelcomePage} />
<Route path='/owners/list' component={FindOwnersPage} />
<Route path='/owners/new' component={NewOwnerPage} />
<Route path='/owners/:ownerId/edit' component={EditOwnerPage} />
<Route path='/owners/:ownerId/pets/:petId/edit' component={EditPetPage} />
<Route path='/owners/:ownerId/pets/new' component={NewPetPage} />
<Route path='/owners/:ownerId/pets/:petId/visits/new' component={VisitsPage} />
<Route path='/owners/:ownerId' component={OwnersPage} />
<Route path='/vets' component={VetsPage} />
<Route path='/error' component={ErrorPage} />
<Route path='*' component={NotFoundPage} />
```

All 11 target components also appear among the 24 source-function anchors. However, the persisted representation is disconnected:

- `configureRoutes.default` is one UI anchor;
- its interaction record contains the 11 route declarations as nested `UIElement` records;
- every route element is unresolved with a reason that its component implementation is not linked;
- the `configureRoutes.default` trace contains one symbol and zero edges;
- each target component has a separate source-function anchor; and
- the root view of each target component has `route_patterns: null` and unresolved routing.

For example:

```text
Route declaration
  path = /owners/:ownerId
  component = OwnersPage
             |
             | no relationship
             v
OwnersPage.render anchor
  route = unknown
```

The extractor knows both the route target name and the component symbol inventory, but it emits no normalized relationship connecting them.

### User-action evidence

PetClinic contains concrete UI actions such as:

- `Find Owner` invoking `submitSearchForm`;
- `Add Owner` or `Update Owner` invoking `OwnerEditor.onSubmit`;
- pet submission invoking `PetEditor.onSubmit`; and
- `Add Visit` invoking `VisitsPage.onSubmit`.

The adapter can store some `onX` registrations as nested `UIEvent` records and can attempt to link a handler. It does not create an anchor for the registered action. The surrounding component's `render` method remains the single candidate anchor even when a view contains multiple distinct actions.

The unit of interpretation is therefore the rendering function, not the route or event that initiates the behavior.

### Supporting-component evidence

The same JSX predicate promotes implementation details that are not independently registered routes:

| Extracted anchor | Observed source role | Persisted interaction evidence |
| --- | --- | --- |
| `configureRoutes.default` | Route registry/configuration | 11 nested routes; no route-to-component edges |
| `FieldFeedbackPanel.default` | Reusable validation-feedback renderer | No route, event or call |
| `LoadingPanel.default` | Loading-state renderer | No route, event or call |
| `Input.default` | Reusable form control | Unresolved local change event; no route |
| `DateInput.default` | Reusable date control | No linked route; its custom event is not captured as an action anchor |
| `SelectInput.default` | Reusable form control | Unresolved local change event; no route |
| `OwnerInformation.default` | Supporting owner-details renderer | No route, event or call |
| `PetDetails.default` | Supporting pet-details renderer | No route, event or call |

These components can be important implementation evidence inside a routed view or form trace. JSX presence alone does not establish that each is an independent observable activity entry point.

This table does not declare that every supporting component must be discarded. A reusable component can expose a genuine action or independently registered entry point. Its role must be established through registration and interaction evidence rather than its ability to render.

### Trace evidence

Thirteen resolved TSX traces contain exactly one symbol and no edges. This includes routed pages, supporting renderers and `configureRoutes.default`. The common trace algorithm cannot distinguish:

- a legitimate concrete leaf UI implementation;
- a route declaration disconnected from its target;
- a supporting component with no entry-point registration; or
- routing infrastructure incorrectly promoted to an activity anchor.

That false-completeness mechanism is F-04. F-07 is the earlier failure that chose the wrong starting entity for the trace.

### What this evidence proves

- The TSX anchor rule uses supported function syntax plus descendant JSX as its eligibility condition.
- It does not require route registration, a form, a registered user event, a visible action label or reachability from the application router.
- PetClinic produces 24 source-function UI candidates through that rule.
- Eleven actual route registrations are nested under one route-configuration anchor rather than represented as canonical route anchors.
- No normalized relationships connect those route declarations to their target component anchors.
- Route-target component anchors retain null route patterns.
- Captured user events are nested records rather than activity anchors.
- Supporting components with no route, event or call can be promoted to independent candidates.
- Provider interpretation is scheduled from these component-function anchors rather than reconciled route/action anchors.

### What this evidence does not prove

- It does not prove that all 24 TSX candidates are invalid.
- It does not prove that only the 11 registered routes should become UI anchors.
- It does not prove that welcome, error or not-found routes are business activities; they remain candidates requiring an explained disposition.
- It does not prove that every form or event must become a separate business activity. Anchor identity and activity grouping are different decisions.
- It does not prove that a reusable component can never expose an independent entry point.
- It does not establish a replacement canonical UI-anchor count for PetClinic.
- It does not authorize deduplication through component names or visible text alone.

## Evidence from the Grocery trial

The Grocery trial at `/private/tmp/speed-domain-grocery` directly reproduces the same source-role failure through SQL.

`JTA_Packages.sql` contains:

- 24 public package-specification routine declarations: three in `jta_error` and 21 in `jta`;
- 25 package-body routines: the 24 public implementations plus one private helper, `jta.get_hours`; and
- four registered database triggers.

The SQL adapter discards each package declaration whose header terminates at `;`:

```python
if not intro or intro.group() == ';':
    continue  # Package declarations are contracts, not executable bodies.
```

For every procedure, function or trigger body it retains, it unconditionally assigns the anchor role:

```python
units.append(Unit(
    source,
    name.split('.')[-1],
    qualified,
    match.start(),
    finish,
    'declarative_operation',
    params,
    owner,
    anchor_kind='sql',
))
```

The persisted facts consequently contain zero package-specification symbols/anchors, 25 package-body routine anchors and four trigger anchors.

### Private-helper example

The package body explicitly documents `jta.get_hours` as a private procedure. It is absent from the public `jta` package specification and is invoked internally by `jta.process_payroll`:

```text
public jta.process_payroll
          |
          v
private jta.get_hours
```

Despite that visibility evidence, both bodies become independent `sql` anchors. `get_hours` should be a supporting implementation symbol reached from the public operation's trace unless some separate registration evidence makes it externally invocable.

### Trigger-registration example

Grocery contains four triggers with materially different registrations:

| Trigger | Actual registration |
| --- | --- |
| `update_job_history_trigger` | `AFTER INSERT OR UPDATE OF job_id ON staff FOR EACH ROW` with a `WHEN` condition |
| `email_on_inv_trigger` | `AFTER UPDATE OF quantity ON inventory_by_location FOR EACH ROW` with a `WHEN` condition |
| `logon_trigger` | `AFTER LOGON ON SCHEMA` |
| `logoff_trigger` | `BEFORE LOGOFF ON SCHEMA` |

Each persisted anchor retains only an operation name and generic protocol `sql`. It has null method/path fields, `resolution: resolved`, and no reason. The event, timing, target table/schema, row/statement scope and condition are absent from anchor identity.

The triggers may legitimately be event entry points. The failure is not that they were retained; it is that the adapter selected and identified them from “has a body” rather than their actual trigger registration.

### What this evidence proves

- SQL body extraction and SQL entry-point selection are the same operation in the adapter.
- Public contract declarations are discarded before anchor construction.
- A body-only private helper is promoted to an independent candidate anchor.
- Trigger bodies are promoted without preserving the registrations that make them entry points.
- All 29 retained SQL bodies are marked as anchors, and the common schema defaults all 29 to resolved.
- The SQL trial reproduces the same implementation-versus-entry-point conflation as the TSX trial.

### What this evidence does not prove

- It does not establish that all 24 public package operations are business activities; they are externally visible source-level entry-point candidates requiring interpretation.
- It does not establish that every trigger represents a business activity; technical triggers still require an explicit disposition.
- It does not prove a final canonical SQL-anchor count.
- It does not prove that an executable body can never be independently registered through configuration or dynamic SQL.
- It does not justify hardcoding PL/SQL visibility or trigger rules in common orchestration.

## RFC requirements

The RFC requires candidate anchors to come from evidenced invocation boundaries. Its examples include:

- UI routes;
- forms; and
- user actions with visible labels;
- API operations and implementation methods;
- message consumers, scheduled jobs and CLI operations;
- exported library APIs; and
- procedural SQL and registered database behavior where supported.

It separately requires:

- route patterns, source symbols and route input bindings;
- links through hooks, callbacks, validators and API wrappers when statically resolvable;
- explicit gaps for unresolved event or route behavior;
- deduplication only through a resolved interaction path or a validated evidence-backed decision;
- generic component imports not to establish event wiring; and
- a language-, dialect- and framework-independent common model.

A function that happens to contain JSX and a callable that happens to have an executable body are implementation evidence. Neither is, by itself, an externally invocable entry point.

## Exact execution path

### 1. The TSX rule selects JSX-bearing function forms

`lib/context/rules/tsx/business.yml` defines `tsx-jsx-entrypoint` as:

```yaml
metadata:
  produces: business_anchor
  anchor_kind: ui
rule:
  any:
    - kind: function_declaration
    - kind: arrow_function
    - kind: method_definition
      has:
        field: name
        regex: '^render$'
  has:
    any:
      - kind: jsx_element
      - kind: jsx_self_closing_element
    stopBy: end
```

The predicate contains no registration, form, event, label or reachability requirement.

### 2. The rules adapter attaches `ui` to a source-function unit

`business_domain_adapters/rules.py::extract()` finds a `business_anchor` match with the same span as an extracted unit and assigns:

```python
unit.anchor_kind = metadata['anchor_kind']
```

The anchor role is therefore placed on the component function or `render` method.

### 3. The common extractor creates a function-derived anchor

`Extractor.add_unit()` derives anchor identity from the source-qualified unit:

```python
unit.anchor_id = identifier('anchor', unit.qualified, unit.anchor_kind)
```

Its operation name becomes values such as `render`, `Input.default` or `configureRoutes.default`, rather than an exact route/action identity.

### 4. Route declarations become nested UI elements

The `tsx-route-declaration` rule emits `produces: ui_route`. `rules.py::interaction()` stores each match as a nested `UIElement` under the current function-derived anchor.

It records the route path and target component label but deliberately leaves the element unresolved:

```text
Route declaration is captured; component implementation is not yet linked.
```

The route rule emits neither an anchor nor a semantic relationship. `rules.py::relations()` processes `semantic_relation` or `also_relation`; `ui_route` has neither marker. No edge reaches the target component symbol.

### 5. User events also remain nested details

The `tsx-ui-event` rule captures `onX` attributes and `interaction()` creates `UIEvent` records. Even when a handler can be selected, that event is not promoted to an anchor with its trigger, visible label and routed view context.

### 6. Discovery interprets every function-derived candidate

As described in F-06, `discover()` schedules each stored anchor independently:

```python
packet = packet_for(baseline, 'activity', [anchor])
```

No pre-synthesis step replaces a source-function candidate with canonical route/action anchors or attaches supporting component evidence to those anchors.

```text
TSX source
   |
   +--> JSX-bearing matched function ----------> UI anchor
   |                                                |
   |                                                v
   |                                      independent activity packet
   |
   +--> <Route path component> ----------------> nested UI element
   |                                                |
   |                                          no target edge
   |
   +--> onClick/onChange ----------------------> nested UI event
                                                    |
                                              not an anchor
```

### 7. The SQL adapter selects executable bodies and discards contracts

`business_domain_adapters/sql.py::extract()` scans for `PROCEDURE`, `FUNCTION` and `TRIGGER`. A declaration ending at `;` is skipped. Every retained body receives `anchor_kind='sql'` in the same constructor call that creates its implementation unit.

The adapter does not emit separate normalized facts for:

- public package visibility;
- private package-body visibility;
- specification-to-body implementation selection;
- trigger event/timing/target registration; or
- external invocation configuration.

```text
PL/SQL source
   |
   +--> package specification declaration -----> discarded
   |
   +--> public package body --------------------> SQL anchor
   |
   +--> private package body -------------------> SQL anchor
   |
   +--> trigger body ---------------------------> SQL anchor
                                                     |
                                               trigger registration
                                               identity not retained
```

### 8. The common extractor cannot repair adapter role selection

For both TSX and SQL, `Extractor.add_unit()` creates an anchor whenever `unit.anchor_kind` is non-null. It does not receive normalized registration or visibility facts with which to validate that choice. It also omits explicit resolution, allowing the schema default described in F-03 to mark the resulting anchor resolved.

## Root cause

The implementation conflates three different concepts:

1. **Registration or exposure:** how a route, event, exported contract, command, subscription or trigger becomes externally invocable.
2. **Implementation:** the component, callback, function, routine or body that supplies behavior.
3. **Activity interpretation:** whether one or more canonical entry points express the same business activity.

JSX indicates rendering implementation. A PL/SQL body indicates executable implementation. Neither establishes registration, external visibility or activity identity.

This cannot be corrected by adding React component-name allowlists, SQL keyword lists, file naming conventions or language/framework branches to common discovery. Trusted adapters/enrichers must emit normalized registration, exposure, target and visibility records through F-02's capability contract. F-06 then canonicalizes evidenced contract and implementation representations before common tracing and interpretation.

## Expected behavior

1. Preserve implementation units as symbols and evidence without automatically making each one an activity anchor.
2. Require an evidenced registration, exported contract or other external-invocation role before creating an anchor.
3. Emit a candidate anchor for each statically registered UI route using its exact path, routing scope and evidence.
4. Emit a candidate anchor for an evidenced form submission or user action using its trigger, visible label when known, owning view and handler evidence.
5. Link each route/action anchor to its exact target component or callback when resolvable.
6. Preserve SQL package specifications, visibility and callable signatures; link public declarations to their exact bodies.
7. Keep body-only private SQL routines as supporting symbols unless separate registration evidence establishes an entry point.
8. Model a database trigger from its firing registration, including event, timing, target, scope and condition, then link that registration to its body.
9. Retain ambiguous, dynamic and configuration-dependent targets with candidates and explicit reasons.
10. Attach reusable controls, validators, feedback, loading states, private helpers and child implementations to reachable traces.
11. Keep distinct entry points distinct even when one implementation unit serves several registrations.
12. Permit several canonical anchors to support one interpreted activity without collapsing their anchor identities.
13. Exclude technical/non-business candidates only with an explicit reason; extraction must not silently discard registered behavior.
14. Reconcile multiple source representations only through resolved links or reviewable evidence-backed decisions under F-06.
15. Require every anchor producer to set resolution explicitly.
16. Keep eligibility, canonicalization and tracing language-, dialect- and framework-agnostic in common code.

## User and system impact

- The 24-candidate count can be mistaken for a count of UI entry points.
- Routing infrastructure and supporting components can consume independent semantic-provider requests.
- Registered paths are disconnected from the components that implement them.
- A component containing several user actions is interpreted as one render-function entry point.
- Shared validation and input components can be interpreted outside the business context of their callers.
- Route parameters and visible action labels are absent from the anchor identity sent for interpretation.
- UI/API reconciliation lacks a reliable starting anchor and interaction path.
- Coverage reports dispositions of implementation-function candidates rather than proven route/action coverage.
- Empty component traces can be falsely marked resolved under F-04.
- Public SQL contract evidence and declared signatures disappear from the inventory.
- Private SQL helpers consume independent interpretation requests and can be mistaken for user-visible operations.
- Trigger activities lack the event and target identity needed to explain what initiates them.
- SQL coverage reports dispositions of executable bodies rather than registered or externally visible entry points.

## Reproduction

1. Run repository-digest refresh against `/private/tmp/speed-domain-petclinic`.
2. Count `ui` anchors in `.speed/context/business-domain-facts.json` and observe 24.
3. Inspect `tsx-jsx-entrypoint` and confirm that JSX inside selected function syntax is its eligibility predicate.
4. Inspect `configureRoutes.tsx` and enumerate its 11 path-bearing route registrations.
5. Locate the `configureRoutes.default` interaction record and observe 11 nested route elements.
6. Confirm that its trace contains one symbol and zero edges.
7. Inspect the 11 target component anchors and confirm that their root view route patterns are null.
8. Search facts edges for relationships from those route declarations to target component symbols and confirm that none exist.
9. Inspect `FindOwnersPage`, `OwnerEditor`, `PetEditor` and `VisitsPage` events and confirm that events are nested interaction records rather than anchors.
10. Inspect `FieldFeedbackPanel` and `LoadingPanel`; confirm that they become anchors despite having no registered route, captured user event or service call.
11. Inspect `discover()` and confirm that each function-derived anchor receives a separate activity packet.
12. Run repository-digest refresh against `/private/tmp/speed-domain-grocery`.
13. Count the 24 public package-specification declarations, 25 package-body routines and four triggers in `JTA_Packages.sql`.
14. Confirm that persisted facts contain zero package-specification records, 25 body anchors and four trigger anchors.
15. Inspect `jta.get_hours`; confirm that it is documented private, absent from the package specification and called from `jta.process_payroll`, yet has its own resolved anchor.
16. Inspect the four trigger declarations and compare their firing clauses with their persisted generic SQL operation records.
17. Inspect `sql.py::extract()` and confirm that declarations ending at `;` are discarded while every retained procedure/function/trigger body receives `anchor_kind='sql'`.
18. Inspect `Extractor.add_unit()` and confirm that both adapters' non-null `anchor_kind` values become anchors without common registration/visibility validation.

## Required correction

Do not fix this with component-name lists, directory conventions, SQL keyword lists, React/Oracle branches or rules that merely exclude the examples observed in either trial.

The correction must:

1. Define normalized, technology-independent records for entry-point registration/exposure, implementation selection, visibility, trigger/action identity and composition.
2. Extend the trusted adapter/enricher capability contract from F-02 to declare entry-point detection and registration/visibility resolution support independently of parsing support.
3. Activate language, dialect and framework adapters from descriptors and source/configuration evidence rather than hardcoded checks in core code.
4. Replace JSX or executable-body presence as the anchor-eligibility decision with evidenced registration/exposure roles.
5. Preserve component and callable bodies as implementation symbols even when they are not independent anchors.
6. Resolve UI route registrations to exact components and form/user events to callbacks, retaining paths, labels, owning views, inputs and outcomes.
7. Parse SQL package specifications and bodies through a dialect adapter; preserve public/private visibility and exact declaration-to-body links.
8. Parse trigger registrations into event, timing, target, scope and condition fields and link them to executable bodies.
9. Represent dynamic, conditional, generated, externally configured and ambiguous registrations explicitly.
10. Run F-06 canonicalization over resolved contract/registration/implementation representations before the model-ready graph is serialized or semantic scopes are scheduled.
11. Build traces from canonical entry-point anchors through implementation, helper, data and outcome evidence.
12. Keep technical registrations and unresolved candidates visible for explicit interpretation or exclusion rather than silently dropping them.
13. Require explicit resolution and capability diagnostics from every producing adapter.
14. Ensure common inventory, canonicalization, tracing, synthesis and verification never branch on language, SQL dialect, UI framework or router names.

## Acceptance tests

The defect is fixed only when all of the following pass:

1. **No JSX-only eligibility:** An unregistered helper that renders JSX remains implementation/view evidence and does not become an activity anchor solely because JSX is present.
2. **PetClinic routes:** All 11 path-bearing route declarations produce route-anchor records with exact path evidence.
3. **Route implementation links:** Each statically resolvable PetClinic route links to its exact target component symbol.
4. **Route registry role:** `configureRoutes.default` is represented as routing/registration evidence and is not automatically interpreted as a separate user activity.
5. **Route target context:** `OwnersPage`, `VisitsPage` and other routed views receive route context through resolved registration relationships rather than independent null-route anchors.
6. **Form action:** `Add Visit` is represented as an action anchor linked through `VisitsPage.onSubmit` with its visible label and owning route context.
7. **Multiple actions:** Distinct user actions implemented within one component retain distinct anchor identities and can later be interpreted as one activity only through evidence-backed grouping.
8. **Reusable controls:** `Input`, `DateInput` and `SelectInput` remain reachable control/validation evidence without becoming standalone activities unless independently registered action evidence exists.
9. **Feedback/loading components:** `FieldFeedbackPanel` and `LoadingPanel` do not become independent activity anchors solely from rendering.
10. **View composition:** Supporting views such as `OwnerInformation`, `PetsTable` and `PetDetails` link to their parent interaction paths when statically resolvable.
11. **Dynamic route:** A lazy, computed or configuration-selected target remains ambiguous or unresolved with candidate/evidence records.
12. **Visible label gap:** An action whose visible label cannot be resolved retains an explicit identity gap rather than borrowing its handler or component name as a business label.
13. **Explicit resolution:** A frontend adapter that omits anchor or registration resolution fails common validation under F-03.
14. **Canonicalization:** Resolved route/component/action representations receive canonical identities and evidence-preserving aliases under F-06.
15. **Trace completeness:** A route declaration disconnected from its target cannot produce a resolved one-symbol trace under F-04.
16. **Provider workload:** Semantic interpretation is scheduled from eligible canonical route/action anchors, not every JSX-bearing component unit.
17. **No name-only deduplication:** Equal route target, handler or visible-label text does not merge unrelated interactions.
18. **SQL public visibility:** Grocery's 24 public package declarations are preserved and linked to their exact implementations when resolvable.
19. **SQL private helper:** `jta.get_hours` remains a supporting symbol reached from `process_payroll` and is not independently anchored without separate invocation evidence.
20. **SQL trigger identity:** All four Grocery triggers retain event, timing, target, row/schema scope and condition evidence in their registration anchors.
21. **SQL declaration/body separation:** A body is not promoted because it is executable, and a public contract is not discarded because it lacks a body in the same source.
22. **Cross-technology conformance:** Equivalent registered, internal, ambiguous and dynamically selected fixtures from React, PL/SQL and at least one additional adapter produce the same normalized roles without core changes.
23. **No core technology branches:** Common inventory, canonicalization, tracing, synthesis and verification contain no TSX, React, router, SQL, Oracle, procedure or trigger conditionals.
24. **Honest PetClinic accounting:** Every one of the 24 previous function-derived candidates is accounted for as a canonical route/action anchor, supporting implementation evidence, explicit exclusion or unresolved candidate; no replacement count is asserted until reconciliation completes.
25. **Honest Grocery accounting:** Every one of the 29 previous body-derived candidates is accounted for as a registered/exported canonical anchor, supporting implementation evidence, explicit exclusion or unresolved candidate; no replacement count is asserted until visibility and registration reconciliation completes.

## Relationship to F-06

F-07 decides whether source evidence establishes an entry point. F-06 decides how multiple evidenced representations of that entry point—such as a package specification and body, or a route and component—receive a canonical identity while retaining aliases.

Neither defect may be fixed with technology-specific branches in the common pipeline.

## Resolution

Status: completed on 2026-09-08.

- Entry-point eligibility now requires normalized registration or exposure evidence; JSX-bearing and executable bodies remain supporting implementations by default.
- UI route/action registrations retain exact identity, route/label context, evidence, resolution, bounded dynamic candidates and links to their implementations and composed views.
- PL/SQL package contracts select exact public bodies, private helpers remain traceable supporting symbols, and trigger registrations retain their complete firing identity separately from their bodies.
- The shared schema, adapter contract and canonical graph use technology-neutral registration and composition records; common validation rejects missing registration resolution.

Verification: all 25 F-07 acceptance tests, all 300 business-domain tests and all 95 tree-sitter/unit-layer regression tests pass. The contract checker passes 23 valid specimens and rejects all 14 invalid variants. Python compilation and Git diff checks pass. PetClinic's 24 former JSX candidates and Grocery's 29 former body candidates are fully dispositioned by the acceptance suite.
