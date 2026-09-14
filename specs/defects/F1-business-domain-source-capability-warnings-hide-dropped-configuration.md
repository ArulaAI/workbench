# F1: Source capability warnings hide dropped business configuration

Severity: P0

Feature: `speed-business-domain-discovery`

Classification: Deterministic pipeline defect

Status: Implementation-ready

## Summary

Business-domain extraction recognizes 26 Petclinic files but cannot assign
them a business-discovery owner. It emits 26
`SOURCE_CAPABILITY_UNAVAILABLE` warnings, drops Spring configuration and leaves
`coverage.unsupported_source_ids` empty.

For example, the repository declares
`petclinic.security.enable=false`, while two production Java classes enable
opposite security behavior for values `true` and `false`. Extraction retains
the Java text but drops the declaration and its links to those consumers. This
hides a security-relevant repository default behind misleading parser warnings.

F1 must replace suffix-only admission with one deterministic source-selection
contract. It must parse Java Properties, route supporting inputs to existing
deterministic owners, retain bounded reference evidence, explicitly ignore
out-of-scope inputs and make warnings agree with coverage.

No LLM or synthesis component participates in this fix or its acceptance
tests. Repository declarations remain source facts, not effective deployed
values.

## Minimal end-to-end example

This is an executed pre-fix reproduction followed by a contract-valid expected
result. The expected result is not executed post-fix evidence.

Input at commit `77db261c615f30431014f431d5525ddf4ba770df`:

All fenced blocks use unified-diff annotation: `+` (green) is a required
addition, `-` (red) is a required deletion and a leading space is verified
context rather than a proposed change. Remove the marker before applying or
running a block.

```diff
 # Existing fixture input; no file change
 # src/main/resources/application.properties
 petclinic.security.enable=false
```

```diff
 // Existing fixture input; no file change
 @ConditionalOnProperty(name = "petclinic.security.enable", havingValue = "true")
 class BasicAuthenticationConfig { /* authentication required */ }
 @ConditionalOnProperty(name = "petclinic.security.enable", havingValue = "false")
 class DisableSecurityConfig { /* requests permitted */ }
```

| Result | Current | Required |
| --- | ---: | ---: |
| Application-properties language | `ini` | `properties` |
| Property declarations/bindings | 0 | Retained with exact evidence |
| Linked property conditions | 0 | 2 distinct unresolved predicates |
| Capability warnings | 26 | 0 |
| Unsupported repository sources | 0 | 0 |

## Verified baseline

These are verified facts, not post-fix results.

- Repository: `/Users/sanjay/Documents/code/tmp/spring-petclinic-reactjs`
- Commit: `77db261c615f30431014f431d5525ddf4ba770df`
- Retained artifact: `.speed/context/business-domain-facts.json`
- The artifact has 26 `SOURCE_CAPABILITY_UNAVAILABLE` warnings, zero
  `coverage.unsupported_source_ids` and one separate `SOURCE_ENCODING` warning
  for `messages_de.properties`.
- The repository has 10 `.properties` files: eight application/message inputs
  and two build/quality-tool inputs.
- The retained main application resource is labeled `ini`, unresolved and has
  no evidence.
- The prototype parsed 54 declarations from the eight relevant files with zero
  parse diagnostics. The prototype is evidence only, not SPEED integration.
- `messages_de.properties` contains ISO-8859-1 byte `0xfc` and fails the
  unconditional UTF-8 inventory gate.
- Main configuration declares `petclinic.security.enable=false`; test
  configuration declares `petclinic.security.enable=true`.
- Two production classes use `@ConditionalOnProperty` for the same key with
  opposite `havingValue` values. Production consumers must not link to the
  test declaration.
- `.properties` has catalog claimants `ini` and `properties`; current
  first-claimant behavior selects `ini`.
- Project-map classifies SVG as an asset, but business extraction independently
  classifies it as XML/config.
- PNG, JPG, JPEG, WebM, MPEG, MPG, ICO and SVGZ already classify as assets.

## Exact disposition of the 26 warnings

These are fixture expectations, not hard-coded production rules.

| Disposition | Count | Sources |
| --- | ---: | --- |
| `analyze` | 7 | Four main application files, one test application file and two UTF-8 message bundles in the warning set |
| `supporting` | 3 | `package.json`, `tsconfig.json`, `typings.json` |
| `reference_only` | 2 | IDE launch XML and Logback XML |
| `ignore` | 14 | Two tool properties, two developer JSON files, four LESS files, two SVG fonts, three CI files and `speed.toml` |
| unavailable | 0 | None |

`messages_de.properties` is an eighth analyzed Properties source. It is absent
from the 26 because it currently fails earlier with `SOURCE_ENCODING`.

## Goals and non-goals

F1 must:

- explicitly resolve only `.properties -> properties` among duplicate
  extensions;
- share path classification between project-map and business extraction;
- retain one immutable final primary-owner selection and one loaded owner per
  source;
- parse Java Properties without executing repository code;
- connect literal Spring property conditions to compatible declarations;
- consume supporting inputs through named deterministic owners;
- preserve redaction, original-byte accounting, cache invalidation and safe
  publication; and
- align source warnings, Resource state, capabilities and coverage.

F1 does not choose owners for `.bas`, `.cl`, `.fs`, `.inc`, `.pl`, `.sc` or
`.v`; add generic INI/JSON/XML/YAML/TOML business parsers; interpret messages as
rules; treat CI or styles as business behavior; execute repository code; or
claim a repository value is effective in deployment.

## Existing owners and constraints

- `language_registry.py` owns installed languages and adapter descriptors.
- `project_map.py` owns project-specific category overrides.
- `business_domain_adapters/__init__.py` owns trusted sibling-module loading.
- `business_domain_extract.py` owns bounded inventory, evidence, redaction,
  projection and fingerprinting.
- `repository_digest_runtime.py` owns package-manifest parsing.
- `layer1_domain_clustering.py` owns TypeScript alias/configuration parsing.
- `java_semantic.py` owns the Java AST and annotation spans.
- `spring_semantic.py` owns Spring interpretation.
- `business_domain_schema.py` owns structural and reference validation.
- `business_domains.py` writes attempt facts before synthesis but publishes a
  domain model only after every validation and supersession check passes.
- `business_domain_snapshots.py` separately adds unsupported supplied snapshot
  resources. F1 must preserve that contract.

Current extraction re-runs `descriptor()` or `adapter_for()` during inventory,
extraction, evidence, enrichment, binding projection, connections, relations,
observations, traces and capability aggregation. The implementation must
remove every repeated primary-owner selection, not only the obvious calls.

## Authoritative design

### Validate extension ownership and shared path classification

Add these top-level installed-configuration tables to
`lib/context/data/extraction.toml`:

```diff
+[extension_owners]
+properties = "properties"
+
+[properties]
+category = "config"
+extraction = "none"
+
+[path_classifiers.svg_asset]
+extensions = ["svg"]
+category = "asset"
+reason = "visual_asset"
```

`LanguageRegistry._load()` must collect every string-extension claimant before
building the extension index. For a duplicate it selects an owner only when
`extension_owners` declares one, verifies that owner is a claimant, rejects
unused/unnecessary/misspelled entries and otherwise retains ambiguity. Catalog
order must never choose a duplicate owner.

The constructor must stop its broad silent fallback. It builds and validates a
candidate registry in local variables and publishes it only after validation
succeeds. It catches only `RegistryConfigurationError` to preserve a normalized
`load_error` on the module singleton; it does not expose an empty registry as
usable. Every public lookup calls `require_valid()` and raises that stored error.
`Extractor.__init__()` calls `require_valid()` before inventory. It translates
the error to `DomainError('ADAPTER_REGISTRY_INVALID', normalized_message)` so
the existing `business_domains.discover()` boundary records a fatal status error
and preserves prior publication; no FactsArtifact, file Resource, cache or
publication is produced for that attempt. The message contains only the
normalized registry cause, never an exception string. Multiple disposition
rules matching one concrete path are not a global load error; they fail that
source as specified below.

Implement `RegistryConfigurationError`, `LanguageRegistry.load_error`,
`require_valid()`, `classify_path()` and the compatible `classify()` behavior in
`lib/context/language_registry.py`. The TOML loader remains the only installed
configuration owner.

The immutable `classify_path(path)` result contains `path`, `category`,
`language | null`, sorted `language_candidate_ids`, `status = classified |
ambiguous | unrecognized` and `reason | null`. Retain legacy `classify(ext)` for
current callers; it returns no language for unresolved duplicates.

Installed path-classifier loading validates exact fields, extension syntax,
allowed category and a nonempty reason. Duplicate extension claims fail load.
More than one classifier matching a concrete path is a deterministic registry
error; the design does not claim arbitrary regex overlap can be proven
statically.

`project_map._classify_file()` keeps project-specific configured overrides
first, then uses `classify_path()`. Remove its private SVG set. Business
inventory uses the same operation. Only SVG needs this exception.

Required classifications:

```diff
-.properties -> config, ini, classified by catalog order
+.properties -> config, properties, classified
-.pl         -> source, one arbitrary catalog claimant
+.pl         -> source, null, ambiguous(prolog, perl)
-*.svg       -> config, xml, classified
+*.svg       -> asset, xml, classified, visual_asset
 *.png       -> asset, null, unrecognized
```

### Separate routing, decoding, selection and execution

Put `PathClassification` in `lib/context/language_registry.py`. Put
frozen `SourceInventory(routes, retained_bytes, diagnostics)`,
`DecodedSourceInventory(routes, sources, diagnostics, provisional_decoders)`, `SourceRoute`,
`SourceSelection` and mutable `SourceExecution` in
`lib/context/business_domain_extract.py`; add only fields consumed by adapters
to `Source` in `lib/context/business_domain_adapters/base.py`, and widen
`Source.language` from `str` to `str | None` because an unresolved duplicate
extension such as `.pl` has no selected language.
`SourceInventory` and `DecodedSourceInventory` are aggregate stage containers.
The other four are per-path or per-source records with distinct lifetimes:

1. `PathClassification` is the result above.
2. Immutable `SourceRoute` contains classification, sorted matched disposition
   rule IDs, nullable disposition, expected owner, required capabilities and
   status `routed` or `overlap`. It is known before bytes are decoded. Multiple
   identical matches collapse; conflicting matches produce `overlap`.
3. Immutable `SourceSelection` is the only final primary-owner decision. It
   contains the route, selected descriptor or null, sorted candidate owner IDs
   and status `selected`, `ambiguous`, `unavailable` or `ignored`.
4. Mutable `SourceExecution` contains the loaded owner, output, diagnostics and
   final Resource state. Execution failure never mutates `SourceSelection`.

Inventory order is normative:

```diff
+Git path -> classify -> route
+  ignore -> retain decision only; no read and no business Resource
+  otherwise -> contained bounded byte read
+    -> pre-decode module lookup only for an explicitly routed decoder
+    -> decode
+    -> create final SourceSelection exactly once
+    -> load selected installed owner exactly once
```

The pre-decode lookup is not final selection. It may only fetch a decoder named
by installed route policy. In `business_domain_adapters/__init__.py`, load that
trusted module once and retain it as the provisional decoder. When final
selection confirms the same owner, `SourceExecution.loaded_owner` reuses that
module object; it must not invoke the loader again. Non-routed adapters load only
after final selection. Thus `java_properties` can decode Latin-1 while existing
SQL/API content detection occurs after strict UTF-8 decode.

If the explicitly routed decoder cannot load or its `decode()` call fails,
`inventory()` uses ISO-8859-1 only as a reversible one-character-per-byte
failure-evidence view, marks the Source's decoder failure and never runs its
parser. Final selection records `ADAPTER_UNAVAILABLE`, unresolved Resource
evidence and unsupported coverage with a normalized cause. This fallback is not
successful decoding and cannot emit declarations.

Replace descriptor admission in `business_domain_extract.source_paths()` and
bounded read/decode/Source construction in `inventory()`. Orchestrate route,
final selection and load in `Extractor.extract()` through the trusted selection
inputs from `business_domain_adapters/__init__.py`. That module exposes
`descriptor_for_route(source, route)` and `load_installed(module_name)`; it does
not own final selection. The registry only classifies paths and validates
installed configuration.
`LanguageRegistry.source_adapter_descriptor(owner_id)` is the public read-only
exact-ID lookup used by `inventory()` before a `Source` exists; it returns a
defensive immutable descriptor or null and calls `require_valid()` first.

The exact orchestration interfaces in `business_domain_extract.py` are
`source_paths(root) -> list[str]`,
`scan_inventory(root, config) -> SourceInventory`,
`inventory(scan: SourceInventory, config) -> DecodedSourceInventory`,
`select_source(source, route) -> SourceSelection`,
`load_selection(source, selection, provisional_decoder=None, module_cache=None)
-> SourceExecution` and
`source_fingerprint(scan: SourceInventory) -> str`. `scan_inventory()`
classifies/routes, performs contained bounded reads for retained sources and
stores their raw bytes, but never decodes or loads an adapter. `inventory()`
consumes that scan without rereading files and may load only an explicitly
routed decoder; it stores that module in the runtime-only
`provisional_decoders[source.resource_id]` map and performs no other primary
load. `Extractor.__init__()` retains one scan and its one decoded
`DecodedSourceInventory`; `Extractor.extract()` creates one selection/execution per
retained source. The supersession check creates only a fresh `SourceInventory`
and therefore never loads or executes adapters.

`load_selection()` checks `source.decoder_failure` first. When set, it returns a
failed execution using that normalized cause, never reloads the owner and never
runs the parser, whether the provisional module is absent (load failure) or
present (decode failure).

Every later primary-adapter hook uses `SourceExecution.loaded_owner`.
Evidence, bindings, connections, relations, observations, traces and
capabilities must not call `descriptor()` or `adapter_for()`. Enricher
descriptors/modules are selected once from normalized activation evidence and
stored separately.

Remove those repeated primary lookups from `Extractor.extract()`, `evidence()`,
`add_unit()`, `_connections()` (including its relation projection),
`_observations()`, `_capabilities()` and `_traces()` in
`lib/context/business_domain_extract.py`.

When no explicit disposition rule matches, preserve existing behavior:

- one installed adapter means `analyze/selected`;
- an unresolved duplicate-language classification means `analyze/ambiguous`,
  even when every candidate language would use the same fallback module;
- multiple adapters for one resolved language mean `analyze/ambiguous`;
- a recognized in-scope language with no adapter means
  `analyze/unavailable`; and
- an unrecognized asset means `ignore/unrecognized_asset`.

Zero explicit matches uses that compatibility rule, one uses the explicit
rule, and multiple matches fail selection for that concrete source. This keeps
ordinary Java, TypeScript, Python, SQL and OpenAPI sources working without rule
priority.

Add pure `source_fingerprint(scan: SourceInventory) -> str` to
`lib/context/business_domain_extract.py`. `Extractor.extract()` uses it for
`facts['fingerprint']['sources']`, and `business_domains.discover()` uses the
same helper at the existing prepublication supersession check. It hashes
canonical routing decisions for every discovered path and raw-byte hashes only
for retained paths, never the runtime byte map itself. The existing
implementation hash covers installed rules and owner versions. Add
`repository_digest_runtime.py` and `layer1_domain_clustering.py` explicitly to
the `implementation_hash()` inputs because supporting consumers execute their
shared parsers; changing either file must invalidate facts even when descriptor
versions are unchanged. Ignored content is not hashed, so changing a stylesheet
does not invalidate semantic facts;
changing properties/package/TypeScript inputs does. The prepublication
supersession check must use the same new fingerprint function.

### Install exact source dispositions

Patterns use `re.fullmatch` against full repository-relative POSIX paths.
Add the following top-level tables to `lib/context/data/extraction.toml`.
Python must not contain Petclinic-specific names.

```diff
+[source_dispositions.application_properties]
+path_any = ['(?:.*/)?src/(?:main|test)/resources/application(?:-[^/]+)?\.properties']
+language = "properties"
+disposition = "analyze"
+owner = "java_properties"
+required_capabilities = ["parsing", "declaration_extraction", "bindings"]
+
+[source_dispositions.message_properties]
+path_any = ['(?:.*/)?src/(?:main|test)/resources/(?:.*/)?messages(?:_[^/]+)?\.properties']
+language = "properties"
+disposition = "analyze"
+owner = "java_properties"
+required_capabilities = ["parsing", "declaration_extraction", "bindings"]
+
+[source_dispositions.tool_properties]
+path_any = ['(?:.*/)?\.mvn/wrapper/maven-wrapper\.properties', '(?:.*/)?sonar-project\.properties']
+language = "properties"
+disposition = "ignore"
+owner = "tool_configuration"
+
+[source_dispositions.package_manifest]
+path_any = ['(?:.*/)?package\.json']
+language = "json"
+disposition = "supporting"
+owner = "package_manifest"
+required_capabilities = ["runtime_selection"]
+
+[source_dispositions.typescript_module_resolution]
+path_any = ['(?:.*/)?(?:tsconfig|typings)\.json']
+language = "json"
+disposition = "supporting"
+owner = "typescript_module_resolution"
+required_capabilities = ["type_resolution"]
+
+[source_dispositions.developer_tool_configuration]
+path_any = ['(?:.*/)?\.vscode/.*', '(?:.*/)?tslint\.json']
+disposition = "ignore"
+owner = "developer_tool_configuration"
+
+[source_dispositions.stylesheet]
+path_any = ['.*\.less']
+language = "less"
+disposition = "ignore"
+owner = "stylesheet"
+
+[source_dispositions.visual_asset]
+category = "asset"
+disposition = "ignore"
+owner = "asset"
+
+[source_dispositions.ide_launch_configuration]
+path_any = ['.*\.launch']
+language = "xml"
+disposition = "reference_only"
+owner = "ide_launch_configuration"
+
+[source_dispositions.logging_configuration]
+path_any = ['(?:.*/)?logback\.xml']
+language = "xml"
+disposition = "reference_only"
+owner = "logging_configuration"
+
+[source_dispositions.ci_configuration]
+path_any = ['\.github/workflows/.*\.ya?ml', '\.travis\.yml']
+disposition = "ignore"
+owner = "ci_configuration"
+
+[source_dispositions.speed_configuration]
+path_any = ['speed\.toml']
+language = "toml"
+disposition = "ignore"
+owner = "speed_configuration"
```

Static validation rejects unknown fields, invalid regexes/dispositions,
unknown capabilities and missing owners. For `analyze`, `owner` must name an
installed source-adapter descriptor compatible with the rule language and its
required capabilities. For `supporting`, it must name an installed supporting
consumer. For `ignore` and `reference_only`, it is a nonexecuting stable reason
ID matching `[a-z][a-z0-9_]*`; those dispositions cannot declare required
capabilities or load a module. If multiple matching rules have identical
disposition, owner, language and capabilities, collapse them deterministically.
Any other concrete overlap raises fatal
`DomainError('ADAPTER_REGISTRY_INVALID', normalized_message)` from
`scan_inventory()` after routing all paths but before any retained-byte read or
FactsArtifact construction; the existing discovery status boundary preserves
prior publication.

Add these supporting-consumer tables to
`lib/context/data/extraction.toml`. Supporting owners use the same trusted
sibling-module boundary as adapters:

```diff
+[supporting_consumers.package_manifest]
+module = "package_manifest"
+function = "consume"
+version = "1"
+capabilities = ["runtime_selection"]
+capability_status = "partial"
+diagnostic_codes = ["PACKAGE_JSON_INVALID"]
+
+[supporting_consumers.typescript_module_resolution]
+module = "typescript_module_resolution"
+function = "consume"
+version = "1"
+capabilities = ["type_resolution"]
+capability_status = "partial"
+diagnostic_codes = ["TYPESCRIPT_MODULE_RESOLUTION_INVALID"]
```

Registry validation requires exact fields, a safe module/function identifier,
a nonempty version, known capabilities, status `supported` or `partial`, a
nonempty unique list of namespaced diagnostic codes, and a one-to-one match
between supporting disposition owners and consumer IDs.
`runtime_selection` and `type_resolution` remain the existing capability-catalog
names. The latter is the closest installed capability for TypeScript module-path
resolution; F1 does not add a competing `module_resolution` capability.
`business_domain_adapters/__init__.py` resolves each descriptor's installed
sibling module: `business_domain_adapters/package_manifest.py` for
`package_manifest`, and
`business_domain_adapters/typescript_module_resolution.py` for
`typescript_module_resolution`. It uses the existing containment check, validates the
named callable, and loads the selected module once per owner. Repository input
cannot register a consumer.

### Add the exact Java Properties adapter

The adapter ID/module/file are `java_properties`, `java_properties` and
`lib/context/business_domain_adapters/java_properties.py`. The catalog language
is `properties`, the extension is `.properties`, and the diagnostic is
`JAVA_PROPERTIES_SYNTAX_INVALID`. Do not describe it as generic Properties or
INI.

Add this complete registration to `lib/context/data/extraction.toml`:

```diff
+[source_adapters.java_properties]
+kind = "adapter"
+module = "java_properties"
+decoder = "decode"
+version = "1"
+contract_version = 1
+normalized_output_version = 1
+conformance = "declaration"
+languages = ["properties"]
+detect_any = ['(?:^|\n)SPEED_PATH:(?:.*/)?src/(?:main|test)/resources/(?:application(?:-[^/]+)?|(?:.*/)?messages(?:_[^/]+)?)\.properties\Z']
+diagnostic_codes = ["JAVA_PROPERTIES_SYNTAX_INVALID"]
+
+[source_adapters.java_properties.capabilities]
+parsing = "supported"
+declaration_extraction = "supported"
+entrypoint_detection = "unsupported"
+call_classification = "unsupported"
+callable_resolution = "unsupported"
+overload_resolution = "unsupported"
+type_resolution = "unsupported"
+relationship_resolution = "unsupported"
+framework_enrichment = "unsupported"
+bindings = "supported"
+data_access = "unsupported"
+rules = "unsupported"
+control_flow = "unsupported"
+outputs = "unsupported"
+runtime_selection = "unsupported"
```

Extend source-adapter validation in `lib/context/language_registry.py` to allow
the optional safe identifier `decoder` only for an adapter selected by an
explicit pre-decode route. `business_domain_adapters/__init__.py` validates that
the loaded module exposes that callable.

Add frozen `ConfigurationDeclaration(key, value, occurrence, profile,
environment, role, value_spans)` and
`DecodedSource(text, encoding, original_byte_length)`, plus nullable
`Unit.configuration` in
`lib/context/business_domain_adapters/base.py`. Role is
`application_configuration` or `message_catalog`.

`java_properties.py` implements `decode(raw: bytes) -> DecodedSource`,
`extract(source) -> list[Unit]`, `bindings(unit) -> list[dict]` and
`diagnostics(source) -> list[dict]` using the existing adapter diagnostic
shape. It also supplies the mandatory
adapter hooks `calls(unit)`,
`candidates(unit, receiver, name, candidates, position)`, `resources(unit)`,
`observations(unit)` and `operations(unit)` with empty results;
`symbol_key(name)` returns the name unchanged. The core invokes `decode` from
`business_domain_extract.inventory()` before constructing `Source`.

The bounded single-pass parser must preserve original character offsets and
implement:

- only LF, CR and CRLF physical terminators;
- form-feed as whitespace, not a terminator;
- comments after leading whitespace;
- the first unescaped `=`, `:`, space, tab or form-feed separator;
- odd trailing-backslash continuation and leading-space removal;
- standard escapes and escaped separators;
- exactly four hex digits per `\uXXXX`;
- valid surrogate-pair combination and diagnostics for lone/reversed
  surrogates;
- duplicate occurrences; and
- exact pre-decoding physical spans.

Decode as UTF-8 when valid, otherwise ISO-8859-1. Do not use `utf-8-sig`; BOM
behavior must not silently alter the first key. If decoded text begins with
U+FEFF, emit `JAVA_PROPERTIES_SYNTAX_INVALID` for span `[0, 1)`, skip the
affected first logical declaration and continue parsing later lines. A file
containing only a BOM therefore produces no declarations and an unresolved
Resource. This is an explicit SPEED contract for Spring application/message
sources, not a false claim that Java `Properties.load(InputStream)` itself uses
UTF-8-first decoding.

Implement `_configuration_scope(path) -> tuple[environment, profile, role]` in
`java_properties.py` and test it in
`tests/test_business_domain_java_properties.py`. `environment` is exactly
`main` or `test`, `profile` is a string or null and `role` is
`application_configuration` or `message_catalog`; an impossible routed path
shape raises `ValueError` and follows the per-source owner-execution failure
path. It derives scope from exact path
segments, including nested modules:

```diff
+.../src/main/resources/application.properties -> main, no profile
+.../src/main/resources/application-mysql.properties -> main, mysql
+.../src/test/resources/application.properties -> test, no profile
+.../messages_de.properties -> message_catalog
```

Each declaration becomes a `Unit`, then the existing projector creates one
`Symbol`, internal string `Binding` and exact `Evidence`. Its reason says
repository declaration was retained but effective precedence was not
evaluated. Valid declarations survive a malformed neighbor, but that file
Resource stays unresolved with diagnostic evidence. Empty valid input is
successful and gets `(0, 0)` source evidence.

For each key, `occurrence` is its zero-based physical declaration order within
that source. Set `Unit.name = key`, `Unit.kind = 'field'`, `Unit.start`
and `Unit.end` to the complete logical declaration span, and
`Unit.qualified = 'property:' + digest([source.path, key, occurrence])`.
`ConfigurationDeclaration.occurrence` stores the same integer. The existing
`add_unit()` symbol formula and shared `binding_id()` therefore remain stable
and cannot overwrite duplicate keys; tests assert the exact Unit, Symbol and
Binding IDs for two occurrences of the same key.

`java_properties.bindings(unit)` returns one mapping with `name = key`,
`value_type = 'string'`, `direction = 'internal'`, `expression = value`, the
complete Scope below, `resolution = 'unresolved'`, and reason `Repository
declaration retained; effective precedence was not evaluated.` Core supplies
source/target and evidence. Redaction runs before persistence.

Each Binding scope sets `environment` and `profile` from the declaration and
sets `tenant`, `actor`, `effective_from`, `effective_to`, `version` and
`entrypoint_ids` to null. `main` and `test` are source-set labels, not deployed
environment claims. Tests assert the complete Scope object.

Add `original_byte_length` to `Source` in
`business_domain_adapters/base.py`; finalization in `Extractor.extract()` sums
it into `limits.source_bytes` rather than re-encoding decoded text. Hash the
original bytes.

Extend `business_domain_extract.redacted()` and `redact_values()` as the single
redaction owner. Add one compiled case-insensitive sensitive-name expression
matching
`(?:^|[._-])(?:password|passwd|secret|credential|token|api[_-]?key|access[_-]?token)(?:$|[._-])`
and use it everywhere below. The generic assignment redactor replaces everything
after a sensitive assignment separator through the physical line ending, so
quoted or unquoted values containing spaces cannot leak.

Add `redact_named_value(name, value)`: a matching name replaces the entire value
with `[REDACTED]`; otherwise it applies `redacted(value)`. `redact_values()` recursively detects sibling `name` or `key`
and `expression` or `value` fields and calls `redact_named_value()` before recursing.
`Extractor.add_unit()`, `_observations()` and `_hydrate_operation()` use that
mapping-aware function. `Extractor.evidence()` continues to call
`redacted(excerpt)` because it has no separate key argument.

Add runtime-only `Source.redaction_spans` and
`Source.evidence_redaction_required` in
`business_domain_adapters/base.py`. The Java Properties parser records every
physical value segment in `ConfigurationDeclaration.value_spans`, including
quoted, space-containing and continued values. After extraction, core applies
its single sensitive-name predicate and copies only sensitive declarations'
spans to `Source.redaction_spans`; the adapter never imports or duplicates the
redactor. The existing observation dictionary carries optional
`named_value_spans`; for Spring these contain the parsed key plus each raw
`havingValue` expression span without deciding sensitivity. Core applies
the same predicate after Spring preparation and before projecting pending
diagnostics or evidence. Rejected Spring conditions put every raw
`havingValue` span and each independently decoded canonical key in
the existing diagnostic dictionary's optional `named_value_spans`; core
validates that metadata and
registers matching spans before creating diagnostic evidence. If no key can be
decoded, the key is `null` and core conservatively redacts every associated
value span. `Extractor.evidence()` first replaces
every intersection with those spans, then applies the generic redactor. If the
Properties decoder or owner fails before it can provide spans, the core sets
`evidence_redaction_required` and failure evidence is
the constant `[REDACTED]`, never raw source. A database password literal must be
absent from bindings, evidence, snapshots, diagnostics, logs and provider-ready
projections.

### Integrate supporting consumers without duplicate readers

Add frozen, validated `SupportingConsumerResult(consumed_source_ids,
normalized_inputs, diagnostics)` to
`lib/context/business_domain_adapters/base.py`. Its `diagnostics` tuple uses the
existing adapter diagnostic dictionary with required `code`, `reason` and
`span`, plus `source_id` for grouped consumers and optional
`named_value_spans`. Java Properties omits `source_id` because the existing
per-source loop already owns that association. Replace the duplicated primary
diagnostic validation with one `_project_adapter_diagnostic()` core helper used
by primary, supporting and Spring paths.
For the new Spring-property case only,
`spring_semantic.prepare(sources, units, diagnostics=None) -> list[dict]`; its
returned dictionaries use that same adapter diagnostic shape, while it
continues to append its existing endpoint
diagnostics to the supplied list. Other existing `prepare()` hooks may return
`None`. `Extractor.extract()` captures and projects only a returned diagnostic
list through `_project_adapter_diagnostic(owner, diagnostic)`. Core validates that the
source exists, the code is declared by that installed owner,
`0 <= start <= end <= len(source.text)`, and the message is normalized, then
creates exact Evidence and the schema-valid Diagnostic.

Implement the common
`consume(supporting_sources, primary_sources) -> SupportingConsumerResult`
contract in each new owner module:
`lib/context/business_domain_adapters/package_manifest.py` and
`lib/context/business_domain_adapters/typescript_module_resolution.py`. In
`Extractor.extract()`, group supporting sources by owner and invoke the callable
named by that owner's descriptor once with this common signature. Inputs are
the already bounded Sources; consumers never reread disk. Every selected source
ID must appear exactly once in consumed IDs or diagnostics. Missing, duplicate
or foreign IDs fail the consumer. The core already owns the selected descriptor,
so it attaches and validates owner ID/version when projecting capabilities; a
consumer must not duplicate installed provenance constants.

An absent owner is a source capability failure. Multiple candidates are an
ambiguity. A missing callable, load failure or thrown group call is an owner
execution failure. An invalid returned result or missing, duplicate or foreign
consumed ID is a consumer-contract failure. Because
a thrown group call has no trustworthy source identity, it fails every source
in that owner group. A consumer-reported malformed JSON record instead produces
that owner's format diagnostic for the source: its Resource is
unresolved, but its ID is not unsupported because the installed capability ran
and reported its input. For primary owners, per-source parse diagnostics affect
only their named source and an `extract()` exception affects only the source
being extracted. Existing primary and enricher `prepare()` hooks mutate shared
Sources and Units, so their exceptions cannot be rolled back safely. A thrown
primary or enricher `prepare()` therefore raises fatal
`DomainError('ADAPTER_UNAVAILABLE', normalized_message)` and aborts the whole
attempt before facts/cache publication; extracted declarations remain only
process-local and the prior published model remains intact. This is deliberate
instead of projecting a partly mutated graph. Supporting consumers return data
without mutating inputs; core applies no normalized supporting output until the
entire `SupportingConsumerResult` validates.

Success resolves the source Resource with bounded evidence. Capability
and pending-diagnostic projection and Resource finalization occur in
`Extractor.extract()`; supporting capability projection occurs in
`Extractor._capabilities()`. Capability projection reads the installed consumer descriptor above and emits one normal
`Capability` for each declared consumer capability using its configured status,
owner ID and version.

Add an immutable `supporting_inputs` map and nullable normalized
`decoder_failure` to `Source` in
`lib/context/business_domain_adapters/base.py`.
`SourceExecution.loaded_owner` is the single runtime owner reference and is not
serialized. Each primary `Source` has installed-data-only
`supporting_inputs: Map<owner_id, Map<document_kind, normalized_record>>`, where
`document_kind` is `package`, `tsconfig` or `typings`. Before adapter `prepare()`,
the extractor assigns a consumer's normalized records to compatible primary
sources using this scope algorithm: the supporting file's parent is its scope;
it applies to descendants; if nested files for the same owner exist, the
deepest ancestor wins; a root file applies only where no deeper same-owner file
does. Choose independently per `(owner_id, document_kind)`; only an equal-depth
tie within that pair is a consumer-contract failure. Thus same-scope
`tsconfig.json` and `typings.json` inputs are complementary, not competing.

In `lib/context/repository_digest_runtime.py`, factor
`_load_package_json(path)` into pure
`parse_package_json(text, sections, strict) -> PackageManifest`, where
`PackageManifest.engines`
contains sorted `{name, constraint}` records from the object-valued `engines`
section and `PackageManifest.dependencies` contains sorted
`{name, constraint, dependency_kind}` records from object-valued `dependencies`
and `devDependencies`. `dependency_kind` is `runtime` or `development`,
respectively; names and constraints must be strings. Add
`PackageJsonError(cause, start, end)`: JSON syntax uses
`JSONDecodeError.pos..min(pos+1,len(text))` (or `(0,0)` for empty input), while
wrong top-level/section/value shapes use the whole-document span.

Keep `_load_package_json(path, sections)` as the tolerant safe path wrapper used
by every existing digest caller: it catches I/O and `PackageJsonError`, returns
`None` on failure and otherwise returns `PackageManifest`. A nonstring selected
value is represented internally as null so runtimes can skip it and frameworks
can retain their existing `version=null` behavior. `derive_runtimes()` requests
only `engines`; `derive_frameworks()` requests only `dependencies` and
`devDependencies`, so a malformed unrelated section cannot suppress a valid
legacy fact. The supporting consumer calls the default `strict=True` parser
across all three sections, so persisted normalized constraints remain strings.
Package scripts are never executed or exposed.
`package_manifest.consume()` adds `source_id` and the parent-derived
`scope_dir`, producing `{source_id, scope_dir, engines[{name, constraint}],
dependencies[{name, constraint, dependency_kind}]}`. It converts
`PackageJsonError` to `PACKAGE_JSON_INVALID` at the supplied span. Before enricher
selection in `Extractor.extract()`, merge those dependency names into the
temporary evidence dictionary passed to `enricher_descriptors()` under its
existing `dependencies` key (descriptor predicates are named
`dependencies_any`). Do not claim `Source` already owns a dependency
set. Package scripts never enter the result.

In `lib/context/layer1_domain_clustering.py`, factor
`TypeScriptModuleResolutionError(cause, start, end)`, plus
`parse_typescript_module_resolution(text, document_kind) -> {aliases,
declared_external_modules}` and
`resolve_typescript_path_alias(import_name, scope_dir, aliases, source_paths) ->
{state, candidates}` from `_find_tsconfig_paths()` and
`_resolve_typescript_imports()`. Those existing functions must call the shared
helpers. `typescript_module_resolution.consume()` adds Source identity and
scope and passes `document_kind = tsconfig | typings`, derived from the matched
installed disposition and the routed source basename (`tsconfig.json` or
`typings.json`), rather than repository-controlled configuration;
`business_domain_adapters/ts_semantic.prepare()` consumes the normalized
configuration and calls the same resolver. F1 deliberately supports only the existing `compilerOptions.paths`
contract plus legacy `typings.json` dependency sections; it does not add
`extends`, `baseUrl`, include/exclude/files or type-root evaluation.

The parser raises `TypeScriptModuleResolutionError` for malformed JSON, a wrong
top-level/section shape, a nonstring alias target or an invalid wildcard count.
JSON syntax uses `JSONDecodeError.pos..min(pos+1,len(text))`, with `(0,0)` for
empty input; structural/value failures use the whole-document span. Existing
Layer 1 callers catch it and retain their current no-alias result.
`typescript_module_resolution.consume()` instead converts it to
`TYPESCRIPT_MODULE_RESOLUTION_INVALID` with the same span.
Before returning, that consumer validates every alias target relative to the
source-derived `scope_dir`; a target escaping the repository produces
`TYPESCRIPT_MODULE_RESOLUTION_INVALID` over `[0, len(source.text))`. This check
cannot be deferred to `ts_semantic.prepare()`, where the supporting source span
and per-source failure boundary are no longer available.

Add runtime-only `resolved_module_targets: Map<module,
{state, candidate_source_paths, external}>` to `Source` in
`business_domain_adapters/base.py`. Before calling `rules.prepare()`,
`ts_semantic.prepare()` resolves every static-import `Reference.module` through
the chosen configuration and stores the result in that map. No alias match
leaves the entry absent and preserves existing behavior; one local path records
`resolved`; multiple local paths record `ambiguous`; zero local paths record
`unresolved`, unless a matching legacy declaration records `external`.
The shared resolver returns `state='unmatched'` when no alias pattern matches,
distinct from `state='unresolved'` when a pattern matched but produced no local
candidate. Both Layer 1 and `ts_semantic` consume that distinction directly and
must not repeat alias matching.

Factor the lexical/type portion of `rules.candidates()` into
`rules.lexical_candidates(unit, receiver, name, available)` in
`business_domain_adapters/rules.py`; `rules.candidates()` calls it first and
then preserves its existing imported-target fallback. This keeps lexical
ownership in one place.

`ts_semantic.candidates(unit, receiver, name, available, position)` is the
alias call-resolution sink. It first returns any `rules.lexical_candidates()`
result. Otherwise it obtains the bound identifier's module through
`rules._import_bindings(source)`, using the receiver text before its first dot
when present and otherwise the call name. With no module-index entry it delegates to
`rules.candidates()` unchanged. For `resolved` or `ambiguous`, it returns
directly the sorted Units from the already name-matched `available` list whose
`source.path` is in `candidate_source_paths`; it does not delegate that result
back to `rules.candidates()`. One Unit resolves, and multiple Units remain
bounded ambiguity candidates through the existing core path. For `unresolved`
or `external`, it returns no local candidate;
`_external_import_boundaries()` emits the existing evidenced external boundary
only for `external`. The existing core `_connections()` then projects exact or
ambiguous call edges through its normal `SemanticResult` path. Layer 1 consumes
the same resolver candidates in `_resolve_typescript_imports()` to create its
file edges. Thus the resolver has one parser/probe owner and explicit sinks in
both pipelines.

The normalized shape is `{source_id, scope_dir,
aliases[{pattern, wildcard, targets[{pattern, wildcard}]}],
declared_external_modules[{name}]}`. An alias or target pattern contains
zero or one `*`; `wildcard` records which form was parsed. Preserve every string
target in declaration order. `typings.json` names come
from `dependencies`, `globalDependencies` and `ambientDependencies` and prove
only a declared external module, never a local implementation.

Before `ts_semantic.prepare()`, store the deepest compatible configuration on
each JS/TS primary Source. An exact alias matches only an identical import. A
wildcard alias matches its literal prefix and suffix and captures only the text
between them; this prevents `foo` from matching `foobar`. `ts_semantic` chooses
all matches tied for the longest combined literal prefix and suffix, evaluates
their targets and unions the resulting candidate paths; one candidate resolves,
multiple candidates are ambiguous and zero candidates are unresolved. Evaluate
tied aliases by sorted pattern and targets in their declaration order, then
deduplicate and sort candidates; declaration order is not a match tie breaker.
An exact alias with a wildcard target is invalid because it
has no capture and raises `TypeScriptModuleResolutionError`. For a wildcard alias,
substitute the capture only into target patterns that contain `*`; a target
without `*` remains fixed. Resolve every resulting target relative to
`scope_dir`, normalize it without allowing `..` to escape the repository, and
then check the selected primary-source inventory in target order using exact path,
`.ts`, `.tsx`, `.js`, `.jsx` and corresponding `/index.*` probes. One candidate
resolves, several are ambiguous and zero retains the existing unresolved path.
A matching legacy dependency may classify a zero-local-candidate import as an
evidenced external boundary. It cannot resolve a local symbol. Malformed JSON,
nonobject sections or nonstring alias targets produce a per-source supporting
diagnostic rather than silent omission. Both Layer 1 and business extraction
use these same parser/probe helpers; do not create another resolver.

`scope_dir` is the supporting file's repository-relative parent, with the root
represented as `.`. Compatibility is a segment-aware ancestor test, not a
string prefix. Configuration choice is independently deepest per owner and
document kind; equal-depth same-kind candidates are a consumer-contract
failure. Normalized inputs are
immutable JSON-compatible records sorted by source ID, then normalized
key/value; only returned adapter diagnostics require exact spans.
`Source.supporting_inputs` is initialized to an empty immutable map for every
primary source. The package-manifest consumer contributes only normalized dependency
names to the temporary activation evidence described above. The TypeScript
consumer combines the chosen `tsconfig` aliases and chosen `typings` external
declarations into one immutable `typescript_module_resolution` view;
`ts_semantic.prepare()` reads that view and the already selected primary-source inventory. No consumer may
mutate source text, selection or another consumer's field.

### Retain bounded reference evidence

Implement reference-only and ignore routing in
`business_domain_extract.inventory()` and Resource/evidence finalization in
`Extractor.extract()` and `Extractor.evidence()`. These dispositions bypass
primary adapter loading; XML adapters and `project_map.py` do not project them.

A reference-only source creates one repository-file Resource with evidence for
`[0, min(character_length, 4096))`, or `(0, 0)` when empty; unresolved state;
and reason `Reference-only <owner>: retained for context; no business semantics
were inferred.` It emits no capability or warning. Inventory read, containment,
encoding and size failures retain their existing diagnostics.

Ignored sources create no business Resource, warning or capability. Their
installed decisions remain fingerprint inputs.

### Link Spring property consumers exactly

In `lib/context/business_domain_adapters/java_semantic.py`, extend the existing
`_annotations(source, node)` helper with `_annotation_arguments(source, node)`
so its records expose argument expressions and spans. Array initializers yield
one record per element. Do not reparse Java in the Spring enricher.

Add framework-neutral `JavaLiteralError(cause, start, end)` and
`_decode_java_string_literal(token) -> str` in `java_semantic.py`. The decoder preserves
non-ASCII and operates on the exact quoted AST token. First apply Java Unicode
translation: an eligible backslash followed by one or more lowercase `u`
characters and exactly four hex digits becomes one UTF-16 code unit. Eligibility
uses the Java contiguous-backslash parity rule. Then require one ordinary
double-quoted string token and decode `\b`, `\t`, `\n`, `\f`, `\r`, `\s`, `\"`,
`\'`, `\\` and Java octal escapes; an octal escape beginning `0`-`3` consumes at
most three octal digits and one beginning `4`-`7` consumes at most two. Combine
valid high/low surrogate pairs and reject lone or reversed surrogates. Reject
text blocks, raw line terminators, invalid/truncated escapes, constants,
concatenations, calls and every other dynamic expression by raising
`JavaLiteralError`; it never creates a framework diagnostic. Never use Python
`unicode_escape`.

Activate `spring_semantic` only when normalized evidence has a parsed
`ConditionalOnProperty` annotation plus the exact import, its wildcard package
import or a fully qualified annotation. `java_semantic.activation_evidence()`
produces that evidence, `business_domain_adapters/__init__.py` performs trusted
enricher selection/loading, and `spring_semantic.prepare()` performs the
normalization and linking. It catches `JavaLiteralError` and translates the
annotation-expression span into
`SPRING_PROPERTY_CONDITION_UNAVAILABLE` adapter diagnostic.

In `java_semantic._annotations()`, retain both simple `name` and untruncated
`qualified_name`; `activation_evidence()` includes both values in `annotations`
and keeps exact imports plus wildcard package prefixes in `imports`.

Extend `language_registry.py` so an enricher descriptor declares exactly one of
the existing ANDed `evidence` table or `evidence_any`, an array of ANDed clauses;
the array matches when any complete clause matches. Migrate only the Spring
descriptor in `lib/context/data/extraction.toml` and add its diagnostic code:

```diff
-diagnostic_codes = ["SPRING_ENDPOINT_AMBIGUOUS", "SPRING_CONTRACT_DECLARATION_UNAVAILABLE"]
+diagnostic_codes = ["SPRING_ENDPOINT_AMBIGUOUS", "SPRING_CONTRACT_DECLARATION_UNAVAILABLE", "SPRING_PROPERTY_CONDITION_UNAVAILABLE"]
-[source_adapters.spring_semantic.evidence]
-imports_any = ['^org\.springframework\.web\.bind\.annotation(?:\.|$)']
-annotations_any = ['^(?:RestController|Controller|RequestMapping|GetMapping|PostMapping|PutMapping|PatchMapping|DeleteMapping)$']
+[[source_adapters.spring_semantic.evidence_any]]
+imports_any = ['^org\.springframework\.web\.bind\.annotation(?:\.|$)']
+annotations_any = ['^(?:RestController|Controller|RequestMapping|GetMapping|PostMapping|PutMapping|PatchMapping|DeleteMapping)$']
+
+[[source_adapters.spring_semantic.evidence_any]]
+imports_any = ['^org\.springframework\.boot\.autoconfigure\.condition(?:\.ConditionalOnProperty)?$']
+annotations_any = ['^ConditionalOnProperty$']
+
+[[source_adapters.spring_semantic.evidence_any]]
+annotations_any = ['^org\.springframework\.boot\.autoconfigure\.condition\.ConditionalOnProperty$']
```

The first clause preserves existing Spring MVC activation. The second accepts a
simple annotation with either the exact class import or stored wildcard package
prefix. The third accepts only the fully qualified annotation and needs no
import. The common core diagnostic validation uses the added installed code.

The Spring normalizer must:

- accept literal `prefix`, one of `name`/`value`, `havingValue` and literal
  boolean `matchIfMissing`;
- reject simultaneous/missing names, repeated scalar values and dynamic
  expressions with an evidenced
  `SPRING_PROPERTY_CONDITION_UNAVAILABLE`;
- preserve prefix and append one dot only when needed;
- represent omitted `havingValue` as “present and not false,” never equality
  with an empty string; and
- create one observation per key using a stable key/ordinal ID so array names
  cannot overwrite each other.

The exact deterministic `native_expression` spelling is
`property[<canonical JSON string key>] == <canonical JSON string havingValue>`;
when `havingValue` is omitted it is
`property[<canonical JSON string key>] is present and not false`. Append
` or missing` only when `matchIfMissing=true`. Use compact `json.dumps()` with
`ensure_ascii=False`; one helper in `spring_semantic.py` owns this serialization.

`spring_semantic.prepare()` stores a normalized configuration-observation
dictionary on the Java Unit and
retains the matched Properties declaration Units in `declaration_units`; it does
not construct binding IDs before projection. Production Java paths with exact
`src/main/java` segments use unprofiled main declarations; paths with exact
`src/test/java` segments retain unprofiled main and test candidates; other Java
paths do not link in F1. The observation scope uses the corresponding `main` or
`test` source-set label with every other Scope field null.

Add the single
`binding_id(unit, name, direction)` helper to
`lib/context/business_domain_extract.py`. `Extractor.add_unit()` uses it when
creating bindings. Later, `Extractor._observations()` replaces
each `declaration_unit` with `binding_id(declaration_unit, binding_name,
binding_direction)`, validates every binding and its declaration evidence, and
uses `identifier('observation', consumer_unit.symbol_id, key, ordinal)` for the
observation ID. It projects `rule_id=null`,
`source_location_kind='configuration'`, the normalized condition as
`native_expression`, those IDs as `input_binding_ids`, empty activity/output/
dependency lists and the stored scope/resolution/reason. No adapter duplicates
either identity formula.

Link only `application_configuration` declarations. Message keys are never
application-property candidates. Production consumers see only main
declarations. Test consumers may see main and test declarations as unresolved
precedence candidates. F1 does not parse Spring `@Profile`, and the current Java
consumer model has no normalized profile evidence. Therefore the Spring linker
accepts only declarations whose `profile` is null; profiled declarations remain
ordinary bindings but never link to `ConditionalOnProperty` in F1. Profile-aware
consumer evidence is a future feature, not an inferred match.

Store `configuration_observations` as the adapter-owned dynamic Unit attribute
convention already used by SQL; do not expand the shared `Unit` contract.
Replace the current
`java_semantic.observations = rules.observations` alias with
`java_semantic.observations(unit)`, which returns the rule observations plus
that optional list. `Extractor._observations()` validates every linked
binding ID and adds its declaration evidence. A missing binding is an
adapter-contract failure.
Both Petclinic production annotations must link only to the main false binding,
remain distinct and make no deployed-state claim.

### Align diagnostics, coverage and Resource state

Except for the fatal primary/enricher `prepare()` contract fault defined above, one
repository source gets at most one blocking owner diagnostic, even with several
required capabilities or cascading failures. The blocking codes are
`SOURCE_CAPABILITY_UNAVAILABLE`, `AMBIGUOUS_ADAPTER` and
`ADAPTER_UNAVAILABLE`. Choose one by this precedence: ambiguous owner, absent
owner, then owner load/execution failure. Registry load and concrete-rule
overlap faults are fatal attempt status errors, not source diagnostics. Format
diagnostics are nonblocking and may coexist.

Allowed source-warning causes are `owner_not_installed`, `ambiguous_language`,
`multiple_owners`, `owner_load_failed`, `owner_execution_failed` and
`consumer_contract_invalid`. Never persist raw exception messages, absolute or
temporary paths, or source content. Required capability to lost-fact mapping is
authoritative: `parsing -> evidence`, `declaration_extraction -> symbols`,
`bindings -> bindings`, `runtime_selection -> framework_activation`, and
`type_resolution -> module_relationships,type_relationships`. The warning uses
the sorted union for all failed required capabilities.

Since `Diagnostic` rejects extra fields, use this exact deterministic message
for every blocking source diagnostic. Implement
`_blocking_source_diagnostic(execution)` in
`lib/context/business_domain_extract.py`; fatal `prepare()` faults bypass it and
become `DomainError.record()` through `business_domains.discover()`:

```diff
+<path>: language=<language|null>; disposition=<analyze|supporting>;
+required=[<sorted capabilities>]; owner=<owner|null>;
+candidates=[<sorted IDs>]; cause=<normalized cause>;
+lost_facts=[<sorted fact classes>].
```

| Failure | Code |
| --- | --- |
| Required owner absent | `SOURCE_CAPABILITY_UNAVAILABLE` |
| Ambiguous language or multiple final owners | `AMBIGUOUS_ADAPTER` |
| Invalid installed registry or conflicting concrete overlap; fatal status only | `ADAPTER_REGISTRY_INVALID` |
| Selected owner load, per-source extract or supporting execute failure | `ADAPTER_UNAVAILABLE` |
| Invalid Properties syntax | `JAVA_PROPERTIES_SYNTAX_INVALID` |
| Invalid package manifest | `PACKAGE_JSON_INVALID` |
| Invalid TypeScript module-resolution input | `TYPESCRIPT_MODULE_RESOLUTION_INVALID` |
| Unsupported Spring property condition | `SPRING_PROPERTY_CONDITION_UNAVAILABLE` |

Resource state is limited to the selected source:

`Extractor.extract()` owns these Resource transitions and appends unsupported
IDs only through `_blocking_source_diagnostic()`:

| Outcome | State |
| --- | --- |
| Successful analyze | resolved; marker plus declaration evidence |
| Partial/invalid analyze | unresolved; valid facts retained; diagnostic evidence |
| Successful supporting | resolved; bounded evidence |
| Failed supporting | unresolved; evidence and failure reason |
| Reference-only | unresolved; evidence and scope reason |
| Unavailable/ambiguous/failed | unresolved; evidence and normalized cause |
| Ignore | no Resource |

Add `validate_source_warning_coverage(facts)` to
`lib/context/business_domain_schema.py`, call it at the end of
`Extractor.extract()` immediately before schema validation and in the acceptance
harness after each read, and enforce this cross-record rule:

```diff
+repository_file IDs in coverage.unsupported_source_ids
+  == repository_file subject IDs of warnings whose code is in
+     {SOURCE_CAPABILITY_UNAVAILABLE, AMBIGUOUS_ADAPTER,
+      ADAPTER_UNAVAILABLE}
```

Each blocking source warning has exactly one subject and evidence; each
unsupported repository-file ID has exactly one blocking warning. A fatal
registry-load or concrete-overlap status error creates no FactsArtifact or
unsupported source ID and is outside this bijection. A fatal primary/enricher `prepare()`
error likewise appears only as the attempt status error, creates no artifact and
is outside the source matrix and bijection. Snapshot-only unsupported resources
keep `SNAPSHOT_REFERENCE_ONLY` and also fall outside this repository-file
bijection.

### Preserve cache and publication semantics

In `lib/context/business_domains.py`, replace the current
`discover()` prepublication `inventory()` plus ad hoc `digest()` comparison with
`source_fingerprint(scan_inventory(root, config))`. Keep validation, evidence validation,
reconciliation, snapshot freshness and deadline gates before atomic publication.

`business-domains.json` is the published domain artifact. A failed refresh may
write attempt facts/status and additive snapshot blobs, but must not replace
the prior validated domain model or its baseline/history. Update the contract
at `specs/tech/contracts/business-domain-artifacts.md` to state this exact
boundary; do not claim attempt facts remain unchanged.

## Normative implementation patch

The production diff blocks below contain the required implementation logic;
filenames, splice contexts, names, return shapes, failure boundaries and call
order are normative. The later test matrix and verification commands are
acceptance requirements, not claimed test-file implementations.

### Add the shared records

`base.py` gains only three genuinely new cross-module value contracts:
`DecodedSource` crosses decoder/inventory, `ConfigurationDeclaration` crosses
Properties/Spring/core, and `SupportingConsumerResult` crosses consumer/core.
Diagnostics and observations remain the existing dictionaries owned and
projected by `business_domain_extract.py`; F1 must not add parallel diagnostic
or observation classes.

Apply this addition to `lib/context/business_domain_adapters/base.py`:

```diff
+from types import MappingProxyType
+from typing import Mapping
+
+@dataclass(frozen=True)
+class DecodedSource:
+    text: str
+    encoding: str
+    original_byte_length: int
+
+
+@dataclass(frozen=True)
+class ConfigurationDeclaration:
+    key: str
+    value: str
+    occurrence: int
+    profile: str | None
+    environment: str
+    role: str
+    value_spans: tuple[tuple[int, int], ...]
+
+
+@dataclass(frozen=True)
+class SupportingConsumerResult:
+    consumed_source_ids: tuple[str, ...]
+    normalized_inputs: tuple[dict, ...]
+    diagnostics: tuple[dict, ...]
```

Apply these field changes to the existing `Source` and `Unit` dataclasses in
that file:

```diff
 @dataclass
 class Source:
     path: str
-    language: str
+    language: str | None
     text: str
     source_hash: str
     resource_id: str
+    original_byte_length: int = 0
+    redaction_spans: list[tuple[int, int]] = field(default_factory=list)
+    decoder_failure: str | None = None
+    evidence_redaction_required: bool = False
+    supporting_inputs: Mapping[str, Mapping[str, dict]] = field(
+        default_factory=lambda: MappingProxyType({}))
+    resolved_module_targets: Mapping[str, dict] = field(
+        default_factory=lambda: MappingProxyType({}))
     matches: list[dict] = field(default_factory=list)
     units: list[Unit] = field(default_factory=list)
 @dataclass
 class Unit:
     source: Source
     name: str
     qualified: str
     start: int
     end: int
     kind: str
     params: list[tuple[str, str]] = field(default_factory=list)
     owner: str | None = None
     bases: list[str] = field(default_factory=list)
     anchor_kind: str | None = None
     method: str | None = None
     route: str | None = None
     symbol_id: str = ''
     anchor_id: str | None = None
     evidence_id: str = ''
     anchor_resolution: str | None = None
     anchor_reason: str | None = None
     anchor_evidence_spans: list[tuple[Source, int, int]] = field(default_factory=list)
     anchor_role: str | None = None
     anchor_identity_key: str | None = None
     anchor_eligibility: str = 'unresolved'
     anchor_visibility: str = 'unknown'
     anchor_correspondence_units: list[Unit] = field(default_factory=list)
     anchor_correspondence_state: str | None = None
     anchor_correspondence_reason: str | None = None
     anchor_correspondence_relationship_kind: str | None = None
     anchor_registration: dict | None = None
     anchor_registration_evidence_spans: list[tuple[Source, int, int]] = field(default_factory=list)
     executable_body: bool = False
     trace_role: str | None = None
     required_relationships: tuple[str, ...] | None = None
     required_capabilities: tuple[str, ...] | None = None
     valid_terminal: bool | None = None
+    configuration: ConfigurationDeclaration | None = None
```

### Make installed classification deterministic

Apply these additions to `lib/context/language_registry.py` and have `_load()`
publish the validated local collections shown here only after every helper
returns successfully:

```diff
+from types import MappingProxyType
+from typing import Mapping
+
+_IDENTIFIER = re.compile(r'[a-z][a-z0-9_]*\Z')
+_CATEGORIES = frozenset({'source', 'config', 'schema', 'asset'})
+_DISPOSITIONS = frozenset({'analyze', 'supporting', 'reference_only', 'ignore'})
+_ROUTABLE_CAPABILITIES = frozenset({
+    'parsing', 'declaration_extraction', 'bindings', 'runtime_selection',
+    'type_resolution',
+})
+
+
+class RegistryConfigurationError(ValueError):
+    pass
+
+
+@dataclass(frozen=True)
+class PathClassification:
+    path: str
+    category: str
+    language: str | None
+    language_candidate_ids: tuple[str, ...]
+    status: str
+    reason: str | None = None
+
+
+def _fail(cause: str) -> None:
+    raise RegistryConfigurationError(cause)
+
+
+def _freeze(value):
+    if isinstance(value, dict):
+        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
+    if isinstance(value, list):
+        return tuple(_freeze(item) for item in value)
+    return value
+
+
+def _compile_patterns(values, cause):
+    if not isinstance(values, list) or not values or not all(
+            isinstance(value, str) and value for value in values):
+        _fail(cause)
+    try:
+        return tuple(re.compile(value) for value in values)
+    except re.error:
+        _fail(cause)
+
+
+def _evidence_clauses(descriptor):
+    single = descriptor.get('evidence')
+    alternatives = descriptor.get('evidence_any')
+    if (single is None) == (alternatives is None):
+        _fail('enricher_evidence_conflict')
+    clauses = alternatives if alternatives is not None else [single]
+    if not isinstance(clauses, list) or not clauses or not all(
+            isinstance(clause, dict) and clause for clause in clauses):
+        _fail('enricher_evidence_invalid')
+    for clause in clauses:
+        if set(clause) - SOURCE_ADAPTER_EVIDENCE_KEYS:
+            _fail('enricher_evidence_invalid')
+        for values in clause.values():
+            _compile_patterns(values, 'enricher_evidence_invalid')
+    return tuple(_freeze(clause) for clause in clauses)
```

Replace `_load()` with a normalizing wrapper and move its current body to
`_load_candidate()`. The candidate method uses locals only; no partially
validated object state is published:

```diff
-    def _load(self, data_dir: Path) -> None:
+    def _load(self, data_dir: Path) -> Mapping:
+        try:
+            return self._load_candidate(data_dir)
+        except RegistryConfigurationError:
+            raise
+        except FileNotFoundError:
+            _fail('registry_file_missing')
+        except PermissionError:
+            _fail('registry_file_unreadable')
+        except tomllib.TOMLDecodeError:
+            _fail('registry_toml_invalid')
+        except json.JSONDecodeError:
+            _fail('trusted_parser_manifest_json_invalid')
+        except (OSError, KeyError, TypeError, ValueError, re.error):
+            _fail('registry_value_invalid')
+
+    def _load_candidate(self, data_dir: Path) -> Mapping:
         """Parse and validate installed metadata without mutating self."""
+        by_name = {}
+        extension_claimants = {}
+        adapters = {}
+        trusted_parsers = {}
         # Load Helix languages.toml
```

In `_load_candidate()`, keep the current validation indentation, remove both
early publications and propagate adapter faults to the normalizing wrapper:

```diff
-        self._trusted_parsers = trusted_parsers
```

Replace its evidence validation and publication tail exactly as follows:

```diff
-                if kind == 'enricher' and not descriptor.get('evidence'):
-                    raise ValueError('Framework enricher must declare activation evidence')
+                if kind == 'enricher':
+                    evidence_clauses = _evidence_clauses(descriptor)
+                elif ('evidence' in descriptor or 'evidence_any' in descriptor):
+                    raise ValueError('Ordinary adapters cannot declare activation evidence')
+                else:
+                    evidence_clauses = ({},)
 @@
-                evidence = descriptor.get('evidence', {})
-                if set(evidence) - SOURCE_ADAPTER_EVIDENCE_KEYS:
-                    raise ValueError('Unsupported source adapter evidence kind')
-                for values in evidence.values():
-                    if not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values):
-                        raise ValueError('Source adapter evidence predicates must be arrays')
-                for pattern in (descriptor.get('detect_any', []) + descriptor.get('exclude_any', [])
-                                + [p for values in evidence.values() for p in values]):
+                for pattern in (descriptor.get('detect_any', [])
+                                + descriptor.get('exclude_any', [])):
                     re.compile(pattern)
-                descriptor = {'kind':kind, **descriptor}
+                descriptor = {'kind': kind, **descriptor,
+                              '_evidence_clauses': evidence_clauses}
                 adapters[name] = descriptor
-            self._source_adapters = adapters
-        except (TypeError, ValueError, re.error) as exc:
-            # Adapter registration is an optional capability layer. Preserve
-            # the primary language registry and make the deployment fault visible.
-            self._source_adapters = {}
-            self.source_adapter_error = type(exc).__name__
+        except (TypeError, ValueError, re.error):
+            raise
```

The extension-index portion of `_load()` replaces first-claimant-wins with:

```diff
-            self._by_name[name] = lang
-            for ext in extensions:
-                if ext not in self._by_extension:
-                    self._by_extension[ext] = lang
+            by_name[name] = lang
+            for extension in extensions:
+                extension_claimants.setdefault(extension, []).append(lang)
+
+        configured_owners = extraction_config.get('extension_owners', {})
+        if not isinstance(configured_owners, dict):
+            _fail('extension_owners_invalid')
+        by_extension = {}
+        extension_candidates = {}
+        used_owners = set()
+        for extension, claimants in sorted(extension_claimants.items()):
+            unique = {candidate.name: candidate for candidate in claimants}
+            extension_candidates[extension] = tuple(
+                unique[name] for name in sorted(unique))
+            if len(unique) == 1:
+                by_extension[extension] = next(iter(unique.values()))
+                continue
+            configured = configured_owners.get(extension.removeprefix('.'))
+            if configured is None:
+                continue
+            if configured not in unique:
+                _fail('extension_owner_not_claimant')
+            by_extension[extension] = unique[configured]
+            used_owners.add(extension.removeprefix('.'))
+        if set(configured_owners) != used_owners:
+            _fail('extension_owner_unused')
```

After validating adapters, supporting consumers, classifiers and disposition
rules into local variables, `_load()` returns them. `__init__()` publishes that
state atomically:

```diff
-        try:
-            self._load(data_dir)
-        except Exception:
-            self._by_extension = {}
-            self._by_name = {}
-            self._source_adapters = {}
-            self._trusted_parsers = {}
-            self.source_adapter_error = "REGISTRY_LOAD_FAILED"
-
-        self._scan_installed_grammars()
+        self.load_error: RegistryConfigurationError | None = None
+        try:
+            state = self._load(data_dir)
+        except RegistryConfigurationError as error:
+            self.load_error = error
+        else:
+            self._by_name = state['by_name']
+            self._by_extension = state['by_extension']
+            self._extension_candidates = state['extension_candidates']
+            self._source_adapters = state['source_adapters']
+            self._supporting_consumers = state['supporting_consumers']
+            self._path_classifiers = state['path_classifiers']
+            self._source_dispositions = state['source_dispositions']
+            self._trusted_parsers = state['trusted_parsers']
+            self._scan_installed_grammars()
+
+    def require_valid(self) -> None:
+        if self.load_error is not None:
+            raise self.load_error
+
+    def source_adapter_descriptor(self, owner_id: str) -> Mapping | None:
+        self.require_valid()
+        descriptor = self._source_adapters.get(owner_id)
+        return _freeze({'id': owner_id, **descriptor}) if descriptor else None
+
+    def supporting_consumer_descriptor(self, owner_id: str) -> Mapping | None:
+        self.require_valid()
+        descriptor = self._supporting_consumers.get(owner_id)
+        return _freeze({'id': owner_id, **descriptor}) if descriptor else None
+
+    def source_dispositions(self) -> tuple[Mapping, ...]:
+        self.require_valid()
+        return self._source_dispositions
+
+    def classify_path(self, path: str) -> PathClassification:
+        self.require_valid()
+        extension = Path(path).suffix.lower()
+        candidates = self._extension_candidates.get(extension, ())
+        language = self._by_extension.get(extension)
+        if language is not None:
+            result = PathClassification(path, language.category, language.name,
+                tuple(candidate.name for candidate in candidates), 'classified')
+        elif candidates:
+            categories = {candidate.category for candidate in candidates}
+            result = PathClassification(path,
+                next(iter(categories)) if len(categories) == 1 else 'source',
+                None, tuple(candidate.name for candidate in candidates), 'ambiguous')
+        else:
+            result = PathClassification(path, 'asset', None, (), 'unrecognized')
+        matches = [item for item in self._path_classifiers
+            if extension in item['extensions']]
+        if len(matches) > 1:
+            _fail('path_classifier_overlap')
+        if matches:
+            match = matches[0]
+            result = PathClassification(path, match['category'], result.language,
+                result.language_candidate_ids, result.status, match['reason'])
+        return result
+
+    def classify(self, ext: str) -> tuple[str, str | None]:
+        result = self.classify_path('file' + ext)
+        return result.category, result.language
```

Every other public registry query begins with `self.require_valid()`. Apply the
same first statement to the existing methods explicitly:

```diff
     def classify_by_shebang(self, abs_path: str) -> tuple[str, str | None]:
+        self.require_valid()
 @@
     def can_parse(self, name: str) -> bool:
+        self.require_valid()
 @@
     def grammar(self, name: str) -> tuple[str, str] | None:
+        self.require_valid()
 @@
     def extraction_level(self, name: str) -> str:
+        self.require_valid()
 @@
     def rules_language(self, name: str) -> str:
+        self.require_valid()
 @@
     def ambient_globals(self, name: str) -> frozenset[str]:
+        self.require_valid()
 @@
     def source_adapters(
 @@
     ) -> list[dict]:
+        self.require_valid()
 @@
     def load_trusted_parser(self, identity: str):
+        self.require_valid()
 @@
     def fence_label_for(self, path: str) -> str:
+        self.require_valid()
```

The local validator stores frozen disposition records with compiled `path_any`
regexes under the private key `_path_patterns`; repository input never supplies
them.

Use this validator from `_load()` after languages and adapter descriptors have
been built in locals:

```diff
+def _validate_installed_policy(config, by_name, adapters):
+    raw_consumers = config.get('supporting_consumers', {})
+    raw_classifiers = config.get('path_classifiers', {})
+    raw_dispositions = config.get('source_dispositions', {})
+    if not all(isinstance(value, dict) for value in
+            (raw_consumers, raw_classifiers, raw_dispositions)):
+        _fail('installed_policy_table_invalid')
+
+    consumers = {}
+    consumer_fields = {'module', 'function', 'version', 'capabilities',
+        'capability_status', 'diagnostic_codes'}
+    for identity, raw in sorted(raw_consumers.items()):
+        if not _IDENTIFIER.fullmatch(identity) or set(raw) != consumer_fields:
+            _fail('supporting_consumer_invalid')
+        if (not _IDENTIFIER.fullmatch(raw.get('module', ''))
+                or not _IDENTIFIER.fullmatch(raw.get('function', ''))
+                or not isinstance(raw.get('version'), str) or not raw['version']
+                or raw.get('capability_status') not in {'supported', 'partial'}):
+            _fail('supporting_consumer_invalid')
+        capabilities = raw.get('capabilities')
+        diagnostics = raw.get('diagnostic_codes')
+        if (not isinstance(capabilities, list) or not capabilities
+                or len(capabilities) != len(set(capabilities))
+                or set(capabilities) - SOURCE_ADAPTER_CAPABILITIES
+                or not isinstance(diagnostics, list) or not diagnostics
+                or len(diagnostics) != len(set(diagnostics))
+                or not all(re.fullmatch(r'[A-Z][A-Z0-9_]*', code)
+                           for code in diagnostics)):
+            _fail('supporting_consumer_invalid')
+        consumers[identity] = _freeze(raw)
+
+    classifiers, claimed_extensions = [], set()
+    for identity, raw in sorted(raw_classifiers.items()):
+        if (not _IDENTIFIER.fullmatch(identity)
+                or set(raw) != {'extensions', 'category', 'reason'}
+                or raw.get('category') not in _CATEGORIES
+                or not _IDENTIFIER.fullmatch(raw.get('reason', ''))):
+            _fail('path_classifier_invalid')
+        extensions = raw.get('extensions')
+        if not isinstance(extensions, list) or not extensions or not all(
+                isinstance(value, str) and re.fullmatch(r'[a-z0-9]+', value)
+                for value in extensions):
+            _fail('path_classifier_invalid')
+        normalized = tuple('.' + value for value in extensions)
+        if claimed_extensions.intersection(normalized):
+            _fail('path_classifier_extension_duplicate')
+        claimed_extensions.update(normalized)
+        classifiers.append(_freeze({'id': identity, **raw,
+            'extensions': normalized}))
+
+    dispositions = []
+    allowed_fields = {'path_any', 'language', 'category', 'disposition',
+        'owner', 'required_capabilities'}
+    for identity, raw in sorted(raw_dispositions.items()):
+        if (not _IDENTIFIER.fullmatch(identity) or set(raw) - allowed_fields
+                or raw.get('disposition') not in _DISPOSITIONS
+                or not _IDENTIFIER.fullmatch(raw.get('owner', ''))
+                or not ({'path_any', 'language', 'category'} & set(raw))):
+            _fail('source_disposition_invalid')
+        if raw.get('language') is not None and raw['language'] not in by_name:
+            _fail('source_disposition_language_unknown')
+        if raw.get('category') is not None \
+                and raw['category'] not in _CATEGORIES:
+            _fail('source_disposition_category_invalid')
+        patterns = (_compile_patterns(raw['path_any'],
+            'source_disposition_pattern_invalid') if 'path_any' in raw else ())
+        required = raw.get('required_capabilities', [])
+        if (not isinstance(required, list)
+                or len(required) != len(set(required))
+                or set(required) - _ROUTABLE_CAPABILITIES):
+            _fail('source_disposition_capability_invalid')
+        owner = raw['owner']
+        if raw['disposition'] == 'analyze':
+            descriptor = adapters.get(owner)
+            if (descriptor is None or descriptor.get('kind') != 'adapter'
+                    or raw.get('language') not in descriptor.get('languages', [])
+                    or any(descriptor['capabilities'][capability] == 'unsupported'
+                           for capability in required)):
+                _fail('source_disposition_owner_invalid')
+        elif raw['disposition'] == 'supporting':
+            descriptor = consumers.get(owner)
+            if descriptor is None or not set(required).issubset(
+                    descriptor['capabilities']):
+                _fail('source_disposition_owner_invalid')
+        elif required:
+            _fail('nonexecuting_disposition_has_capabilities')
+        dispositions.append(_freeze({'id': identity, **raw,
+            'required_capabilities': tuple(sorted(required)),
+            '_path_patterns': patterns}))
+
+    supporting_owners = {item['owner'] for item in dispositions
+        if item['disposition'] == 'supporting'}
+    if supporting_owners != set(consumers):
+        _fail('supporting_consumer_owner_mismatch')
+    analyze_owners = {item['owner'] for item in dispositions
+        if item['disposition'] == 'analyze'}
+    for identity, descriptor in adapters.items():
+        decoder = descriptor.get('decoder')
+        if decoder is not None and (not _IDENTIFIER.fullmatch(decoder)
+                or identity not in analyze_owners):
+            _fail('source_adapter_decoder_invalid')
+    return (MappingProxyType(consumers), tuple(classifiers),
+            tuple(dispositions))
```

The adapter-validation loop calls `_evidence_clauses()` and stores its result;
`source_adapters()` changes its current single-clause check to:

```diff
-            required = descriptor.get('evidence', {})
-            if any(not any(re.search(pattern, value) for pattern in patterns
-                           for value in supplied.get(key.removesuffix('_any'), []))
-                   for key, patterns in required.items()):
+            clauses = descriptor.get('_evidence_clauses', ({},))
+            if not any(all(any(re.search(pattern, value)
+                    for pattern in patterns
+                    for value in supplied.get(key.removesuffix('_any'), []))
+                    for key, patterns in clause.items()) for clause in clauses):
                 continue
```

`_load()` returns the final locals only after `_validate_installed_policy()`:

```diff
+        supporting_consumers, path_classifiers, source_dispositions = \
+            _validate_installed_policy(extraction_config, by_name, adapters)
+        return {
+            'by_name': MappingProxyType(by_name),
+            'by_extension': MappingProxyType(by_extension),
+            'extension_candidates': MappingProxyType(extension_candidates),
+            'source_adapters': MappingProxyType({identity: _freeze(descriptor)
+                for identity, descriptor in adapters.items()}),
+            'supporting_consumers': supporting_consumers,
+            'path_classifiers': path_classifiers,
+            'source_dispositions': source_dispositions,
+            'trusted_parsers': MappingProxyType({identity: _freeze(parser)
+                for identity, parser in trusted_parsers.items()}),
+        }
```

Apply this exact project-map replacement to
`lib/context/project_map.py`:

```diff
-# Extensions that map to a parseable language (e.g. SVG → XML) but are
-# visual assets, not config or source.  Overrides the registry category.
-_ASSET_EXTENSIONS = {".svg", ".svgz", ".ico"}
-
-
 def _classify_file(
     rel_path: str,
     ext: str,
     extended_categories: dict[str, list[str]],
 ) -> tuple[str, str | None]:
+    classification = registry.classify_path(rel_path)
     for cat_name, patterns in extended_categories.items():
         for pattern in patterns:
             if fnmatch.fnmatch(rel_path, pattern):
-                _cat, language = registry.classify(ext)
-                return cat_name, language
-    category, language = registry.classify(ext)
-    if ext in _ASSET_EXTENSIONS:
-        category = "asset"
-    return category, language
+                return cat_name, classification.language
+    return classification.category, classification.language
```

### Route, decode, select and load once

Apply these loader functions to
`lib/context/business_domain_adapters/__init__.py`:

```diff
-def _load_installed(module_name: str):
+def load_installed(module_name: str):
     if not module_name or not isinstance(module_name, str):
-        return None
+        raise ValueError('Installed module name is required')
     installed = Path(__file__).parent.resolve()
     module = (installed/(module_name+'.py')).resolve()
     if not module.is_relative_to(installed) or not module.is_file():
         raise ValueError('Selected source adapter is not installed in the trusted package')
     return importlib.import_module('.' + module_name, __name__)
+
+
+def descriptor_for_route(source: Source, route) -> list[dict]:
+    if route.disposition in {'ignore', 'reference_only'}:
+        return []
+    if route.expected_owner:
+        descriptor = (registry.supporting_consumer_descriptor(route.expected_owner)
+            if route.disposition == 'supporting'
+            else registry.source_adapter_descriptor(route.expected_owner))
+        return [dict(descriptor)] if descriptor else []
+    supplied_languages = route.classification.language_candidate_ids or (
+        (route.classification.language,) if route.classification.language else ())
+    matches = {}
+    detection_text = source.text + '\nSPEED_PATH:' + source.path
+    for language in supplied_languages:
+        for descriptor in registry.source_adapters(language, detection_text,
+                kind='adapter'):
+            if descriptor.get('decoder'):
+                continue
+            matches[descriptor['id']] = descriptor
+    return [matches[key] for key in sorted(matches)]
```

Legacy `adapter_for()` and `enrichers_for()` call `load_installed()` after this
rename. New extraction code calls neither legacy function.

Apply these records and functions to
`lib/context/business_domain_extract.py`:

```diff
+import math
+import json
+from dataclasses import dataclass, field
+from types import MappingProxyType, ModuleType
+from typing import Mapping
+from pathlib import PurePosixPath
+from .language_registry import PathClassification, RegistryConfigurationError, registry
-from .business_domain_adapters import (CATALOG, adapter_for, descriptor,
-    enricher_descriptors, enrichers_for)
+from .business_domain_adapters import (CATALOG, descriptor_for_route,
+    enricher_descriptors, load_installed)
+from .business_domain_adapters.base import (DecodedSource,
+    SupportingConsumerResult)
+
+
+@dataclass(frozen=True)
+class SourceRoute:
+    classification: PathClassification
+    matched_rule_ids: tuple[str, ...]
+    disposition: str
+    expected_owner: str | None
+    required_capabilities: tuple[str, ...]
+    status: str
+
+
+@dataclass(frozen=True)
+class SourceInventory:
+    routes: tuple[SourceRoute, ...]
+    retained_bytes: Mapping[str, bytes]
+    diagnostics: tuple[dict, ...]
+
+
+@dataclass(frozen=True)
+class DecodedSourceInventory:
+    routes: tuple[SourceRoute, ...]
+    sources: tuple[Source, ...]
+    diagnostics: tuple[dict, ...]
+    provisional_decoders: Mapping[str, ModuleType]
+
+
+@dataclass(frozen=True)
+class SourceSelection:
+    route: SourceRoute
+    selected_descriptor: Mapping | None
+    candidate_owner_ids: tuple[str, ...]
+    status: str
+
+
+@dataclass
+class SourceExecution:
+    source: Source
+    selection: SourceSelection
+    loaded_owner: ModuleType | None = None
+    output: tuple[Unit, ...] = ()
+    diagnostics: list[dict] = field(default_factory=list)
+    state: str = 'unresolved'
+    cause: str | None = None
+
+
+def _route(path: str, classification: PathClassification) -> SourceRoute:
+    matches = []
+    for rule in registry.source_dispositions():
+        patterns = rule.get('_path_patterns', ())
+        if patterns and not any(pattern.fullmatch(path) for pattern in patterns):
+            continue
+        if rule.get('language') is not None \
+                and rule['language'] != classification.language:
+            continue
+        if rule.get('category') is not None \
+                and rule['category'] != classification.category:
+            continue
+        matches.append(rule)
+    if not matches:
+        if classification.category == 'asset' and classification.status == 'unrecognized':
+            return SourceRoute(classification, (), 'ignore', 'unrecognized_asset',
+                (), 'routed')
+        return SourceRoute(classification, (), 'analyze', None, (), 'routed')
+    signatures = {
+        (rule['disposition'], rule['owner'], rule.get('language'),
+         tuple(rule.get('required_capabilities', ())))
+        for rule in matches
+    }
+    matched_ids = tuple(sorted(rule['id'] for rule in matches))
+    if len(signatures) != 1:
+        return SourceRoute(classification, matched_ids, 'analyze', None, (), 'overlap')
+    disposition, owner, _language, capabilities = next(iter(signatures))
+    return SourceRoute(classification, matched_ids, disposition, owner,
+        tuple(sorted(capabilities)), 'routed')
+
+
-def inventory(root: Path, config: dict) -> tuple[list[Source], list[dict]]:
-    sources, diagnostics = [], []
-    relatives = source_paths(root)
-    markers = set(CATALOG.get('service_scope_markers', []))
-    scope_directories = {Path(relative).parent.as_posix()
-        for relative in relatives if Path(relative).name in markers}
-    for relative in relatives:
-        path = root / relative
-        if not path.resolve().is_relative_to(root) or path.is_symlink() or not path.is_file():
-            diagnostics.append(record('Diagnostic', code='UNSAFE_SOURCE', message='Excluded source outside repository containment', subject_ids=[], evidence_ids=[]))
-            continue
-        try:
-            with path.open('rb') as stream:
-                raw = stream.read(config['max_source_bytes'] + 1)
-        except OSError:
-            diagnostics.append(record('Diagnostic', code='SOURCE_UNAVAILABLE', message=f'Cannot read source: {relative}', subject_ids=[], evidence_ids=[]))
-            continue
-        if len(raw) > config['max_source_bytes']:
-            diagnostics.append(record('Diagnostic', code='SOURCE_LIMIT', message=f'Excluded oversized source: {relative}', subject_ids=[], evidence_ids=[]))
-            continue
-        try:
-            text = raw.decode('utf-8')
-        except UnicodeError:
-            diagnostics.append(record('Diagnostic', code='SOURCE_ENCODING', message=f'Unsupported source encoding: {relative}', subject_ids=[], evidence_ids=[]))
-            continue
-        source = Source(relative, descriptor(relative)['language'], text, digest(raw),
-            identifier('resource', relative))
-        parents = [parent.as_posix() for parent in Path(relative).parents]
-        service_scope = max(
-            (scope for scope in scope_directories if scope in parents),
-            key=lambda scope: len(Path(scope).parts), default=None)
-        source.service_scope = ('repository' if service_scope in (None, '.')
-            else service_scope)
-        sources.append(source)
-    return sources, diagnostics
-
+def scan_inventory(root: Path, config: dict) -> SourceInventory:
+    root = root.resolve()
+    routes = tuple(_route(path, registry.classify_path(path))
+        for path in source_paths(root))
+    overlaps = [route for route in routes if route.status == 'overlap']
+    if overlaps:
+        paths = ','.join(sorted(route.classification.path for route in overlaps))
+        raise DomainError('ADAPTER_REGISTRY_INVALID',
+            f'conflicting_source_dispositions:{paths}')
+    retained = {}
+    diagnostics = []
+    for route in routes:
+        if route.disposition == 'ignore':
+            continue
+        relative = route.classification.path
+        path = root / relative
+        if (path.is_symlink() or not path.is_file()
+                or not path.resolve().is_relative_to(root)):
+            diagnostics.append(record('Diagnostic', code='UNSAFE_SOURCE',
+                message=f'Excluded unsafe source: {relative}',
+                subject_ids=[], evidence_ids=[]))
+            continue
+        try:
+            with path.open('rb') as stream:
+                raw = stream.read(config['max_source_bytes'] + 1)
+        except OSError:
+            diagnostics.append(record('Diagnostic', code='SOURCE_UNAVAILABLE',
+                message=f'Cannot read source: {relative}',
+                subject_ids=[], evidence_ids=[]))
+            continue
+        if len(raw) > config['max_source_bytes']:
+            diagnostics.append(record('Diagnostic', code='SOURCE_LIMIT',
+                message=f'Excluded oversized source: {relative}',
+                subject_ids=[], evidence_ids=[]))
+            continue
+        retained[relative] = raw
+    return SourceInventory(routes, MappingProxyType(retained), tuple(diagnostics))
+
+
+def inventory(scan: SourceInventory, config: dict) -> DecodedSourceInventory:
+    routes = {route.classification.path: route for route in scan.routes}
+    sources = []
+    diagnostics = list(scan.diagnostics)
+    provisional = {}
+    decoder_modules = {}
+    decoder_load_failures = set()
+    markers = set(CATALOG.get('service_scope_markers', ()))
+    scope_directories = {PurePosixPath(route.classification.path).parent.as_posix()
+        for route in scan.routes
+        if PurePosixPath(route.classification.path).name in markers}
+    for relative, raw in scan.retained_bytes.items():
+        route = routes[relative]
+        decoded = None
+        failure = None
+        descriptor = (registry.source_adapter_descriptor(route.expected_owner)
+            if route.disposition == 'analyze' and route.expected_owner else None)
+        decoder_name = descriptor.get('decoder') if descriptor else None
+        if decoder_name:
+            module = None
+            module_key = (descriptor['id'], descriptor['module'])
+            if module_key in decoder_load_failures:
+                failure = 'owner_load_failed'
+            else:
+                try:
+                    module = decoder_modules.get(module_key)
+                    if module is None:
+                        module = load_installed(descriptor['module'])
+                        decoder_modules[module_key] = module
+                    decoder = getattr(module, decoder_name, None)
+                    if not callable(decoder):
+                        raise TypeError('Installed decoder is not callable')
+                    decoded = decoder(raw)
+                    if (not isinstance(decoded, DecodedSource)
+                            or not isinstance(decoded.text, str)
+                            or not isinstance(decoded.encoding, str)
+                            or decoded.original_byte_length != len(raw)):
+                        raise TypeError(
+                            'Installed decoder returned an invalid result')
+                except Exception:
+                    failure = ('owner_load_failed' if module is None
+                               else 'owner_execution_failed')
+                    if module is None:
+                        decoder_load_failures.add(module_key)
+            if failure:
+                decoded = DecodedSource(raw.decode('iso-8859-1'),
+                    'failure-evidence-iso-8859-1', len(raw))
+            if module is not None:
+                provisional[identifier('resource', relative)] = module
+        else:
+            try:
+                decoded = DecodedSource(raw.decode('utf-8'), 'utf-8', len(raw))
+            except UnicodeDecodeError:
+                diagnostics.append(record('Diagnostic', code='SOURCE_ENCODING',
+                    message=f'Unsupported source encoding: {relative}',
+                    subject_ids=[], evidence_ids=[]))
+                continue
+        source = Source(path=relative, language=route.classification.language,
+            text=decoded.text, source_hash=digest(raw),
+            resource_id=identifier('resource', relative),
+            original_byte_length=decoded.original_byte_length,
+            decoder_failure=failure,
+            evidence_redaction_required=bool(failure))
+        parents = {parent.as_posix() for parent in PurePosixPath(relative).parents}
+        service_scope = max((scope for scope in scope_directories if scope in parents),
+            key=lambda value: len(PurePosixPath(value).parts), default=None)
+        source.service_scope = ('repository' if service_scope in {None, '.'}
+            else service_scope)
+        sources.append(source)
+    return DecodedSourceInventory(scan.routes, tuple(sources), tuple(diagnostics),
+        MappingProxyType(provisional))
+
+
+def select_source(source: Source, route: SourceRoute) -> SourceSelection:
+    if route.disposition in {'ignore', 'reference_only'}:
+        return SourceSelection(route, None, (), 'ignored')
+    candidates = descriptor_for_route(source, route)
+    candidate_ids = tuple(sorted(candidate['id'] for candidate in candidates))
+    if (route.expected_owner is None
+            and route.classification.status == 'ambiguous'):
+        return SourceSelection(route, None, candidate_ids, 'ambiguous')
+    if len(candidates) == 1:
+        return SourceSelection(route, MappingProxyType(dict(candidates[0])),
+            candidate_ids, 'selected')
+    return SourceSelection(route, None, candidate_ids,
+        'ambiguous' if candidates else 'unavailable')
+
+
+def load_selection(source: Source, selection: SourceSelection,
+        provisional_decoder: ModuleType | None = None,
+        module_cache: dict[tuple[str, str, str], ModuleType] | None = None
+        ) -> SourceExecution:
+    execution = SourceExecution(source, selection)
+    if selection.route.disposition in {'ignore', 'reference_only'}:
+        return execution
+    if source.decoder_failure:
+        execution.loaded_owner = provisional_decoder
+        execution.cause = source.decoder_failure
+        return execution
+    descriptor = selection.selected_descriptor
+    if selection.status != 'selected' or descriptor is None:
+        execution.cause = (
+            'ambiguous_language'
+            if (selection.status == 'ambiguous'
+                and selection.route.classification.status == 'ambiguous')
+            else 'multiple_owners' if selection.status == 'ambiguous'
+            else 'owner_not_installed')
+        return execution
+    cache = module_cache if module_cache is not None else {}
+    try:
+        module = provisional_decoder
+        cache_key = (selection.route.disposition, descriptor['id'],
+            descriptor['module'])
+        if module is None:
+            module = cache.get(cache_key)
+        if module is None:
+            module = load_installed(descriptor['module'])
+            cache[cache_key] = module
+        execution.loaded_owner = module
+        if selection.route.disposition == 'analyze':
+            extract = getattr(module, 'extract', None)
+            if not callable(extract):
+                raise AttributeError('Installed adapter extract hook is unavailable')
+            execution.output = tuple(extract(source))
+        execution.state = 'resolved'
+    except Exception:
+        execution.cause = ('owner_load_failed' if execution.loaded_owner is None
+            else 'owner_execution_failed')
+        if descriptor.get('decoder'):
+            source.evidence_redaction_required = True
+        execution.loaded_owner = None
+        execution.output = ()
+        execution.state = 'unresolved'
+    return execution
+
+
+def source_fingerprint(scan: SourceInventory) -> str:
+    return digest({
+        'routes': [{
+            'path': route.classification.path,
+            'category': route.classification.category,
+            'language': route.classification.language,
+            'language_candidate_ids': list(route.classification.language_candidate_ids),
+            'classification_status': route.classification.status,
+            'classification_reason': route.classification.reason,
+            'matched_rule_ids': list(route.matched_rule_ids),
+            'disposition': route.disposition,
+            'owner': route.expected_owner,
+            'required_capabilities': list(route.required_capabilities),
+            'route_status': route.status,
+        } for route in scan.routes],
+        'retained_bytes': {path: digest(raw)
+            for path, raw in sorted(scan.retained_bytes.items())},
+    })
```

Remove descriptor admission from `source_paths()`:

```diff
     return sorted({p for p in paths if p and not any(part in IGNORED for part in Path(p).parts)
-                   and descriptor(p) is not None and not is_credential_path(Path(p))})
+                   and not is_credential_path(Path(p))})
```

`Extractor.__init__()` performs the only setup sequence:

```diff
         self.root=root.resolve();self.config=config
-        self.sources,self.diagnostics=inventory(self.root,config)
+        try:
+            registry.require_valid()
+        except RegistryConfigurationError as error:
+            raise DomainError('ADAPTER_REGISTRY_INVALID', str(error)) from None
+        self.scan = scan_inventory(self.root, config)
+        decoded = inventory(self.scan, config)
+        self.sources = list(decoded.sources)
+        self.routes = {route.classification.path: route for route in decoded.routes}
+        self.provisional_decoders = dict(decoded.provisional_decoders)
+        self.diagnostics = list(decoded.diagnostics)
+        self.selections_by_source_id = {}
+        self.executions_by_source_id = {}
+        self.owner_module_cache = {}
```

Every later primary hook obtains its module only through:

```diff
+    def _owner(self, source: Source):
+        execution = self.executions_by_source_id[source.resource_id]
+        return execution.loaded_owner if execution.state == 'resolved' else None
```

Replace the current primary-selection, primary-prepare and enricher-selection
loops at the start of `extract()` with this orchestration method and call it
once before `add_unit()`:

```diff
-    def extract(self) -> tuple[dict,list[Unit]]:
-        selected_adapters = {}
-        for source in self.sources:
-            self.facts['resources'][source.resource_id]=record('Resource',id=source.resource_id,kind='repository_file',name=source.path,language=source.language)
-            adapter = None
-            try:
-                entry = descriptor(source) or {}
-                selected = entry.get('capability') or {}
-                adapter_id = selected.get('id') or entry.get('adapter') or 'business-domain-static'
-                parser_id = selected.get('parser')
-                source.adapter_id = f'{adapter_id}/{parser_id}' if parser_id else adapter_id
-                source.adapter_version = selected.get('parser_version') or selected.get('version') or '1'
-                source.declared_capabilities = dict(selected.get('capabilities', {}))
-                source.parser_required = bool(parser_id)
-                adapter = adapter_for(source)
-                units = adapter.extract(source) if adapter else []
-                if adapter is None:
-                    code = ('ADAPTER_REGISTRY_INVALID' if entry.get('registry_error') else
-                            'AMBIGUOUS_ADAPTER' if len(entry.get('candidates', [])) > 1 else
-                            'SOURCE_CAPABILITY_UNAVAILABLE')
-                    self.diagnostics.append(record('Diagnostic', code=code,
-                        message='No unique installed parser capability matches this source.', subject_ids=[source.resource_id]))
-                    for diagnostic_code in (entry.get('capability') or {}).get('diagnostic_codes', []):
-                        if diagnostic_code != code:
-                            self.diagnostics.append(record('Diagnostic', code=diagnostic_code,
-                                message='Selected source capability is unavailable for this input.',
-                                subject_ids=[source.resource_id]))
-            except (ImportError,ValueError,TypeError,RuntimeError,subprocess.SubprocessError) as exc:
-                source.adapter_failed = True
-                adapter = None
-                self.diagnostics.append(record('Diagnostic',code='ADAPTER_UNAVAILABLE',message=f'{source.language}: {type(exc).__name__}',subject_ids=[source.resource_id],evidence_ids=[]));units=[]
-            self.units.extend(units)
-            if adapter:
-                selected_adapters.setdefault(id(adapter), (adapter, []))[1].append(source)
-        # Resolve cross-file semantics through installed provider hooks. Core
-        # orchestration does not inspect language or framework identities.
-        for adapter, sources in sorted(selected_adapters.values(),
-                key=lambda item: (getattr(item[0], 'PREPARE_PHASE', 100),
-                                  getattr(item[0], '__name__', type(item[0]).__name__))):
-            prepare = getattr(adapter, 'prepare', None)
-            if prepare:
-                prepare(sources, self.units, self.diagnostics)
-            diagnostics = getattr(adapter, 'diagnostics', None)
-            if diagnostics:
-                for source in sources:
-                    for diagnostic in diagnostics(source):
-                        if not isinstance(diagnostic, dict):
-                            raise ValueError('Adapter diagnostic must be a normalized record')
-                        span = diagnostic.get('span')
-                        reason = diagnostic.get('reason')
-                        code = diagnostic.get('code')
-                        if (not isinstance(span, (tuple, list)) or len(span) != 2
-                                or any(type(value) is not int for value in span)
-                                or not 0 <= span[0] <= span[1] <= len(source.text)
-                                or not isinstance(code, str) or not code
-                                or not isinstance(reason, str) or not reason):
-                            raise ValueError('Adapter diagnostic requires code, reason, and a valid source span')
-                        evidence_id = self.evidence(source, span[0], span[1])
-                        self.diagnostics.append(record('Diagnostic', code=code, message=reason,
-                            subject_ids=[source.resource_id], evidence_ids=[evidence_id]))
-        selected_enrichers = {}
-        for source in self.sources:
-            if source.adapter_failed:
-                continue
-            adapter = adapter_for(source)
-            evidence = getattr(adapter, 'activation_evidence', lambda _: {})(source) if adapter else {}
-            for enricher in enrichers_for(source, evidence):
-                selected_enrichers.setdefault(id(enricher), (enricher, []))[1].append(source)
-        for enricher, sources in selected_enrichers.values():
-            prepare = getattr(enricher, 'prepare', None)
-            if prepare:
-                prepare(sources, self.units, self.diagnostics)
-        for unit in self.units:
-            self.add_unit(unit)
-        self._connections()
-        self._anchor_correspondences()
-        self._observations()
-        self._canonicalize_anchors()
-        self._documentation_edges()
-        self._capabilities()
-        self._traces()
-        from .business_domain_snapshots import capture_supplied
-        self.external_freshness,self.snapshot_inputs = capture_supplied(self)
-        self.facts['coverage']['anchors_total']=len(self.facts['anchors'])
-        self.facts['coverage']['anchors_pending']=len(self.facts['anchors'])
-        self.facts['coverage']['evidence_valid']=len(self.facts['evidence'])
-        self.facts['limits']['source_bytes']=sum(len(s.text.encode()) for s in self.sources)
-        self.facts['limits']['semantic_units_total']=len(self.facts['traces'])
-        self.facts['limits']['semantic_units_pending']=len(self.facts['traces'])
-        installed = Path(__file__).parent
-        fp = dict(sources=digest({s.path:s.source_hash for s in self.sources}),
-            configuration=digest(self.config),
-            extractors=implementation_hash(Path(__file__),installed/'business_domain_adapters',
-                installed/'rules',installed/'data',installed/'language_registry.py',
-                installed/'treesitter_extract.py',installed/'business_domain_schema.py',
-                installed/'business_domain_snapshots.py',
-                installed/'business_domain_identity.py',installed/'business_domain_policies.json',
-                installed/'business_domain_reference_targets.json',
-                installed/'business_domain_artifacts.schema.json'),
-            prompts=digest({}),provider=digest({}),overrides=digest({}),
-            snapshots=digest({'records':self.facts['source_snapshots'],'inputs':self.snapshot_inputs}))
-        fp['value']=digest(fp);self.facts['fingerprint']=fp
-        for blob,snapshot in self.snapshot_objects.items():atomic_write(self.root/'.speed/context/business-domain-snapshots'/f'{blob}.json',snapshot)
-        account_artifact_bytes(self.facts)
-        validate(self.facts,'FactsArtifact')
-        return self.facts,self.units
-
+    def _execute_installed_owners(self):
+        primary_groups = {}
+        for source in self.sources:
+            route = self.routes[source.path]
+            self.facts['resources'][source.resource_id] = record('Resource',
+                id=source.resource_id, kind='repository_file', name=source.path,
+                language=source.language)
+            selection = select_source(source, route)
+            execution = load_selection(source, selection,
+                self.provisional_decoders.get(source.resource_id),
+                self.owner_module_cache)
+            self.selections_by_source_id[source.resource_id] = selection
+            self.executions_by_source_id[source.resource_id] = execution
+            descriptor = selection.selected_descriptor or {}
+            if descriptor:
+                parser_id = descriptor.get('parser')
+                source.adapter_id = (f"{descriptor['id']}/{parser_id}"
+                    if parser_id else descriptor['id'])
+                source.adapter_version = (descriptor.get('parser_version')
+                    or descriptor.get('version', '1'))
+                source.declared_capabilities = dict(
+                    descriptor.get('capabilities', {}))
+                source.parser_required = bool(parser_id)
+            self.units.extend(execution.output)
+            if execution.output:
+                _register_redaction_spans(execution.output)
+            if (route.disposition == 'analyze'
+                    and execution.state == 'resolved'
+                    and execution.loaded_owner is not None):
+                primary_groups.setdefault(descriptor['id'],
+                    (descriptor, execution.loaded_owner, []))[2].append(source)
+
+        self._run_supporting_consumers()
+
+        for _owner_id, (descriptor, module, sources) in sorted(
+                primary_groups.items(), key=lambda item: (
+                    getattr(item[1][1], 'PREPARE_PHASE', 100), item[0])):
+            prepare = getattr(module, 'prepare', None)
+            if prepare:
+                try:
+                    pending = prepare(sources, self.units, self.diagnostics)
+                except Exception:
+                    raise DomainError('ADAPTER_UNAVAILABLE',
+                        'primary_prepare_failed') from None
+                if pending is not None:
+                    if not isinstance(pending, list) or not all(
+                            isinstance(item, dict) for item in pending):
+                        raise DomainError('INVALID_ADAPTER_CONTRACT',
+                            'primary_prepare_result_invalid')
+                    for item in pending:
+                        self._project_adapter_diagnostic(descriptor, item)
+            diagnostics = getattr(module, 'diagnostics', None)
+            if diagnostics:
+                for source in sources:
+                    for item in diagnostics(source):
+                        self._project_adapter_diagnostic(
+                            descriptor, item, source)
+
+        enricher_groups = {}
+        self.enricher_descriptors_by_source_id = {}
+        for source in self.sources:
+            owner = self._owner(source)
+            if owner is None or self.routes[source.path].disposition != 'analyze':
+                continue
+            evidence = dict(getattr(owner, 'activation_evidence',
+                lambda _source: {})(source))
+            package = source.supporting_inputs.get('package_manifest', {}).get(
+                'package')
+            if package:
+                evidence['dependencies'] = sorted({
+                    *evidence.get('dependencies', ()),
+                    *(item['name'] for item in package['dependencies'])})
+            descriptors = tuple(enricher_descriptors(source, evidence))
+            self.enricher_descriptors_by_source_id[source.resource_id] = descriptors
+            for descriptor in descriptors:
+                try:
+                    cache_key = ('enricher', descriptor['id'],
+                        descriptor['module'])
+                    module = self.owner_module_cache.get(cache_key)
+                    if module is None:
+                        module = load_installed(descriptor['module'])
+                        self.owner_module_cache[cache_key] = module
+                except Exception:
+                    raise DomainError('ADAPTER_UNAVAILABLE',
+                        'enricher_load_failed') from None
+                enricher_groups.setdefault(descriptor['id'],
+                    (descriptor, module, []))[2].append(source)
+        for _owner_id, (descriptor, module, sources) in sorted(
+                enricher_groups.items()):
+            prepare = getattr(module, 'prepare', None)
+            if prepare:
+                try:
+                    pending = prepare(sources, self.units, self.diagnostics)
+                except Exception:
+                    raise DomainError('ADAPTER_UNAVAILABLE',
+                        'enricher_prepare_failed') from None
+                _register_redaction_spans(self.units)
+                if pending is not None:
+                    if not isinstance(pending, list) or not all(
+                            isinstance(item, dict) for item in pending):
+                        raise DomainError('INVALID_ADAPTER_CONTRACT',
+                            'enricher_prepare_result_invalid')
+                    for item in pending:
+                        self._project_adapter_diagnostic(descriptor, item)
+
+    def extract(self):
+        self._execute_installed_owners()
+        for unit in self.units:
+            self.add_unit(unit)
+        self._connections()
+        self._anchor_correspondences()
+        self._observations()
+        self._canonicalize_anchors()
+        self._documentation_edges()
+        self._finalize_source_resources()
+        self._capabilities()
+        self._traces()
+        from .business_domain_snapshots import capture_supplied
+        self.external_freshness, self.snapshot_inputs = capture_supplied(self)
+        self.facts['coverage']['anchors_total'] = len(self.facts['anchors'])
+        self.facts['coverage']['anchors_pending'] = len(self.facts['anchors'])
+        self.facts['coverage']['evidence_valid'] = len(self.facts['evidence'])
+        self.facts['limits']['source_bytes'] = sum(
+            source.original_byte_length for source in self.sources)
+        self.facts['limits']['semantic_units_total'] = len(self.facts['traces'])
+        self.facts['limits']['semantic_units_pending'] = len(self.facts['traces'])
+        return self._finalize_artifact()
```

Replace the current inline dictionary-diagnostic validation with this one
projector for primary adapters, supporting consumers and enrichers:

```diff
+    def _validate_adapter_diagnostic(self, descriptor, diagnostic, source=None):
+        if not isinstance(diagnostic, dict):
+            raise DomainError('INVALID_ADAPTER_CONTRACT',
+                'adapter_diagnostic_invalid')
+        if set(diagnostic) - {
+                'source_id', 'code', 'reason', 'span', 'named_value_spans'}:
+            raise DomainError('INVALID_ADAPTER_CONTRACT',
+                'adapter_diagnostic_fields_invalid')
+        source_id = diagnostic.get('source_id')
+        if source is None:
+            source = next((item for item in self.sources
+                if item.resource_id == source_id), None)
+        elif source_id is not None and source_id != source.resource_id:
+            raise DomainError('INVALID_ADAPTER_CONTRACT',
+                'adapter_diagnostic_source_invalid')
+        span = diagnostic.get('span')
+        reason = diagnostic.get('reason')
+        code = diagnostic.get('code')
+        named_spans = diagnostic.get('named_value_spans', ())
+        if (source is None
+                or not isinstance(span, (tuple, list)) or len(span) != 2
+                or any(type(value) is not int for value in span)
+                or not 0 <= span[0] <= span[1] <= len(source.text)
+                or code not in descriptor['diagnostic_codes']
+                or not isinstance(reason, str) or not reason
+                or '\n' in reason or '\r' in reason):
+            raise DomainError('INVALID_ADAPTER_CONTRACT',
+                'adapter_diagnostic_invalid')
+        _validate_named_value_spans(source, named_spans)
+        return source
+
+    def _project_adapter_diagnostic(self, descriptor, diagnostic, source=None):
+        source = self._validate_adapter_diagnostic(
+            descriptor, diagnostic, source)
+        span = diagnostic['span']
+        reason = diagnostic['reason']
+        code = diagnostic['code']
+        named_spans = diagnostic.get('named_value_spans', ())
+        _register_named_value_spans(source, named_spans)
+        evidence_id = self.evidence(source, span[0], span[1])
+        self.diagnostics.append(record('Diagnostic', code=code,
+            message=reason, subject_ids=[source.resource_id],
+            evidence_ids=[evidence_id]))
```

The call above factors the existing fingerprint, snapshot-state, limit
accounting and schema-validation tail into `_finalize_artifact()`; the exact
tail changes appear under “Enforce coverage, cache and publication boundaries.”

Remove every later registry or adapter reselection with these exact hunks:

```diff
-        kind='test' if re.search(CATALOG['test_path_pattern'],source.path) else descriptor(source.path)['source_kind']
+        route = self.routes[source.path]
+        kind = ('test' if re.search(CATALOG['test_path_pattern'], source.path)
+            else CATALOG['source_kind_by_category'].get(
+                route.classification.category, 'source'))
 @@
-        self.facts['source_snapshots'][sid]=record('Snapshot',id=sid,resource_kind=source.language,resource_identity=source.path,content_hash=source.source_hash,local_blob_path=path,retrieved_at=captured_at)
+        self.facts['source_snapshots'][sid] = record('Snapshot', id=sid,
+            resource_kind=(source.language or
+                           self.routes[source.path].classification.category),
+            resource_identity=source.path, content_hash=source.source_hash,
+            local_blob_path=path, retrieved_at=captured_at)
 @@
-            interaction = getattr(adapter_for(unit.source),'interaction',None)
+            owner = self._owner(unit.source)
+            interaction = getattr(owner, 'interaction', None) if owner else None
 @@
-            normalize = getattr(adapter_for(u.source),'symbol_key',lambda name:name)
+            owner = self._owner(u.source)
+            normalize = getattr(owner, 'symbol_key', lambda name: name)
 @@
-            adapter = adapter_for(unit.source)
+            adapter = self._owner(unit.source)
+            if adapter is None:
+                continue
 @@
-            relations = getattr(adapter_for(source),'relations',None)
+            owner = self._owner(source)
+            relations = getattr(owner, 'relations', None) if owner else None
 @@
-            adapter = adapter_for(unit.source)
+            adapter = self._owner(unit.source)
```

After these hunks, `descriptor(` and `adapter_for(` have no call sites in
`business_domain_extract.py`; only their legacy definitions remain in
`business_domain_adapters/__init__.py` for callers outside this pipeline.

### Parse Java Properties from the retained bytes

Create `lib/context/business_domain_adapters/java_properties.py` with this
implementation. It performs no I/O and imports no core redaction function:

```diff
+"""Deterministic Java Properties source adapter."""
+from __future__ import annotations
+
+import re
+from dataclasses import dataclass
+from pathlib import PurePosixPath
+
+from .base import ConfigurationDeclaration, DecodedSource, Source, Unit
+from ..business_domain_schema import digest
+
+_APPLICATION = re.compile(r'application(?:-([^/]+))?\.properties\Z')
+_MESSAGES = re.compile(r'messages(?:_[^/]+)?\.properties\Z')
+_SPACE = ' \t\f'
+_ESCAPES = {'t': '\t', 'n': '\n', 'r': '\r', 'f': '\f'}
+
+
+@dataclass(frozen=True)
+class _LogicalLine:
+    text: str
+    offsets: tuple[int, ...]
+    start: int
+    end: int
+
+
+class _PropertiesSyntaxError(ValueError):
+    def __init__(self, cause: str, start: int, end: int):
+        super().__init__(cause)
+        self.cause, self.start, self.end = cause, start, end
+
+
+def decode(raw: bytes) -> DecodedSource:
+    try:
+        text, encoding = raw.decode('utf-8'), 'utf-8'
+    except UnicodeDecodeError:
+        text, encoding = raw.decode('iso-8859-1'), 'iso-8859-1'
+    return DecodedSource(text, encoding, len(raw))
+
+
+def _physical_lines(text: str):
+    cursor = 0
+    while cursor < len(text):
+        start = cursor
+        while cursor < len(text) and text[cursor] not in '\r\n':
+            cursor += 1
+        end = cursor
+        if cursor < len(text):
+            if text[cursor] == '\r' and cursor + 1 < len(text) \
+                    and text[cursor + 1] == '\n':
+                cursor += 2
+            else:
+                cursor += 1
+        yield start, end
+    if not text:
+        return
+
+
+def _logical_lines(text: str):
+    chars, offsets = [], []
+    logical_start = None
+    for physical_start, physical_end in _physical_lines(text):
+        body_start = physical_start
+        comment_cursor = physical_start
+        while comment_cursor < physical_end and text[comment_cursor] in _SPACE:
+            comment_cursor += 1
+        is_comment = (logical_start is None and comment_cursor < physical_end
+            and text[comment_cursor] in '#!')
+        if logical_start is not None:
+            while body_start < physical_end and text[body_start] in _SPACE:
+                body_start += 1
+        body = text[body_start:physical_end]
+        slash_count = len(body) - len(body.rstrip('\\'))
+        continued = not is_comment and slash_count % 2 == 1
+        if continued:
+            body = body[:-1]
+        if logical_start is None:
+            logical_start = physical_start
+        chars.extend(body)
+        offsets.extend(range(body_start, body_start + len(body)))
+        if not continued:
+            yield _LogicalLine(''.join(chars), tuple(offsets), logical_start,
+                physical_end)
+            chars, offsets, logical_start = [], [], None
+    if logical_start is not None:
+        yield _LogicalLine(''.join(chars), tuple(offsets), logical_start,
+            len(text))
+
+
+def _split_declaration(line: str):
+    cursor = 0
+    while cursor < len(line) and line[cursor] in _SPACE:
+        cursor += 1
+    if cursor == len(line) or line[cursor] in '#!':
+        return None
+    key_start, escaped = cursor, False
+    while cursor < len(line):
+        char = line[cursor]
+        if not escaped and (char in '=:' or char in _SPACE):
+            break
+        if char == '\\':
+            escaped = not escaped
+        else:
+            escaped = False
+        cursor += 1
+    key_end = cursor
+    whitespace_separator = cursor < len(line) and line[cursor] in _SPACE
+    while cursor < len(line) and line[cursor] in _SPACE:
+        cursor += 1
+    if cursor < len(line) and line[cursor] in '=:' \
+            and (whitespace_separator or cursor == key_end):
+        cursor += 1
+    while cursor < len(line) and line[cursor] in _SPACE:
+        cursor += 1
+    return key_start, key_end, cursor, len(line)
+
+
+def _span(offsets, start, end, fallback):
+    if start < len(offsets):
+        first = offsets[start]
+        last = offsets[min(max(start, end - 1), len(offsets) - 1)] + 1
+        return first, last
+    return fallback, fallback
+
+
+def _unicode_escape(text, offsets, cursor, end, fallback):
+    finish = cursor + 6
+    if finish > end or text[cursor + 1] != 'u' \
+            or not re.fullmatch(r'[0-9a-fA-F]{4}', text[cursor + 2:finish]):
+        start, stop = _span(offsets, cursor, min(end, finish), fallback)
+        raise _PropertiesSyntaxError('invalid_unicode_escape', start, stop)
+    return int(text[cursor + 2:finish], 16), finish
+
+
+def _decode_token(text, offsets, start, end, fallback):
+    value, cursor = [], start
+    while cursor < end:
+        if text[cursor] != '\\':
+            codepoint, finish = ord(text[cursor]), cursor + 1
+        elif cursor + 1 >= end:
+            start_offset, stop = _span(offsets, cursor, cursor + 1, fallback)
+            raise _PropertiesSyntaxError('truncated_escape', start_offset, stop)
+        elif text[cursor + 1] == 'u':
+            codepoint, finish = _unicode_escape(text, offsets, cursor, end, fallback)
+        else:
+            value.append(_ESCAPES.get(text[cursor + 1], text[cursor + 1]))
+            cursor += 2
+            continue
+        if 0xD800 <= codepoint <= 0xDBFF:
+            if finish >= end or text[finish:finish + 2] != '\\u':
+                first, last = _span(offsets, cursor, finish, fallback)
+                raise _PropertiesSyntaxError('lone_high_surrogate', first, last)
+            low, low_finish = _unicode_escape(text, offsets, finish, end, fallback)
+            if not 0xDC00 <= low <= 0xDFFF:
+                first, last = _span(offsets, finish, low_finish, fallback)
+                raise _PropertiesSyntaxError('invalid_surrogate_pair', first, last)
+            codepoint = 0x10000 + ((codepoint - 0xD800) << 10) + low - 0xDC00
+            finish = low_finish
+        elif 0xDC00 <= codepoint <= 0xDFFF:
+            first, last = _span(offsets, cursor, finish, fallback)
+            raise _PropertiesSyntaxError('lone_low_surrogate', first, last)
+        value.append(chr(codepoint))
+        cursor = finish
+    return ''.join(value)
+
+
+def _source_spans(offsets):
+    spans = []
+    for offset in offsets:
+        if spans and offset == spans[-1][1]:
+            spans[-1] = (spans[-1][0], offset + 1)
+        else:
+            spans.append((offset, offset + 1))
+    return tuple(spans)
+
+
+def _configuration_scope(path: str):
+    parts = PurePosixPath(path).parts
+    locations = [index for index in range(len(parts) - 3)
+        if parts[index] == 'src' and parts[index + 1] in {'main', 'test'}
+        and parts[index + 2] == 'resources']
+    if len(locations) != 1:
+        raise ValueError('invalid_configuration_path')
+    environment = parts[locations[0] + 1]
+    name = parts[-1]
+    application = _APPLICATION.fullmatch(name)
+    if application:
+        return environment, application.group(1), 'application_configuration'
+    if _MESSAGES.fullmatch(name):
+        return environment, None, 'message_catalog'
+    raise ValueError('invalid_configuration_path')
+
+
+def extract(source: Source) -> list[Unit]:
+    environment, profile, role = _configuration_scope(source.path)
+    units, occurrences = [], {}
+    pending_diagnostics = []
+    source.java_properties_diagnostics = pending_diagnostics
+    skip_bom_declaration = source.text.startswith('\ufeff')
+    if skip_bom_declaration:
+        pending_diagnostics.append({
+            'code': 'JAVA_PROPERTIES_SYNTAX_INVALID',
+            'reason': 'byte_order_mark_not_supported', 'span': (0, 1)})
+    for logical in _logical_lines(source.text):
+        declaration = _split_declaration(logical.text)
+        if declaration is None:
+            continue
+        key_start, key_end, value_start, value_end = declaration
+        if skip_bom_declaration and logical.start == 0:
+            skip_bom_declaration = False
+            continue
+        try:
+            key = _decode_token(logical.text, logical.offsets,
+                key_start, key_end, logical.end)
+            value = _decode_token(logical.text, logical.offsets,
+                value_start, value_end, logical.end)
+        except _PropertiesSyntaxError as error:
+            pending_diagnostics.append({
+                'code': 'JAVA_PROPERTIES_SYNTAX_INVALID',
+                'reason': error.cause, 'span': (error.start, error.end)})
+            continue
+        occurrence = occurrences.get(key, 0)
+        occurrences[key] = occurrence + 1
+        configuration = ConfigurationDeclaration(key, value, occurrence,
+            profile, environment, role,
+            _source_spans(logical.offsets[value_start:value_end]))
+        units.append(Unit(source=source, name=key,
+            qualified='property:' + digest([source.path, key, occurrence]),
+            start=logical.start, end=logical.end, kind='field',
+            configuration=configuration))
+    return units
+
+
+def bindings(unit: Unit):
+    declaration = unit.configuration
+    if declaration is None:
+        return []
+    return [{
+        'name': declaration.key,
+        'value_type': 'string',
+        'direction': 'internal',
+        'expression': declaration.value,
+        'scope': {
+            'environment': declaration.environment,
+            'tenant': None,
+            'actor': None,
+            'profile': declaration.profile,
+            'effective_from': None,
+            'effective_to': None,
+            'version': None,
+            'entrypoint_ids': None,
+        },
+        'resolution': 'unresolved',
+        'reason': 'Repository declaration retained; effective precedence was not evaluated.',
+    }]
+
+
+def diagnostics(source):
+    return list(getattr(source, 'java_properties_diagnostics', ()))
+
+
+def symbol_key(name):
+    return name
+
+
+def calls(unit):
+    return []
+
+
+def candidates(unit, receiver, name, available, position=None):
+    return []
+
+
+def resources(unit):
+    return []
+
+
+def observations(unit):
+    return []
+
+
+def operations(unit):
+    return []
```

Core registers sensitive spans immediately after a successful primary extract:

```diff
+_SENSITIVE_NAME_RE = re.compile(
+    r'(?i)(?:^|[._-])(?:password|passwd|secret|credential|token|'
+    r'api[_-]?key|access[_-]?token)(?:$|[._-])')
+
+
+def _sensitive_name(name: str) -> bool:
+    return bool(_SENSITIVE_NAME_RE.search(name))
+
+
+def _validate_named_value_spans(source, candidates):
+    if (not isinstance(candidates, (tuple, list))
+            or not all(isinstance(item, (tuple, list)) and len(item) == 3
+                and (item[0] is None or isinstance(item[0], str))
+                and type(item[1]) is int and type(item[2]) is int
+                and 0 <= item[1] <= item[2] <= len(source.text)
+                for item in candidates)):
+        raise DomainError('INVALID_ADAPTER_CONTRACT',
+            'named_value_spans_invalid')
+    return tuple(tuple(item) for item in candidates)
+
+
+def _register_named_value_spans(source, candidates) -> None:
+    candidates = _validate_named_value_spans(source, candidates)
+    spans = [*source.redaction_spans,
+        *((start, end) for name, start, end in candidates
+          if name is None or _sensitive_name(name))]
+    merged = []
+    for start, end in sorted(spans):
+        if merged and start <= merged[-1][1]:
+            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
+        else:
+            merged.append((start, end))
+    source.redaction_spans[:] = merged
+
+
+def _register_redaction_spans(units) -> None:
+    for unit in units:
+        declaration = unit.configuration
+        if declaration is not None:
+            _register_named_value_spans(unit.source,
+                tuple((declaration.key, start, end)
+                      for start, end in declaration.value_spans))
+        for observation in getattr(unit, 'configuration_observations', ()):
+            _register_named_value_spans(
+                unit.source, observation.get('named_value_spans', ()))
```

### Reuse the package-manifest parser

Add this pure parser to `lib/context/repository_digest_runtime.py`, then keep
`_load_package_json()` as the existing I/O boundary:

```diff
+from dataclasses import dataclass
+
+
+class PackageJsonError(ValueError):
+    def __init__(self, cause: str, start: int, end: int):
+        super().__init__(cause)
+        self.cause, self.start, self.end = cause, start, end
+
+
+@dataclass(frozen=True)
+class PackageManifest:
+    engines: tuple[dict, ...]
+    dependencies: tuple[dict, ...]
+
+
+def _object_section(data, name, text, strict):
+    value = data.get(name, {})
+    if not isinstance(value, dict):
+        if strict:
+            raise PackageJsonError(f'{name}_must_be_object', 0, len(text))
+        return {}
+    if strict and not all(isinstance(item, str) for item in value.values()):
+        raise PackageJsonError(f'{name}_values_must_be_strings', 0, len(text))
+    return {key: item if isinstance(item, str) else None
+            for key, item in value.items()}
+
+
+def parse_package_json(text: str, sections=('engines', 'dependencies',
+        'devDependencies'), strict=True) -> PackageManifest:
+    try:
+        data = json.loads(text)
+    except json.JSONDecodeError as error:
+        start = min(error.pos, len(text))
+        raise PackageJsonError('json_syntax_invalid', start,
+            min(start + 1, len(text))) from None
+    if not isinstance(data, dict):
+        raise PackageJsonError('top_level_must_be_object', 0, len(text))
+    allowed = {'engines', 'dependencies', 'devDependencies'}
+    if (not isinstance(sections, (tuple, list)) or not sections
+            or set(sections) - allowed):
+        raise ValueError('package_sections_invalid')
+    engines = (_object_section(data, 'engines', text, strict)
+        if 'engines' in sections else {})
+    runtime = (_object_section(data, 'dependencies', text, strict)
+        if 'dependencies' in sections else {})
+    development = (_object_section(data, 'devDependencies', text, strict)
+        if 'devDependencies' in sections else {})
+    return PackageManifest(
+        tuple({'name': name, 'constraint': constraint}
+            for name, constraint in sorted(engines.items())),
+        tuple(sorted((
+            *({'name': name, 'constraint': constraint,
+               'dependency_kind': 'runtime'}
+              for name, constraint in runtime.items()),
+            *({'name': name, 'constraint': constraint,
+               'dependency_kind': 'development'}
+              for name, constraint in development.items()),
+        ), key=lambda item: (item['name'],
+            0 if item['dependency_kind'] == 'runtime' else 1,
+            item['constraint']))),
+    )
+
+
-def _load_package_json(path: Path) -> dict[str, Any] | None:
+def _load_package_json(path: Path, sections) -> PackageManifest | None:
     try:
-        data = json.loads(path.read_text(encoding="utf-8"))
-    except (OSError, ValueError):
+        return parse_package_json(path.read_text(encoding='utf-8'), sections,
+                                  strict=False)
+    except (OSError, UnicodeDecodeError, PackageJsonError):
         return None
-    return data if isinstance(data, dict) else None
```

Apply the factored model in both existing callers. The dependency tuple orders
runtime before development, so the comprehension retains the current
`devDependencies`-wins behavior for duplicate names:

```diff
     for rel_path in _package_json_paths(project_root, project_map):
-        data = _load_package_json(project_root / rel_path)
-        if data is not None:
-            engines = data.get("engines")
-            if isinstance(engines, dict):
-                for lang, version in engines.items():
-                    if isinstance(version, str):
-                        runtimes.append({
-                            "language": lang, "version": version, "source_file": rel_path,
-                            "evidence": [make_evidence("manifest", f"{rel_path} engines.{lang}", path=rel_path)],
-                        })
+        manifest = _load_package_json(project_root / rel_path, ('engines',))
+        if manifest is not None:
+            for engine in manifest.engines:
+                lang, version = engine['name'], engine['constraint']
+                if version is None:
+                    continue
+                runtimes.append({
+                    "language": lang, "version": version,
+                    "source_file": rel_path,
+                    "evidence": [make_evidence("manifest",
+                        f"{rel_path} engines.{lang}", path=rel_path)],
+                })
 @@
     for rel_path in _package_json_paths(project_root, project_map):
-        data = _load_package_json(project_root / rel_path)
-        if data is not None:
-            deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
+        manifest = _load_package_json(project_root / rel_path,
+            ('dependencies', 'devDependencies'))
+        if manifest is not None:
+            deps = {item['name']: item['constraint']
+                    for item in manifest.dependencies}
             for name in _JS_FRAMEWORK_NAMES:
```

Create `lib/context/business_domain_adapters/package_manifest.py`:

```diff
+"""Normalize installed package.json supporting inputs without I/O."""
+from pathlib import PurePosixPath
+
+from .base import SupportingConsumerResult
+from ..repository_digest_runtime import PackageJsonError, parse_package_json
+
+
+def _scope(path: str) -> str:
+    parent = PurePosixPath(path).parent.as_posix()
+    return '.' if parent in {'', '.'} else parent
+
+
+def consume(supporting_sources, primary_sources) -> SupportingConsumerResult:
+    del primary_sources
+    consumed, inputs, diagnostics = [], [], []
+    for source in sorted(supporting_sources, key=lambda item: item.resource_id):
+        try:
+            manifest = parse_package_json(source.text)
+        except PackageJsonError as error:
+            diagnostics.append({'source_id': source.resource_id,
+                'code': 'PACKAGE_JSON_INVALID', 'reason': error.cause,
+                'span': (error.start, error.end)})
+            continue
+        consumed.append(source.resource_id)
+        inputs.append({
+            'source_id': source.resource_id,
+            'scope_dir': _scope(source.path),
+            'document_kind': 'package',
+            'engines': list(manifest.engines),
+            'dependencies': list(manifest.dependencies),
+        })
+    return SupportingConsumerResult(tuple(consumed), tuple(inputs),
+        tuple(diagnostics))
```

### Reuse one TypeScript module resolver

Add these pure helpers to `lib/context/layer1_domain_clustering.py`:

```diff
+import posixpath
+
+
+class TypeScriptModuleResolutionError(ValueError):
+    def __init__(self, cause: str, start: int, end: int):
+        super().__init__(cause)
+        self.cause, self.start, self.end = cause, start, end
+
+
+def _ts_error(cause, text):
+    raise TypeScriptModuleResolutionError(cause, 0, len(text))
+
+
+def _pattern(value, text):
+    if not isinstance(value, str) or value.count('*') > 1:
+        _ts_error('invalid_alias_pattern', text)
+    return {'pattern': value, 'wildcard': '*' in value}
+
+
+def parse_typescript_module_resolution(text: str, document_kind: str) -> dict:
+    try:
+        data = json.loads(text)
+    except json.JSONDecodeError as error:
+        start = min(error.pos, len(text))
+        raise TypeScriptModuleResolutionError('json_syntax_invalid', start,
+            min(start + 1, len(text))) from None
+    if not isinstance(data, dict):
+        _ts_error('top_level_must_be_object', text)
+    if document_kind == 'tsconfig':
+        compiler = data.get('compilerOptions', {})
+        if not isinstance(compiler, dict):
+            _ts_error('compiler_options_must_be_object', text)
+        paths = compiler.get('paths', {})
+        if not isinstance(paths, dict):
+            _ts_error('paths_must_be_object', text)
+        aliases = []
+        for alias, targets in paths.items():
+            parsed_alias = _pattern(alias, text)
+            if not isinstance(targets, list) or not targets:
+                _ts_error('alias_targets_must_be_nonempty_array', text)
+            parsed_targets = tuple(_pattern(target, text) for target in targets)
+            if not parsed_alias['wildcard'] and any(
+                    target['wildcard'] for target in parsed_targets):
+                _ts_error('exact_alias_cannot_capture_wildcard_target', text)
+            aliases.append({**parsed_alias, 'targets': parsed_targets})
+        return {'aliases': tuple(sorted(aliases,
+                    key=lambda item: item['pattern'])),
+                'declared_external_modules': ()}
+    if document_kind == 'typings':
+        names = set()
+        for section_name in ('dependencies', 'globalDependencies',
+                'ambientDependencies'):
+            section = data.get(section_name, {})
+            if not isinstance(section, dict) or not all(
+                    isinstance(name, str) for name in section):
+                _ts_error(f'{section_name}_must_be_object', text)
+            names.update(section)
+        return {'aliases': (), 'declared_external_modules': tuple(
+            {'name': name} for name in sorted(names))}
+    _ts_error('document_kind_invalid', text)
+
+
+def _match_alias(pattern: str, import_name: str):
+    if '*' not in pattern:
+        return '' if import_name == pattern else None
+    prefix, suffix = pattern.split('*')
+    if not import_name.startswith(prefix) or not import_name.endswith(suffix):
+        return None
+    if len(import_name) < len(prefix) + len(suffix):
+        return None
+    return import_name[len(prefix):len(import_name) - len(suffix) if suffix else None]
+
+
+def normalize_typescript_path_target(scope_dir: str, target: str,
+        capture: str) -> str:
+    substituted = target.replace('*', capture) if '*' in target else target
+    scoped = substituted if scope_dir == '.' else posixpath.join(scope_dir, substituted)
+    normalized = posixpath.normpath(scoped)
+    if normalized == '..' or normalized.startswith('../') or normalized.startswith('/'):
+        raise TypeScriptModuleResolutionError('target_escapes_repository', 0, 0)
+    return normalized
+
+
+def _probe_typescript_path(candidate: str, source_paths) -> tuple[str, ...]:
+    available = set(source_paths)
+    probes = (candidate, *(candidate + suffix for suffix in
+        ('.ts', '.tsx', '.js', '.jsx', '/index.ts', '/index.tsx',
+         '/index.js', '/index.jsx')))
+    return tuple(path for path in probes if path in available)
+
+
+def resolve_typescript_path_alias(import_name: str, scope_dir: str,
+        aliases, source_paths) -> dict:
+    matches = []
+    for alias in aliases:
+        capture = _match_alias(alias['pattern'], import_name)
+        if capture is None:
+            continue
+        prefix, _, suffix = alias['pattern'].partition('*')
+        matches.append((len(prefix) + len(suffix), alias, capture))
+    if not matches:
+        return {'state': 'unmatched', 'candidates': ()}
+    specificity = max(item[0] for item in matches)
+    candidates = set()
+    for _, alias, capture in sorted(
+            (item for item in matches if item[0] == specificity),
+            key=lambda item: item[1]['pattern']):
+        for target in alias['targets']:
+            candidate = normalize_typescript_path_target(scope_dir,
+                target['pattern'], capture)
+            candidates.update(_probe_typescript_path(candidate, source_paths))
+    ordered = tuple(sorted(candidates))
+    return {'state': ('resolved' if len(ordered) == 1 else
+                      'ambiguous' if ordered else 'unresolved'),
+            'candidates': ordered}
```

Replace `_find_tsconfig_paths()` and the alias branch in
`_resolve_typescript_imports()` with the shared representation. A malformed
configuration remains a safe Layer 1 miss, matching the current caller's
failure contract:

```diff
-def _resolve_typescript_imports(
-    repo_path: str, ts_files: list[str],
-    path_aliases: list[tuple[str, str, str]] | None = None,
-) -> list[tuple[str, str]]:
-    """TypeScript import resolution via regex + tsconfig path aliases."""
-    file_set = set(ts_files)
-    edges = []
-
-    if path_aliases is None:
-        path_aliases = []
-
-    all_alias_prefixes = {prefix for _, prefix, _ in path_aliases}
-
-    import_re = re.compile(
-        r"""(?:import|export)\s+(?:type\s+)?(?:\{[\s\S]*?\}\s+from|[^'";\n]+from)\s+['"]([^'"]+)['"]|"""
-        r"""(?:import|export)\s+['"]([^'"]+)['"]|"""
-        r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)|"""
-        r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)""",
-        re.MULTILINE,
-    )
-
-    probe_exts = [".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx", "/index.js", "/index.jsx"]
-
-    for source_file in ts_files:
-        full_path = os.path.join(repo_path, source_file)
-        try:
-            with open(full_path, "r", errors="ignore") as fh:
-                content = fh.read(100_000)
-        except OSError:
-            continue
-
-        source_dir = os.path.dirname(source_file)
-
-        for match in import_re.finditer(content):
-            raw = match.group(1) or match.group(2) or match.group(3) or match.group(4)
-            if not raw:
-                continue
-
-            if not raw.startswith(".") and not any(raw.startswith(p) for p in all_alias_prefixes):
-                continue
-
-            resolved_raw = raw
-            is_aliased = False
-            best_scope_len = -1
-            for scope_dir, prefix, replacement in path_aliases:
-                if raw.startswith(prefix) and source_file.startswith(scope_dir + "/" if scope_dir else ""):
-                    if len(scope_dir) > best_scope_len:
-                        best_scope_len = len(scope_dir)
-                        resolved_raw = replacement + raw[len(prefix):]
-                        is_aliased = True
-
-            if is_aliased:
-                candidate_base = os.path.normpath(resolved_raw)
-            elif resolved_raw.startswith("."):
-                candidate_base = os.path.normpath(os.path.join(source_dir, resolved_raw))
-            else:
-                candidate_base = resolved_raw
-
-            found = None
-            if candidate_base in file_set:
-                found = candidate_base
-            else:
-                for ext in probe_exts:
-                    probe = candidate_base + ext
-                    if probe in file_set:
-                        found = probe
-                        break
-
-            if found and found != source_file:
-                edges.append((source_file, found))
-
-    return edges
-
-
-def _find_tsconfig_paths(
-    repo_path: str, ts_files: list[str],
-) -> list[tuple[str, str, str]]:
-    """Find tsconfig.json path aliases, scoped to their directory.
-
-    Returns list of (scope_dir, alias_prefix, resolved_target).
-    """
-    result = []
-    seen_tsconfigs: set[str] = set()
-
-    seen_dirs: set[str] = set()
-    for f in ts_files:
-        d = os.path.dirname(f)
-        while d:
-            if d not in seen_dirs:
-                seen_dirs.add(d)
-                tsconfig_path = os.path.join(repo_path, d, "tsconfig.json")
-                if os.path.exists(tsconfig_path) and d not in seen_tsconfigs:
-                    seen_tsconfigs.add(d)
-                    try:
-                        with open(tsconfig_path) as fh:
-                            config = json.load(fh)
-                        paths = config.get("compilerOptions", {}).get("paths", {})
-                        for alias, targets in paths.items():
-                            prefix = alias.rstrip("*")
-                            if targets:
-                                raw_target = targets[0].rstrip("*")
-                                resolved = os.path.normpath(os.path.join(d, raw_target))
-                                result.append((d, prefix, resolved + "/"))
-                    except (json.JSONDecodeError, OSError):
-                        pass
-            if "/" in d:
-                d = d.rsplit("/", 1)[0]
-            else:
-                break
-
-    # Check root tsconfig
-    tsconfig_path = os.path.join(repo_path, "tsconfig.json")
-    if os.path.exists(tsconfig_path) and "" not in seen_tsconfigs:
-        try:
-            with open(tsconfig_path) as fh:
-                config = json.load(fh)
-            paths = config.get("compilerOptions", {}).get("paths", {})
-            for alias, targets in paths.items():
-                prefix = alias.rstrip("*")
-                if targets:
-                    raw_target = targets[0].rstrip("*")
-                    result.append(("", prefix, raw_target))
-        except (json.JSONDecodeError, OSError):
-            pass
-
-    return result
-
-
+def _find_tsconfig_paths(repo_path: str, ts_files: list[str]):
+    candidates = {''}
+    for source_file in ts_files:
+        directory = os.path.dirname(source_file)
+        while directory:
+            candidates.add(directory)
+            directory = (directory.rsplit('/', 1)[0]
+                         if '/' in directory else '')
+    result = []
+    for scope_dir in sorted(candidates):
+        path = os.path.join(repo_path, scope_dir, 'tsconfig.json')
+        if not os.path.isfile(path):
+            continue
+        try:
+            with open(path, encoding='utf-8') as stream:
+                parsed = parse_typescript_module_resolution(
+                    stream.read(), 'tsconfig')
+        except (OSError, UnicodeDecodeError,
+                TypeScriptModuleResolutionError):
+            continue
+        result.append((scope_dir, parsed['aliases']))
+    return result
```

```diff
+def _resolve_typescript_imports(
+    repo_path: str, ts_files: list[str], path_aliases=None,
+) -> list[tuple[str, str]]:
+    path_aliases = path_aliases or []
+    file_set = set(ts_files)
+    edges = []
+    import_re = re.compile(
+        r'''(?:import|export)\s+(?:type\s+)?(?:\{[\s\S]*?\}\s+from|[^'";\n]+from)\s+['"]([^'"]+)['"]|'''
+        r'''(?:import|export)\s+['"]([^'"]+)['"]|'''
+        r'''require\s*\(\s*['"]([^'"]+)['"]\s*\)|'''
+        r'''import\s*\(\s*['"]([^'"]+)['"]\s*\)''', re.MULTILINE)
+    for source_file in ts_files:
+        try:
+            with open(os.path.join(repo_path, source_file),
+                      encoding='utf-8', errors='ignore') as stream:
+                content = stream.read(100_000)
+        except OSError:
+            continue
+        source_dir = os.path.dirname(source_file)
+        compatible = [(scope, aliases) for scope, aliases in path_aliases
+            if not scope or source_file.startswith(scope + '/')]
+        selected = (max(compatible, key=lambda item: len(item[0]))
+                    if compatible else ('', ()))
+        for match in import_re.finditer(content):
+            raw = next((value for value in match.groups() if value), None)
+            if not raw:
+                continue
+            if raw.startswith('.'):
+                base = os.path.normpath(os.path.join(source_dir, raw))
+                probes = (base, *(base + suffix for suffix in (
+                    '.ts', '.tsx', '.js', '.jsx', '/index.ts', '/index.tsx',
+                    '/index.js', '/index.jsx')))
+                targets = tuple(path for path in probes if path in file_set)
+            else:
+                resolution = resolve_typescript_path_alias(
+                    raw, selected[0] or '.', selected[1], ts_files)
+                targets = resolution['candidates']
+            if len(targets) == 1 and targets[0] != source_file:
+                edges.append((source_file, targets[0]))
+    return edges
```

Create `lib/context/business_domain_adapters/typescript_module_resolution.py`:

```diff
+"""Normalize TypeScript module-resolution supporting inputs without I/O."""
+from pathlib import PurePosixPath
+
+from .base import SupportingConsumerResult
+from ..layer1_domain_clustering import (TypeScriptModuleResolutionError,
+    normalize_typescript_path_target, parse_typescript_module_resolution)
+
+
+def _scope(path: str) -> str:
+    parent = PurePosixPath(path).parent.as_posix()
+    return '.' if parent in {'', '.'} else parent
+
+
+def _kind(path: str) -> str:
+    name = PurePosixPath(path).name
+    if name == 'tsconfig.json':
+        return 'tsconfig'
+    if name == 'typings.json':
+        return 'typings'
+    raise ValueError('invalid_typescript_module_resolution_path')
+
+
+def consume(supporting_sources, primary_sources) -> SupportingConsumerResult:
+    del primary_sources
+    consumed, inputs, diagnostics = [], [], []
+    for source in sorted(supporting_sources, key=lambda item: item.resource_id):
+        try:
+            kind, scope = _kind(source.path), _scope(source.path)
+            normalized = parse_typescript_module_resolution(source.text, kind)
+            for alias in normalized['aliases']:
+                for target in alias['targets']:
+                    normalize_typescript_path_target(
+                        scope, target['pattern'], 'probe')
+        except TypeScriptModuleResolutionError as error:
+            start, end = ((0, len(source.text))
+                if error.cause == 'target_escapes_repository'
+                else (error.start, error.end))
+            diagnostics.append({'source_id': source.resource_id,
+                'code': 'TYPESCRIPT_MODULE_RESOLUTION_INVALID',
+                'reason': error.cause, 'span': (start, end)})
+            continue
+        except ValueError as error:
+            diagnostics.append({'source_id': source.resource_id,
+                'code': 'TYPESCRIPT_MODULE_RESOLUTION_INVALID',
+                'reason': str(error), 'span': (0, len(source.text))})
+            continue
+        consumed.append(source.resource_id)
+        inputs.append({'source_id': source.resource_id, 'scope_dir': scope,
+            'document_kind': kind, **normalized})
+    return SupportingConsumerResult(tuple(consumed), tuple(inputs),
+        tuple(diagnostics))
```

Apply the single lexical owner extraction to
`lib/context/business_domain_adapters/rules.py`:

```diff
-def candidates(unit, receiver, name, available, position=None):
+def lexical_candidates(unit, receiver, name, available):
     if receiver:
         declared_types = set()
         for match in unit.source.rule_outputs:
             metadata = match.attributes
             if match.output_type != 'receiver_binding':
                 continue
             if capture(match, metadata.get('receiver_var')) != receiver:
                 continue
             start, end = span(unit.source, match)
             enclosing = sorted((candidate for candidate in unit.source.units
                 if candidate.start <= start and end <= candidate.end),
                 key=lambda candidate: candidate.end - candidate.start)
             if (not enclosing or not
                     (enclosing[0].start <= unit.start
                      and unit.end <= enclosing[0].end)):
                 continue
             declared = capture(match, metadata.get('type_var'))
             if declared:
                 declared_types.add(declared)
         return [candidate for candidate in available
                 if candidate.owner in declared_types]
     scopes = [unit.name, unit.owner]
     enclosing = sorted([candidate for candidate in unit.source.units
         if candidate.start < unit.start and unit.end <= candidate.end],
         key=lambda candidate: candidate.end - candidate.start)
     scopes.extend(candidate.owner for candidate in enclosing)
     for owner in scopes:
         candidates = [candidate for candidate in available
             if candidate.source.path == unit.source.path
             and candidate.owner == owner]
         if candidates:
             return candidates
+    return []
+
+
+def candidates(unit, receiver, name, available, position=None):
+    lexical = lexical_candidates(unit, receiver, name, available)
+    if lexical:
+        return lexical
     imported = getattr(unit.source, 'resolved_call_targets', {}).get(
         (unit.start + position, name)) if position is not None else None
     if imported:
         return [imported]
     return []
```

Apply the module-resolution sink to
`lib/context/business_domain_adapters/ts_semantic.py`:

```diff
+from types import MappingProxyType
+from ..layer1_domain_clustering import resolve_typescript_path_alias
+
+
 def prepare(sources, units, diagnostics=None):
+    source_paths = tuple(sorted(source.path for source in sources))
     for source in sources:
+        selected = source.supporting_inputs.get(
+            'typescript_module_resolution', {})
+        tsconfig = selected.get('tsconfig', {})
+        typings = selected.get('typings', {})
+        aliases = tsconfig.get('aliases', ())
+        external = {item['name']
+            for item in typings.get('declared_external_modules', ())}
+        resolved = {}
+        for module in _modules(source):
+            result = resolve_typescript_path_alias(
+                module, tsconfig.get('scope_dir', '.'), aliases, source_paths)
+            if result['state'] == 'unmatched':
+                if module not in external:
+                    continue
+                state = 'external'
+            else:
+                state = result['state']
+            if state == 'unresolved' and module in external:
+                state = 'external'
+            resolved[module] = MappingProxyType({
+                'state': state,
+                'candidate_source_paths': tuple(result['candidates']),
+                'external': state == 'external',
+            })
+        source.resolved_module_targets = MappingProxyType(resolved)
+    rules.prepare(sources, units, diagnostics)
+    for source in sources:
+        source.external_import_boundaries = _external_import_boundaries(source)
+
+
 def _external_import_boundaries(source):
     bindings = rules._import_bindings(source)
     boundaries = {}
     for reference in source.references:
         if reference.kind != 'call' or not reference.callee_name:
             continue
         root = rules._receiver_root(reference)
         module = bindings.get(root)
         if not module or module.startswith(('.', '/')):
             continue
+        target = source.resolved_module_targets.get(module)
+        if target is not None and target['state'] != 'external':
             continue
         start, _ = rules.span(source, {'range': reference.source_range})
         if (start, reference.callee_name) in getattr(
                 source, 'resolved_call_targets', {}):
             continue
         boundaries[(start, reference.callee_name)] = (module,
             f'{reference.callee_name} is reached through {root}, imported '
             f'from external module {module}.')
     return boundaries
+
+
 def candidates(unit, receiver, name, available, position=None):
-    return rules.candidates(unit, receiver, name, available, position)
+    lexical = rules.lexical_candidates(unit, receiver, name, available)
+    if lexical:
+        return lexical
+    bindings = rules._import_bindings(unit.source)
+    bound = receiver.split('.', 1)[0] if receiver else name
+    module = bindings.get(bound)
+    target = unit.source.resolved_module_targets.get(module)
+    if target is None:
+        return rules.candidates(unit, receiver, name, available, position)
+    if target['state'] in {'resolved', 'ambiguous'}:
+        paths = set(target['candidate_source_paths'])
+        return sorted((candidate for candidate in available
+            if candidate.source.path in paths),
+            key=lambda candidate: candidate.qualified)
+    return []
```

### Decode Java annotation literals and link Spring conditions

Apply these additions in
`lib/context/business_domain_adapters/java_semantic.py`:

```diff
+class JavaLiteralError(ValueError):
+    def __init__(self, cause: str, start: int, end: int):
+        super().__init__(cause)
+        self.cause, self.start, self.end = cause, start, end
+
+
+def _annotation_arguments(source, annotation):
+    arguments = next(_children(annotation, {'annotation_argument_list'}), None)
+    if arguments is None:
+        return []
+    result = []
+    for child in _children(arguments):
+        if child.type == 'element_value_pair':
+            key = child.child_by_field_name('key')
+            value = child.child_by_field_name('value')
+            name = _text(source, key) if key is not None else ''
+        else:
+            name, value = 'value', child
+        values = (list(_children(value))
+            if value is not None and value.type == 'element_value_array_initializer'
+            else [value])
+        for item in values:
+            if item is not None:
+                result.append({'name': name, 'expression': _text(source, item),
+                    'start': _char(source, item.start_byte),
+                    'end': _char(source, item.end_byte)})
+    return result
+
+
+def _unicode_translate_java(token: str):
+    translated, spans = [], []
+    cursor = 0
+    translated_backslash_run = 0
+    last_raw_character_was_unicode_escape = False
+    while cursor < len(token):
+        eligible = (token[cursor] == '\\' and
+            (last_raw_character_was_unicode_escape
+             or translated_backslash_run % 2 == 0))
+        if eligible:
+            probe = cursor + 1
+            while probe < len(token) and token[probe] == 'u':
+                probe += 1
+            if probe > cursor + 1 and probe + 4 <= len(token) \
+                    and re.fullmatch(r'[0-9a-fA-F]{4}', token[probe:probe + 4]):
+                character = chr(int(token[probe:probe + 4], 16))
+                translated.append(character)
+                spans.append((cursor, probe + 4))
+                cursor = probe + 4
+                translated_backslash_run = (
+                    translated_backslash_run + 1
+                    if character == '\\' else 0)
+                last_raw_character_was_unicode_escape = True
+                continue
+        character = token[cursor]
+        translated.append(character)
+        spans.append((cursor, cursor + 1))
+        cursor += 1
+        translated_backslash_run = (translated_backslash_run + 1
+            if character == '\\' else 0)
+        last_raw_character_was_unicode_escape = False
+    return ''.join(translated), tuple(spans)
+
+
+def _literal_error(cause, spans, start, end):
+    if start < len(spans):
+        raw_start = spans[start][0]
+        raw_end = spans[min(max(start, end - 1), len(spans) - 1)][1]
+    else:
+        raw_start = raw_end = spans[-1][1] if spans else 0
+    raise JavaLiteralError(cause, raw_start, raw_end)
+
+
+def _decode_java_string_literal(token: str) -> str:
+    translated, spans = _unicode_translate_java(token)
+    if (len(translated) < 2 or translated[0] != '"' or translated[-1] != '"'
+            or translated.startswith('"""') or '\r' in translated
+            or '\n' in translated):
+        _literal_error('ordinary_string_literal_required', spans, 0,
+            len(translated))
+    result, cursor, end = [], 1, len(translated) - 1
+    escapes = {'b': '\b', 't': '\t', 'n': '\n', 'f': '\f', 'r': '\r',
+        's': ' ', '"': '"', "'": "'", '\\': '\\'}
+    while cursor < end:
+        char = translated[cursor]
+        if char == '"':
+            _literal_error('unescaped_quote', spans, cursor, cursor + 1)
+        if char != '\\':
+            codepoint, finish = ord(char), cursor + 1
+        else:
+            if cursor + 1 >= end:
+                _literal_error('truncated_escape', spans, cursor, cursor + 1)
+            escaped = translated[cursor + 1]
+            if escaped in escapes:
+                result.append(escapes[escaped])
+                cursor += 2
+                continue
+            if escaped in '01234567':
+                maximum = 3 if escaped in '0123' else 2
+                finish = cursor + 2
+                while finish < end and finish < cursor + 1 + maximum \
+                        and translated[finish] in '01234567':
+                    finish += 1
+                result.append(chr(int(translated[cursor + 1:finish], 8)))
+                cursor = finish
+                continue
+            _literal_error('invalid_escape', spans, cursor, cursor + 2)
+        if 0xD800 <= codepoint <= 0xDBFF:
+            if finish >= end:
+                _literal_error('lone_high_surrogate', spans, cursor, finish)
+            low = ord(translated[finish])
+            if not 0xDC00 <= low <= 0xDFFF:
+                _literal_error('invalid_surrogate_pair', spans, finish, finish + 1)
+            result.append(chr(0x10000 + ((codepoint - 0xD800) << 10)
+                              + low - 0xDC00))
+            cursor = finish + 1
+            continue
+        if 0xDC00 <= codepoint <= 0xDFFF:
+            _literal_error('lone_low_surrogate', spans, cursor, finish)
+        result.append(chr(codepoint))
+        cursor = finish
+    return ''.join(result)
```

Extend the existing annotation record and activation evidence:

```diff
             result.append({
                 "name": _text(source, name).rsplit(".", 1)[-1] if name else "",
+                "qualified_name": _text(source, name) if name else "",
                 "text": _text(source, annotation),
                 "start": _char(source, annotation.start_byte),
                 "end": _char(source, annotation.end_byte),
+                "arguments": _annotation_arguments(source, annotation),
             })
 def activation_evidence(source):
     semantic = getattr(source, "semantic", {})
     return {
         "imports": sorted({*semantic.get("imports", {}).values(),
                            *semantic.get("wildcards", [])}),
-        "annotations": sorted({annotation["name"]
+        "annotations": sorted({value
             for item in semantic.get("types", []) + semantic.get("methods", [])
-            for annotation in item.get("annotations", [])}),
+            for annotation in item.get("annotations", [])
+            for value in (annotation["name"], annotation["qualified_name"])}),
     }
```

Replace the observation alias with the installed hook:

```diff
-observations = rules.observations
+def observations(unit):
+    return [*rules.observations(unit),
+            *getattr(unit, 'configuration_observations', ())]
```

Add this condition normalizer to
`lib/context/business_domain_adapters/spring_semantic.py`. Preserve the endpoint
body and splice the property-condition result into its exact entry and exit:

```diff
+import json
+
+from . import java_semantic
+
+_CONDITIONAL_ON_PROPERTY_FQN = (
+    'org.springframework.boot.autoconfigure.condition.ConditionalOnProperty')
+_CONDITIONAL_ON_PROPERTY_PACKAGE = (
+    'org.springframework.boot.autoconfigure.condition')
+_CONDITION_REASON = (
+    'Repository declarations were linked; effective deployment precedence '
+    'was not evaluated.')
+
+
+class _ConditionError(ValueError):
+    def __init__(self, cause, start, end):
+        super().__init__(cause)
+        self.cause, self.start, self.end = cause, start, end
+
+
+def _string(argument):
+    try:
+        return java_semantic._decode_java_string_literal(argument['expression'])
+    except java_semantic.JavaLiteralError as error:
+        raise _ConditionError(error.cause,
+            argument['start'] + error.start,
+            argument['start'] + error.end) from None
+
+
+def _scope_for_java(path):
+    parts = tuple(path.split('/'))
+    for index in range(len(parts) - 2):
+        if parts[index:index + 3] == ('src', 'main', 'java'):
+            return 'main'
+        if parts[index:index + 3] == ('src', 'test', 'java'):
+            return 'test'
+    return None
+
+
+def _condition_expression(key, having_value, match_if_missing):
+    quoted_key = json.dumps(key, ensure_ascii=False, separators=(',', ':'))
+    if having_value is None:
+        expression = f'property[{quoted_key}] is present and not false'
+    else:
+        quoted_value = json.dumps(having_value, ensure_ascii=False,
+                                  separators=(',', ':'))
+        expression = f'property[{quoted_key}] == {quoted_value}'
+    return expression + (' or missing' if match_if_missing else '')
+
+
+def _condition_redaction_candidates(annotation):
+    grouped = {}
+    for argument in annotation['arguments']:
+        grouped.setdefault(argument['name'], []).append(argument)
+    decoded_names, unknown_key_component = [], False
+    for argument in (*grouped.get('name', ()), *grouped.get('value', ())):
+        try:
+            decoded_names.append(_string(argument))
+        except _ConditionError:
+            unknown_key_component = True
+    decoded_prefixes = []
+    for argument in grouped.get('prefix', ()):
+        try:
+            decoded_prefixes.append(_string(argument))
+        except _ConditionError:
+            unknown_key_component = True
+    prefixes = decoded_prefixes or ['']
+    keys = [prefix + ('.' if prefix and not prefix.endswith('.') else '') + name
+        for prefix in prefixes for name in decoded_names]
+    keys_or_unknown = [*keys,
+        *([None] if unknown_key_component or not keys else [])]
+    return tuple((key, argument['start'], argument['end'])
+        for key in keys_or_unknown
+        for argument in grouped.get('havingValue', ()))
+
+
+def _property_condition(annotation):
+    grouped = {}
+    for argument in annotation['arguments']:
+        grouped.setdefault(argument['name'], []).append(argument)
+    if set(grouped) - {'name', 'value', 'prefix', 'havingValue',
+                       'matchIfMissing'}:
+        raise ValueError('unsupported_conditional_property_argument')
+    names = grouped.get('name', [])
+    values = grouped.get('value', [])
+    if bool(names) == bool(values):
+        raise ValueError('exactly_one_of_name_or_value_is_required')
+    for scalar in ('prefix', 'havingValue', 'matchIfMissing'):
+        if len(grouped.get(scalar, [])) > 1:
+            raise ValueError(f'{scalar}_must_not_repeat')
+    decoded_names = [_string(item) for item in (names or values)]
+    prefix = (_string(grouped['prefix'][0])
+        if grouped.get('prefix') else '')
+    having_value = (_string(grouped['havingValue'][0])
+        if grouped.get('havingValue') else None)
+    value_spans = (((grouped['havingValue'][0]['start'],
+                     grouped['havingValue'][0]['end']),)
+        if grouped.get('havingValue') else ())
+    match_if_missing = False
+    if grouped.get('matchIfMissing'):
+        literal = grouped['matchIfMissing'][0]['expression']
+        if literal not in {'true', 'false'}:
+            raise ValueError('matchIfMissing_must_be_boolean_literal')
+        match_if_missing = literal == 'true'
+    separator = '.' if prefix and not prefix.endswith('.') else ''
+    return ([prefix + separator + name for name in decoded_names],
+        having_value, match_if_missing, value_spans)
+
+
+def _condition_units(sources):
+    for source in sources:
+        semantic = getattr(source, 'semantic', {})
+        for owner in semantic.get('types', []):
+            yield owner['unit'], owner.get('annotations', [])
+            for method in owner.get('methods', []):
+                yield method['unit'], method.get('annotations', [])
+
+
+def _is_condition_annotation(source, annotation):
+    qualified = annotation['qualified_name']
+    if qualified == _CONDITIONAL_ON_PROPERTY_FQN:
+        return True
+    if qualified != 'ConditionalOnProperty':
+        return False
+    semantic = getattr(source, 'semantic', {})
+    return (semantic.get('imports', {}).get('ConditionalOnProperty')
+            == _CONDITIONAL_ON_PROPERTY_FQN
+        or _CONDITIONAL_ON_PROPERTY_PACKAGE in semantic.get('wildcards', ()))
+
+
+def _prepare_property_conditions(sources, units):
+    pending = []
+    declarations = [unit for unit in units
+        if unit.configuration is not None
+        and unit.configuration.role == 'application_configuration'
+        and unit.configuration.profile is None]
+    for consumer, annotations in _condition_units(sources):
+        environment = _scope_for_java(consumer.source.path)
+        if environment is None:
+            continue
+        observations = getattr(consumer, 'configuration_observations', None)
+        if observations is None:
+            observations = []
+            consumer.configuration_observations = observations
+        ordinal = 0
+        for annotation in annotations:
+            if not _is_condition_annotation(consumer.source, annotation):
+                continue
+            redaction_candidates = _condition_redaction_candidates(annotation)
+            try:
+                (keys, having_value, match_if_missing,
+                 value_spans) = _property_condition(annotation)
+            except _ConditionError as error:
+                pending.append({'source_id': consumer.source.resource_id,
+                    'code': 'SPRING_PROPERTY_CONDITION_UNAVAILABLE',
+                    'reason': error.cause, 'span': (error.start, error.end),
+                    'named_value_spans': redaction_candidates})
+                continue
+            except ValueError as error:
+                pending.append({'source_id': consumer.source.resource_id,
+                    'code': 'SPRING_PROPERTY_CONDITION_UNAVAILABLE',
+                    'reason': str(error),
+                    'span': (annotation['start'], annotation['end']),
+                    'named_value_spans': redaction_candidates})
+                continue
+            for key in keys:
+                allowed = {'main'} if environment == 'main' else {'main', 'test'}
+                candidates = tuple(unit for unit in declarations
+                    if unit.configuration.key == key
+                    and unit.configuration.environment in allowed)
+                if not candidates:
+                    pending.append({'source_id': consumer.source.resource_id,
+                        'code': 'SPRING_PROPERTY_CONDITION_UNAVAILABLE',
+                        'reason': 'matching_repository_declaration_unavailable',
+                        'span': (annotation['start'], annotation['end']),
+                        'named_value_spans': redaction_candidates})
+                observations.append(
+                    {'identity_key': f'configuration:{key}:{ordinal}',
+                     'source_location_kind': 'configuration',
+                     'native_expression': _condition_expression(
+                         key, having_value, match_if_missing),
+                     'declaration_units': candidates,
+                     'binding_name': key, 'binding_direction': 'internal',
+                     'span': (annotation['start'] - consumer.start,
+                              annotation['end'] - consumer.start),
+                     'scope': {'environment': environment, 'tenant': None,
+                            'actor': None, 'profile': None,
+                            'effective_from': None, 'effective_to': None,
+                            'version': None, 'entrypoint_ids': None},
+                     'resolution': 'unresolved', 'reason': _CONDITION_REASON,
+                     'named_value_spans': tuple((key, start, end)
+                         for start, end in value_spans)})
+                ordinal += 1
+    return pending
+
+
 def prepare(sources, units, diagnostics=None):
     diagnostics = diagnostics if diagnostics is not None else []
+    pending = _prepare_property_conditions(sources, units)
     all_types = [item for source in sources for item in getattr(source, "semantic", {}).get("types", [])]
 @@
             if unresolved:
                 diagnostics.append({"code": "SPRING_CONTRACT_DECLARATION_UNAVAILABLE",
                     "message": "Controller contract source is unavailable; inherited endpoint mappings remain unresolved.",
                     "subject_ids": [source.resource_id], "evidence_ids": []})
+    return pending
```

### Project redaction, bindings, supporting inputs and warnings

Apply these core helpers to `lib/context/business_domain_extract.py`:

```diff
-def redacted(text: str) -> str:
-    # Keep line count and keys; do not send literal credentials in evidence.
-    return re.sub(r'(?im)((?:password|secret|api[_-]?key|access[_-]?token)["\']?\s*[=:]\s*["\']?)[^\s"\',;]+', r'\1[REDACTED]', text)
-
-
+_ASSIGNMENT_RE = re.compile(
+    r'(?m)^([ \t\f]*([^=:\s]+)[ \t\f]*(?:=|:)[ \t\f]*)([^\r\n]*)')
+_JSON_ASSIGNMENT_RE = re.compile(
+    r'(?m)("(?:\\.|[^"\\])+")([ \t\f]*:[ \t\f]*)'
+    r'("(?:\\.|[^"\\])*"|[^,{}\[\]\r\n]+)')
+_JSON_KEY_RE = re.compile(
+    r'("(?:\\.|[^"\\])+")[ \t\f\r\n]*:[ \t\f\r\n]*')
+_INLINE_ASSIGNMENT_PREFIX_RE = re.compile(
+    r'(?i)(["\']?)([A-Za-z0-9_.-]+)\1([ \t\f]*[=:][ \t\f]*)')
+
+
+def _redact_assignment(match):
+    return (match.group(1) + '[REDACTED]'
+        if _sensitive_name(match.group(2)) else match.group(0))
+
+
+def _redact_json_assignment(match):
+    try:
+        name = json.loads(match.group(1))
+    except (json.JSONDecodeError, TypeError):
+        return match.group(0)
+    return (match.group(1) + match.group(2) + '"[REDACTED]"'
+            if _sensitive_name(name) else match.group(0))
+
+
+def _redact_inline_assignments(text):
+    spans = []
+    for match in _INLINE_ASSIGNMENT_PREFIX_RE.finditer(text):
+        if not _sensitive_name(match.group(2)):
+            continue
+        start = match.end()
+        if text.startswith('[REDACTED]', start):
+            continue
+        line_end = len(text)
+        for terminator in ('\r', '\n'):
+            found = text.find(terminator, start)
+            if found >= 0:
+                line_end = min(line_end, found)
+        quote = text[start:start + 1]
+        if quote in {'"', "'"}:
+            cursor, escaped = start + 1, False
+            while cursor < line_end:
+                character = text[cursor]
+                if character == quote and not escaped:
+                    break
+                escaped = character == '\\' and not escaped
+                if character != '\\':
+                    escaped = False
+                cursor += 1
+            value_start, value_end = start + 1, cursor
+        else:
+            value_start, value_end = start, line_end
+        spans.append((value_start, value_end))
+    selected = []
+    for start, end in sorted(spans):
+        if any(parent_start <= start and end <= parent_end
+               for parent_start, parent_end in selected):
+            continue
+        selected.append((start, end))
+    for start, end in reversed(selected):
+        text = text[:start] + '[REDACTED]' + text[end:]
+    return text
+
+
+def _redact_json_members(text):
+    spans = []
+    decoder = json.JSONDecoder()
+    for match in _JSON_KEY_RE.finditer(text):
+        try:
+            name = json.loads(match.group(1))
+        except (json.JSONDecodeError, TypeError):
+            continue
+        if not _sensitive_name(name):
+            continue
+        start = match.end()
+        try:
+            _value, end = decoder.raw_decode(text, start)
+        except json.JSONDecodeError:
+            continue
+        spans.append((start, end))
+    non_overlapping = []
+    for start, end in sorted(spans):
+        if any(parent_start <= start and end <= parent_end
+               for parent_start, parent_end in non_overlapping):
+            continue
+        non_overlapping.append((start, end))
+    for start, end in reversed(non_overlapping):
+        replacement = '"[REDACTED]"' + ('\n' * text[start:end].count('\n'))
+        text = text[:start] + replacement + text[end:]
+    return text
+
+
+def redacted(text: str) -> str:
+    text = _redact_json_members(text)
+    text = _JSON_ASSIGNMENT_RE.sub(_redact_json_assignment, text)
+    text = _ASSIGNMENT_RE.sub(_redact_assignment, text)
+    return _redact_inline_assignments(text)
+
+
+def redact_named_value(name, value):
+    return '[REDACTED]' if isinstance(name, str) and _sensitive_name(name) \
+        else redacted(value) if isinstance(value, str) else redact_values(value)
+
+
 def redact_values(value):
     if isinstance(value, str):
         return redacted(value)
     if isinstance(value, list):
         return [redact_values(item) for item in value]
     if isinstance(value, dict):
-        return {key:redact_values(item) for key,item in value.items()}
+        result = dict(value)
+        name_key = next((key for key in ('name', 'key') if key in value), None)
+        value_key = next((key for key in ('expression', 'value') if key in value), None)
+        if name_key is not None and value_key is not None:
+            result[value_key] = redact_named_value(value[name_key], value[value_key])
+        return {key: (item if key == value_key else redact_values(item))
+            for key, item in result.items()}
     return value
+
+
+def binding_id(unit, name, direction):
+    return identifier('binding', unit.symbol_id, name, direction)
```

Replace the first line of `Extractor.evidence()` so decoder failures and
recorded spans are redacted before any snapshot or evidence hash is created:

```diff
-        excerpt=redacted(source.text[start:end]);sid=identifier('snapshot',source.path,source.source_hash,start,end)
+        if source.evidence_redaction_required:
+            excerpt = '[REDACTED]'
+        else:
+            excerpt = source.text[start:end]
+            intersections = [(max(span_start, start) - start,
+                              min(span_end, end) - start)
+                for span_start, span_end in source.redaction_spans
+                if span_start < end and start < span_end]
+            for local_start, local_end in reversed(intersections):
+                excerpt = excerpt[:local_start] + '[REDACTED]' + excerpt[local_end:]
+            excerpt = redacted(excerpt)
+        sid=identifier('snapshot',source.path,source.source_hash,start,end)
```

After `load_selection()` returns a successful analyze execution, call
`_register_redaction_spans(execution.output)`. In `add_unit()`, replace the
adapter lookup and duplicated binding identity:

```diff
-        for binding in adapter_for(unit.source).bindings(unit):
+        owner = self._owner(unit.source)
+        for binding in owner.bindings(unit) if owner else ():
             binding = redact_values(binding)
             position = binding.pop('position', None)
             end = binding.pop('end', None)
             if (position is None) != (end is None) or (position is not None and (
                     type(position) is not int or type(end) is not int
                     or not 0 <= position < end <= len(unit.text))):
                 raise ValueError(
                     'Adapter binding requires a valid unit-relative span')
             evidence_id = (unit.evidence_id if position is None else
                 self.evidence(unit.source, unit.start + position,
                               unit.start + end))
-            bid=identifier('binding',unit.symbol_id,binding['name'],binding['direction'])
+            bid=binding_id(unit,binding['name'],binding['direction'])
             self.facts['bindings'][bid] = record('Binding', id=bid,
                 source={'kind': 'symbol', 'id': unit.symbol_id},
                 target={'kind': 'symbol', 'id': unit.symbol_id},
                 evidence_ids=[evidence_id], **binding)
```

Supporting results are validated completely before any source is mutated:

```diff
+def _freeze_runtime(value):
+    if isinstance(value, dict):
+        return MappingProxyType({key: _freeze_runtime(item)
+            for key, item in value.items()})
+    if isinstance(value, (list, tuple)):
+        return tuple(_freeze_runtime(item) for item in value)
+    return value
+
+
+def _runtime_value_is_valid(value):
+    if value is None or type(value) in {bool, int, float, str}:
+        return not isinstance(value, float) or math.isfinite(value)
+    if isinstance(value, (list, tuple)):
+        return all(_runtime_value_is_valid(item) for item in value)
+    if isinstance(value, dict):
+        return (all(isinstance(key, str) for key in value)
+            and all(_runtime_value_is_valid(item) for item in value.values()))
+    return False
+
+
+    def _run_supporting_consumers(self):
+        grouped = {}
+        for execution in self.executions_by_source_id.values():
+            if execution.selection.route.disposition == 'supporting' \
+                    and execution.state == 'resolved':
+                owner_id = execution.selection.selected_descriptor['id']
+                grouped.setdefault(owner_id, []).append(execution)
+        for owner_id, executions in sorted(grouped.items()):
+            descriptor = executions[0].selection.selected_descriptor
+            module = executions[0].loaded_owner
+            consume = getattr(module, descriptor['function'], None)
+            if not callable(consume):
+                for execution in executions:
+                    execution.state = 'unresolved'
+                    execution.cause = 'owner_execution_failed'
+                continue
+            sources = tuple(item.source for item in executions)
+            primary_sources = tuple(execution.source for execution
+                in self.executions_by_source_id.values()
+                if execution.selection.route.disposition == 'analyze'
+                and execution.state == 'resolved')
+            try:
+                result = consume(sources, primary_sources)
+            except Exception:
+                for execution in executions:
+                    execution.state = 'unresolved'
+                    execution.cause = 'owner_execution_failed'
+                continue
+            try:
+                if not isinstance(result, SupportingConsumerResult):
+                    raise TypeError('supporting_result_invalid')
+                expected = {source.resource_id for source in sources}
+                if (not all(isinstance(item, str)
+                            for item in result.consumed_source_ids)
+                        or not all(isinstance(item, dict)
+                                   for item in result.diagnostics)
+                        or not all(isinstance(item, dict)
+                                   for item in result.normalized_inputs)):
+                    raise TypeError('supporting_result_element_invalid')
+                if not all(_runtime_value_is_valid(item)
+                           for item in result.normalized_inputs):
+                    raise TypeError('supporting_input_value_invalid')
+                consumed = list(result.consumed_source_ids)
+                diagnosed = [item.get('source_id') for item in result.diagnostics]
+                if (len(consumed) != len(set(consumed))
+                        or len(diagnosed) != len(set(diagnosed))
+                        or set(consumed) & set(diagnosed)
+                        or set(consumed) | set(diagnosed) != expected
+                        or any(item.get('source_id') not in expected
+                               for item in result.diagnostics)):
+                    raise ValueError('supporting_consumption_invalid')
+                diagnostic_plan = tuple((item,
+                    self._validate_adapter_diagnostic(descriptor, item))
+                    for item in result.diagnostics)
+                if any(not {'source_id', 'scope_dir', 'document_kind'} <= set(item)
+                       or not all(isinstance(item[key], str) and item[key]
+                                  for key in ('source_id', 'scope_dir',
+                                              'document_kind'))
+                       for item in result.normalized_inputs):
+                    raise ValueError('supporting_input_shape_invalid')
+                normalized_ids = [item.get('source_id')
+                    for item in result.normalized_inputs]
+                if (len(normalized_ids) != len(set(normalized_ids))
+                        or set(normalized_ids) != set(consumed)):
+                    raise ValueError('supporting_inputs_invalid')
+                assignment_plan = self._supporting_assignment_plan(
+                    owner_id, result.normalized_inputs, primary_sources)
+            except Exception:
+                for execution in executions:
+                    execution.state = 'unresolved'
+                    execution.cause = 'consumer_contract_invalid'
+                continue
+            by_id = {execution.source.resource_id: execution
+                for execution in executions}
+            for diagnostic, source in diagnostic_plan:
+                by_id[source.resource_id].diagnostics.append(diagnostic)
+                by_id[source.resource_id].state = 'unresolved'
+                self._project_adapter_diagnostic(
+                    descriptor, diagnostic, source)
+            for source, selected in assignment_plan:
+                current = dict(source.supporting_inputs)
+                current[owner_id] = _freeze_runtime(selected)
+                source.supporting_inputs = MappingProxyType(current)
+
+    def _supporting_assignment_plan(self, owner_id, records, primary_sources):
+        del owner_id
+        by_kind = {}
+        for record in records:
+            by_kind.setdefault(record['document_kind'], []).append(record)
+        plan = []
+        for source in primary_sources:
+            selected = {}
+            source_parts = PurePosixPath(source.path).parts[:-1]
+            for kind, candidates in by_kind.items():
+                compatible = []
+                for record in candidates:
+                    scope = () if record['scope_dir'] == '.' else tuple(
+                        PurePosixPath(record['scope_dir']).parts)
+                    if source_parts[:len(scope)] == scope:
+                        compatible.append((len(scope), record))
+                if not compatible:
+                    continue
+                depth = max(item[0] for item in compatible)
+                winners = [item[1] for item in compatible if item[0] == depth]
+                if len(winners) != 1:
+                    raise ValueError('supporting_scope_ambiguous')
+                selected[kind] = winners[0]
+            if selected:
+                plan.append((source, selected))
+        return tuple(plan)
```

Extend the existing dictionary-observation projector rather than adding a
second observation type or branch. Ordinary observations omit the optional
projection fields and retain their current behavior:

```diff
             for observation in adapter.observations(unit):
+                if not isinstance(observation, dict):
+                    raise DomainError('INVALID_ADAPTER_CONTRACT',
+                        'adapter_observation_invalid')
+                observation = dict(observation)
+                named_spans = observation.pop('named_value_spans', ())
+                _register_named_value_spans(unit.source, named_spans)
+                projection_fields = {
+                    'declaration_units', 'binding_name', 'binding_direction'}
+                present_projection_fields = projection_fields & set(observation)
+                if (present_projection_fields
+                        and present_projection_fields != projection_fields):
+                    raise DomainError('INVALID_ADAPTER_CONTRACT',
+                        'observation_binding_projection_incomplete')
+                has_binding_projection = bool(present_projection_fields)
+                declarations = observation.pop('declaration_units', ())
+                binding_name = observation.pop('binding_name', None)
+                binding_direction = observation.pop('binding_direction', None)
+                identity_key = observation.pop('identity_key', None)
+                if (has_binding_projection
+                        and (not isinstance(declarations, tuple)
+                             or not all(isinstance(item, Unit)
+                                        for item in declarations)
+                             or not isinstance(binding_name, str)
+                             or binding_direction != 'internal')):
+                    raise DomainError('INVALID_ADAPTER_CONTRACT',
+                        'observation_binding_projection_invalid')
+                if has_binding_projection:
+                    observation['native_expression'] = redact_named_value(
+                        binding_name, observation.get('native_expression'))
                 observation = redact_values(observation)
                 start, end = observation.pop('span')
                 eid = self.evidence(unit.source, unit.start+start, unit.start+end)
+                evidence_ids, binding_ids = {eid}, []
+                if has_binding_projection:
+                    for declaration in declarations:
+                        candidate = binding_id(
+                            declaration, binding_name, binding_direction)
+                        binding = self.facts['bindings'].get(candidate)
+                        if binding is None or not binding['evidence_ids']:
+                            raise DomainError('INVALID_ADAPTER_CONTRACT',
+                                'observation_binding_missing')
+                        binding_ids.append(candidate)
+                        evidence_ids.update(binding['evidence_ids'])
                 resource = observation.pop('resource',None)
                 if resource:
                     rid = identifier('resource',resource['kind'],resource['name'].casefold())
                     self.facts['resources'].setdefault(rid,record('Resource',id=rid,evidence_ids=[eid],**resource))
                     observation.setdefault('dependency_ids',[]).append(rid)
-                oid = identifier('observation', unit.symbol_id, start)
+                oid = identifier('observation', unit.symbol_id,
+                    identity_key if identity_key is not None else start)
                 self.facts['rule_observations'][oid] = record('RuleObservation', id=oid,
-                    evidence_ids=[eid], **{'resolution':'unresolved',
+                    input_binding_ids=sorted(binding_ids),
+                    evidence_ids=sorted(evidence_ids), **{'resolution':'unresolved',
                     'reason':'Condition observed; outcome and enforcement scope require trace interpretation.',
                     **observation})
```

Blocking failures use one deterministic projector:

```diff
+_LOST_FACTS = {
+    'parsing': ('evidence',),
+    'declaration_extraction': ('symbols',),
+    'bindings': ('bindings',),
+    'runtime_selection': ('framework_activation',),
+    'type_resolution': ('module_relationships', 'type_relationships'),
+}
+
+
+    def _blocking_source_diagnostic(self, execution):
+        selection, route, source = (execution.selection,
+            execution.selection.route, execution.source)
+        cause = execution.cause
+        code = ('AMBIGUOUS_ADAPTER'
+                if cause in {'ambiguous_language', 'multiple_owners'} else
+                'SOURCE_CAPABILITY_UNAVAILABLE'
+                if cause == 'owner_not_installed' else 'ADAPTER_UNAVAILABLE')
+        lost = sorted({fact for capability in route.required_capabilities
+            for fact in _LOST_FACTS[capability]})
+        language = route.classification.language or 'null'
+        owner = route.expected_owner or 'null'
+        required = ','.join(route.required_capabilities)
+        candidates = ','.join(selection.candidate_owner_ids)
+        message = (f'{source.path}: language={language}; '
+            f'disposition={route.disposition}; required=[{required}]; '
+            f'owner={owner}; candidates=[{candidates}]; cause={cause}; '
+            f'lost_facts=[{",".join(lost)}].')
+        evidence_id = self.evidence(source, 0, min(len(source.text), 4096))
+        self.diagnostics.append(record('Diagnostic', code=code,
+            message=message, subject_ids=[source.resource_id],
+            evidence_ids=[evidence_id]))
+        resource = self.facts['resources'][source.resource_id]
+        resource.update(resolution='unresolved', reason=message,
+            evidence_ids=[evidence_id])
+        unsupported = self.facts['coverage']['unsupported_source_ids']
+        if source.resource_id not in unsupported:
+            unsupported.append(source.resource_id)
```

Resource finalization invokes that helper exactly once for every execution with
a blocking cause; format diagnostics do not add unsupported IDs. Successful
supporting and analyze executions resolve only their own Resource. Reference
sources receive bounded evidence and remain unresolved with the installed
reason; ignored sources never get a Resource.

Use this exact finalizer after unit/diagnostic projection and before capability
aggregation:

```diff
+    def _finalize_source_resources(self):
+        format_codes = {'JAVA_PROPERTIES_SYNTAX_INVALID',
+            'PACKAGE_JSON_INVALID', 'TYPESCRIPT_MODULE_RESOLUTION_INVALID',
+            'SPRING_PROPERTY_CONDITION_UNAVAILABLE'}
+        for source in self.sources:
+            route = self.routes[source.path]
+            execution = self.executions_by_source_id[source.resource_id]
+            if execution.cause is not None:
+                self._blocking_source_diagnostic(execution)
+                continue
+            resource = self.facts['resources'][source.resource_id]
+            if route.disposition == 'reference_only':
+                evidence_id = self.evidence(source, 0, min(len(source.text), 4096))
+                resource.update(evidence_ids=[evidence_id], resolution='unresolved',
+                    reason=f'Reference-only {route.expected_owner}: retained for context; '
+                           'no business semantics were inferred.')
+                continue
+            evidence_ids = sorted({unit.evidence_id for unit in self.units
+                if unit.source is source and unit.evidence_id})
+            if not evidence_ids:
+                evidence_ids = [self.evidence(source, 0,
+                    min(len(source.text), 4096))]
+            has_format_error = any(diagnostic['code'] in format_codes
+                and source.resource_id in diagnostic.get('subject_ids', ())
+                for diagnostic in self.diagnostics)
+            resource.update(evidence_ids=evidence_ids,
+                resolution='unresolved' if has_format_error else 'resolved',
+                reason=('Selected source reported invalid input.'
+                        if has_format_error else None))
```

Call `_finalize_source_resources()` after `_observations()` so every declaration
and condition evidence ID already exists. It mutates no other source's state.

Replace `_capabilities()` with stored-descriptor projection:

```diff
-    def _capabilities(self) -> None:
-        """Materialize selected source capabilities before semantic tracing."""
-        capabilities = {}
-        for source in self.sources:
-            source.capability_statuses = {}
-            entry = descriptor(source)
-            selected = entry.get('capability') or {}
-            fallback_codes = ['ADAPTER_REGISTRY_INVALID'] if entry.get('registry_error') else ['SOURCE_CAPABILITY_UNAVAILABLE']
-            unavailable = {feature:'unsupported' for feature in SOURCE_ADAPTER_CAPABILITIES}
-            if source.adapter_failed:
-                selected = {**selected, 'capabilities': unavailable,
-                    'diagnostic_codes': sorted(set(selected.get('diagnostic_codes', [])) | {'ADAPTER_UNAVAILABLE'})}
-            providers = [selected]
-            adapter = None if source.adapter_failed else adapter_for(source)
-            if adapter:
-                evidence = getattr(adapter, 'activation_evidence', lambda _: {})(source)
-                providers.extend(enricher_descriptors(source, evidence))
-            for provider in providers:
-                for feature, status in provider.get('capabilities', unavailable).items():
-                    source.capability_statuses.setdefault(feature, set()).add(status)
-                    capability = record('Capability', language=source.language,
-                        framework=provider.get('framework'), version=provider.get('framework_version'),
-                        adapter=provider.get('id', 'unavailable'), adapter_version=provider.get('version', '1'),
-                        feature=feature, status=status,
-                        diagnostic_codes=provider.get('diagnostic_codes', fallback_codes))
-                    capabilities[digest(capability)] = capability
-        self.facts['capabilities'] = [capabilities[k] for k in sorted(capabilities)]
-
+    def _capabilities(self):
+        capabilities = {}
+        for source in self.sources:
+            route = self.routes[source.path]
+            if route.disposition == 'reference_only':
+                continue
+            execution = self.executions_by_source_id[source.resource_id]
+            descriptor = execution.selection.selected_descriptor
+            providers = []
+            if descriptor and route.disposition == 'supporting':
+                status = ('unsupported' if execution.cause else
+                          descriptor['capability_status'])
+                providers.append((descriptor, {
+                    feature: status for feature in descriptor['capabilities']}))
+            elif descriptor:
+                statuses = dict(descriptor['capabilities'])
+                if execution.cause:
+                    statuses = {feature: 'unsupported'
+                        for feature in SOURCE_ADAPTER_CAPABILITIES}
+                providers.append((descriptor, statuses))
+                providers.extend((enricher, dict(enricher['capabilities']))
+                    for enricher in self.enricher_descriptors_by_source_id.get(
+                        source.resource_id, ()))
+            else:
+                providers.append(({'id': 'unavailable', 'version': '1',
+                    'diagnostic_codes': [
+                        'AMBIGUOUS_ADAPTER' if execution.selection.status == 'ambiguous'
+                        else 'SOURCE_CAPABILITY_UNAVAILABLE']},
+                    {feature: 'unsupported'
+                     for feature in SOURCE_ADAPTER_CAPABILITIES}))
+            source.capability_statuses = {}
+            for provider, statuses in providers:
+                for feature, status in statuses.items():
+                    source.capability_statuses.setdefault(feature, set()).add(status)
+                    capability = record('Capability', language=source.language,
+                        framework=provider.get('framework'),
+                        version=provider.get('framework_version'),
+                        adapter=provider['id'],
+                        adapter_version=provider.get('version', '1'),
+                        feature=feature, status=status,
+                        diagnostic_codes=sorted(set(provider['diagnostic_codes']) |
+                            ({'ADAPTER_UNAVAILABLE'} if execution.cause else set())))
+                    capabilities[digest(capability)] = capability
+        self.facts['capabilities'] = [capabilities[key]
+            for key in sorted(capabilities)]
```

### Enforce coverage, cache and publication boundaries

Add this cross-record validator to `lib/context/business_domain_schema.py`:

```diff
+from collections import Counter
+
+_BLOCKING_SOURCE_CODES = {
+    'SOURCE_CAPABILITY_UNAVAILABLE', 'AMBIGUOUS_ADAPTER',
+    'ADAPTER_UNAVAILABLE',
+}
+
+
+def validate_source_warning_coverage(facts: dict) -> None:
+    resources = facts.get('resources', {})
+    all_unsupported = facts.get('coverage', {}).get(
+        'unsupported_source_ids', [])
+    if len(all_unsupported) != len(set(all_unsupported)):
+        raise DomainError('INVALID_ARTIFACT',
+            'Unsupported repository source IDs must be unique')
+    unsupported = [source_id for source_id in all_unsupported
+        if resources.get(source_id, {}).get('kind') == 'repository_file']
+    warning_subjects = []
+    for warning in facts.get('warnings', []):
+        if warning.get('code') not in _BLOCKING_SOURCE_CODES:
+            continue
+        subjects = warning.get('subject_ids', [])
+        evidence = warning.get('evidence_ids', [])
+        if (len(subjects) != 1 or len(evidence) != 1
+                or resources.get(subjects[0], {}).get('kind') != 'repository_file'):
+            raise DomainError('INVALID_ARTIFACT',
+                'Blocking source warnings require one repository-file subject and evidence')
+        warning_subjects.append(subjects[0])
+    if Counter(unsupported) != Counter(warning_subjects):
+        raise DomainError('INVALID_ARTIFACT',
+            'Unsupported repository sources and blocking warnings must correspond exactly')
```

Import the cross-record validator and replace the former inline extraction tail
with this complete method:

```diff
-from .business_domain_schema import (DEFAULTS, DomainError, account_artifact_bytes,
+from .business_domain_schema import (DEFAULTS, DomainError, account_artifact_bytes,
     atomic_write, digest, identifier, implementation_hash, limits, now, record,
-    validate, read_json)
+    validate, validate_source_warning_coverage, read_json)
 @@
+    def _finalize_artifact(self):
+        installed = Path(__file__).parent
+        fingerprint = dict(
+            sources=source_fingerprint(self.scan),
+            configuration=digest(self.config),
+            extractors=implementation_hash(
+                Path(__file__),
+                installed/'business_domain_adapters',
+                installed/'rules',
+                installed/'data',
+                installed/'language_registry.py',
+                installed/'treesitter_extract.py',
+                installed/'business_domain_schema.py',
+                installed/'business_domain_snapshots.py',
+                installed/'business_domain_identity.py',
+                installed/'business_domain_policies.json',
+                installed/'business_domain_reference_targets.json',
+                installed/'business_domain_artifacts.schema.json',
+                installed/'repository_digest_runtime.py',
+                installed/'layer1_domain_clustering.py'),
+            prompts=digest({}),
+            provider=digest({}),
+            overrides=digest({}),
+            snapshots=digest({'records': self.facts['source_snapshots'],
+                              'inputs': self.snapshot_inputs}))
+        fingerprint['value'] = digest(fingerprint)
+        self.facts['fingerprint'] = fingerprint
+        for blob, snapshot in self.snapshot_objects.items():
+            atomic_write(self.root/'.speed/context/business-domain-snapshots'/
+                         f'{blob}.json', snapshot)
+        account_artifact_bytes(self.facts)
+        validate_source_warning_coverage(self.facts)
+        validate(self.facts, 'FactsArtifact')
+        return self.facts, self.units
```

Replace the prepublication read/decode operation in
`lib/context/business_domains.py` with a raw scan:

```diff
-from .business_domain_extract import Extractor, inventory
+from .business_domain_extract import (Extractor, scan_inventory,
+    source_fingerprint)
 @@
-        current,_ = inventory(root,config)
-        if digest({s.path:s.source_hash for s in current}) != facts['fingerprint']['sources']:
+        current_scan = scan_inventory(root, config)
+        if source_fingerprint(current_scan) != facts['fingerprint']['sources']:
             raise DomainError('SUPERSEDED','Sources changed during discovery')
```

This supersession check performs no decoding, adapter loading,
supporting-consumer execution or provider call.

Apply this exact lifecycle clarification to
`specs/tech/contracts/business-domain-artifacts.md`:

```diff
-- Status phase and timestamps follow RFC transitions; failed/cancelled/unavailable attempts cannot replace the published domain model. Status freshness is recorded at the last explicit observation/build, not live source scanning on reads. Published build IDs link to retained model versions.
+- Status phase and timestamps follow RFC transitions. A failed, cancelled or unavailable refresh may write its attempt FactsArtifact and StatusArtifact and may add immutable snapshot blobs, but it cannot replace the prior validated DomainArtifact, published build ID, baseline or history. Status freshness is recorded at the last explicit observation/build, not live source scanning on reads. Published build IDs link to retained model versions.
```

## Files authorized for the production implementation

- `lib/context/language_registry.py`
- `lib/context/data/extraction.toml`
- `lib/context/project_map.py`
- `lib/context/business_domain_adapters/__init__.py`
- `lib/context/business_domain_adapters/base.py`
- `lib/context/business_domain_adapters/package_manifest.py` (new)
- `lib/context/business_domain_adapters/typescript_module_resolution.py` (new)
- `lib/context/business_domain_adapters/java_properties.py` (new)
- `lib/context/business_domain_adapters/java_semantic.py`
- `lib/context/business_domain_adapters/rules.py`
- `lib/context/business_domain_adapters/spring_semantic.py`
- `lib/context/business_domain_adapters/ts_semantic.py`
- `lib/context/business_domain_extract.py`
- `lib/context/business_domain_schema.py`
- `lib/context/repository_digest_runtime.py`
- `lib/context/layer1_domain_clustering.py`
- `lib/context/business_domains.py`
- `specs/tech/contracts/business-domain-artifacts.md`

Artifact JSON Schemas remain unchanged: the new route, selection, execution,
configuration and supporting-consumer records are internal extraction records;
diagnostics and observations retain their existing dictionary contracts.
Add the cross-record warning/coverage check to `business_domain_schema.py` and
update only the prose contract named above.

## Required tests

Exact test ownership:

| Behavior | Test file |
| --- | --- |
| Registry atomic load, extension owners, classifiers and rule/consumer validation | `tests/test_language_registry.py` (new) |
| Project-map/SVG agreement | `tests/test_unit_layer1.py` and `tests/test_business_domain_extract.py` |
| Adapter preservation and one selection/load | `tests/test_business_domain_adapter_conformance.py` |
| `rules.lexical_candidates()` parity and unchanged ordinary fallback | `tests/test_business_domain_adapter_conformance.py` |
| Routing, decoder order, supporting failures, reference/ignore behavior and warning/coverage | `tests/test_business_domain_extract.py` |
| Package/TypeScript shared-parser implementation fingerprint | `tests/test_business_domain_extract.py` |
| Fatal registry/overlap/prepare failures, cache and publication | `tests/test_business_domain_pipeline.py` |
| Snapshot-only coverage exclusion | `tests/test_business_domain_snapshots.py` |
| Java Properties parser, scope, bytes and persisted redaction | `tests/test_business_domain_java_properties.py` (new) |
| Provider-ready credential redaction | `tests/test_business_domain_candidate_protocol.py` |
| Supporting-consumer dispatch, result validation and common scope contract | `tests/test_business_domain_extract.py` |
| Package-manifest consumer normalization and scope | `tests/test_business_domain_package_manifest.py` (new) |
| TypeScript module-resolution consumer scope and alias call candidates: resolved, ambiguous, unresolved and external | `tests/test_business_domain_typescript_module_resolution.py` (new) |
| Package parser compatibility and digest assembly | `tests/test_repository_digest_runtime.py` and `tests/test_repository_digest.py` |
| Shared TypeScript parser/resolver compatibility | `tests/test_clustering.py` |
| Java literals and Spring conditions | `tests/test_business_domain_java_semantic.py` |
| Schema/contract consistency | `tests/test_business_domain_contract_alignment.py` |
| Two-run Petclinic proof | `tests/f1_petclinic_acceptance.py` (temporary implementation only) |

### Registry, selection and failure

- Catalog reordering does not change `.properties`; all other duplicate
  extensions remain ambiguous.
- Each unresolved duplicate extension `.bas`, `.cl`, `.fs`, `.inc`, `.pl`,
  `.sc` and `.v` remains ambiguous even if its candidate languages resolve to
  the same fallback adapter ID; none acquires an arbitrary language owner.
- Invalid/nonclaimant/unused owners, malformed rules/consumers and concrete
  overlap reject selection visibly.
- Project-map and business inventory agree on SVG.
- Existing Java, JS/TS, Python, SQL and OpenAPI fixtures keep their adapters.
- The 26 paths match exactly 7/3/2/14 once each without fallback.
- Instrument selection/loading: one final selection and one primary load per
  source; no downstream reselection.
- Content-selected SQL/API still select after UTF-8 decode; Properties uses its
  explicit decoder before Latin-1 decode and retains one final selection.
- A same-language file outside an explicit decoder route cannot select
  `java_properties` through fallback matching and never runs its decoder.
- Each owner absence, ambiguity, load failure, per-source extract failure and
  supporting execution failure has exact evidence, state, diagnostic and
  coverage. Three missing capabilities still produce one source warning.
- Registry-load failure records `ADAPTER_REGISTRY_INVALID` as the attempt status
  error, with no file reclassification, FactsArtifact, cache write or
  publication.
- Supporting group exceptions fail their complete owner group; primary and
  enricher `prepare()` exceptions abort the attempt transactionally; per-source
  exceptions and format diagnostics remain isolated.
- Repository-file warning/coverage bijection holds; snapshot coverage remains.
- An ambiguous `.pl` source uses its classified category as non-null Snapshot
  `resource_kind` and the FactsArtifact validates.

### Properties, redaction and byte accounting

- Separators, escapes, comments, comment lines ending in backslash, duplicates,
  blanks and empty files.
- LF/CR/CRLF, form-feed, continuations and EOF behavior.
- UTF-8, Latin-1, Unicode escapes, surrogate pairs, bad hex/lone surrogates and
  explicit BOM behavior.
- Exact spans and occurrence IDs.
- Duplicate keys produce distinct, stable Unit, Symbol and Binding IDs.
- For both duplicate occurrences, assert `unit.kind == 'field'` and the
  projected `facts['symbols'][unit.symbol_id]['kind'] == 'field'`.
- Root/nested main, test, profile and message roles.
- Raw byte accounting equals bytes read for Latin-1.
- Secret literals are absent from every persisted/provider-ready projection.
- Evidence redaction covers quoted/unquoted spaces, `credential`/`passwd` names,
  continuations and decoder/owner failure; `author` and `tokenizer` remain
  visible while delimiter-bounded `token` and `access_token` are redacted.
- Inline `password='alpha beta'`, unquoted line-tail credentials and
  `@ConditionalOnProperty(name="db.password", havingValue="alpha beta")`
  retain structure but never persist `alpha beta` in evidence, snapshots,
  diagnostics or provider-ready projections.
- Repeated and dynamic rejected `havingValue` arguments for a sensitive or
  undecodable property key carry all raw value spans on the pending diagnostic;
  none of their literals persists in evidence, snapshots, diagnostics or
  provider-ready projections.
- A dynamic prefix with a decoded name, and a mixed decoded/dynamic name array,
  each add an unknown-key candidate for every `havingValue`; a partial decode
  can never suppress conservative redaction.
- Raw Evidence, SnapshotArtifact and provider-ready projections contain neither
  value from `{"password":"secret","nested":{"token":"nested-secret"}}`.

### Supporting, reference and Spring behavior

- Existing package and Layer 1 callers use the factored parsers with unchanged
  behavior.
- A malformed `dependencies` section does not suppress valid runtime `engines`,
  and a malformed `engines` section does not suppress valid framework
  dependencies; the strict supporting consumer diagnoses either malformed
  document.
- Package/tsconfig/typings inputs reach compatible primary sources once, with
  scope; same-scope tsconfig/typings merge while same-kind ties fail; malformed
  input and invalid consumption IDs fail with evidence.
- Factoring `rules.lexical_candidates()` leaves every existing lexical/import
  result unchanged. Alias call candidates contain only name-matched Units from
  resolver-selected source paths and cover resolved, ambiguous, unresolved and
  legacy-external outcomes.
- Alias tests cover equal-specificity pattern ties, exact aliases with wildcard
  targets, wildcard aliases with fixed targets and repository-escape targets.
- Reference evidence is bounded and reasoned; ignored sources create nothing;
  ignored content changes do not invalidate semantic facts.
- Spring activation covers exact/wildcard/fully qualified evidence and rejects
  an unrelated simple `ConditionalOnProperty` without the exact import.
- Java literal tests cover non-ASCII, standard/octal/Unicode/surrogate cases,
  Unicode-produced interior quotes, a Unicode-produced backslash followed by a
  second Unicode escape, and all dynamic-expression rejections.
- `name`, `value`, arrays, repeated prefix dots, `havingValue`, omitted
  `havingValue` and `matchIfMissing` normalize correctly without overwritten
  observations; sensitive keys redact the observation expression.
- Observation binding projection accepts either none or all of
  `declaration_units`, `binding_name` and `binding_direction`; every partial
  combination fails the adapter contract, while an explicit empty declaration
  tuple remains a valid unresolved Spring observation.
- Dynamic conditions have evidence; message keys never link; production
  excludes test; test retains main/test candidates; profiled declarations do
  not link in F1.
- Every observation references existing bindings and declaration evidence.

### Schema, determinism and publication

- Validate FactsArtifact, references and evidence; keep schema mirrors equal.
- A failed refresh preserves the prior published model/baseline/history and
  exhibits the documented attempt facts/status behavior.
- Source change before publication triggers `SUPERSEDED` with the new hash.
- Changes to either shared package or TypeScript parser change the extractor
  implementation fingerprint.
- Two extraction runs with fixed build ID/time and run-one snapshots produce
  identical canonical FactsArtifact bytes.
- Patch `business_domains.Synthesis.__init__` and
  `business_domain_synthesis.Synthesis._speed_call_unlogged` with raising,
  incrementing traps during both runs and assert zero calls. This proves the
  actual extraction stage never constructs synthesis or reaches its provider
  bridge without intercepting Git inventory or parser subprocesses.

## Verification commands

Implement in a fresh `/private/tmp` copy using the repository virtual
environment. Create the Petclinic test tree from the exact Git commit, not the
dirty source worktree; copy the retained pre-fix artifact separately. These are
the exact setup and verification commands; `$TEMP_SPEED_COPY` is the only tree
where production files may change.

```diff
+PROOF_ROOT=$(mktemp -d /private/tmp/f1-proof.XXXXXX)
+TEMP_SPEED_COPY="$PROOF_ROOT/speed"
+TEMP_PETCLINIC="$PROOF_ROOT/petclinic"
+BASELINE_FACTS="$PROOF_ROOT/pre-fix-business-domain-facts.json"
+REAL_STATUS_BEFORE="$PROOF_ROOT/real-status-before"
+REAL_PRODUCTION_DIFF_BEFORE="$PROOF_ROOT/real-production-diff-before"
+REAL_PRODUCTION_INDEX_BEFORE="$PROOF_ROOT/real-production-index-before"
+REAL_PRODUCTION_HASHES_BEFORE="$PROOF_ROOT/real-production-hashes-before"
+
+git -C /Users/sanjay/Documents/code/workbench-prs status --porcelain=v1 > "$REAL_STATUS_BEFORE"
+git -C /Users/sanjay/Documents/code/workbench-prs diff --binary -- lib specs/tech/contracts/business-domain-artifacts.md > "$REAL_PRODUCTION_DIFF_BEFORE"
+git -C /Users/sanjay/Documents/code/workbench-prs diff --cached --binary -- lib specs/tech/contracts/business-domain-artifacts.md > "$REAL_PRODUCTION_INDEX_BEFORE"
+git -C /Users/sanjay/Documents/code/workbench-prs ls-files -co --exclude-standard -z -- lib specs/tech/contracts/business-domain-artifacts.md | xargs -0 -I{} shasum -a 256 "/Users/sanjay/Documents/code/workbench-prs/{}" > "$REAL_PRODUCTION_HASHES_BEFORE"
+
+rsync -a --exclude=.git --exclude=.venv --exclude=/.speed/ \
+  --exclude=/.pytest_cache/ --exclude=/dashboard/frontend/node_modules/ \
+  --exclude=/dashboard/frontend/.next/ --exclude=/site/node_modules/ \
+  /Users/sanjay/Documents/code/workbench-prs/ "$TEMP_SPEED_COPY/"
+git -C "$TEMP_SPEED_COPY" init
+git -C "$TEMP_SPEED_COPY" add -A
+git -C "$TEMP_SPEED_COPY" -c user.name=f1-proof -c user.email=f1-proof@invalid commit -m baseline
+cp /Users/sanjay/Documents/code/tmp/spring-petclinic-reactjs/.speed/context/business-domain-facts.json \
+  "$BASELINE_FACTS"
+git clone --no-hardlinks \
+  /Users/sanjay/Documents/code/tmp/spring-petclinic-reactjs "$TEMP_PETCLINIC"
+git -C "$TEMP_PETCLINIC" checkout --detach 77db261c615f30431014f431d5525ddf4ba770df
+test "$(git -C "$TEMP_PETCLINIC" rev-parse HEAD)" = 77db261c615f30431014f431d5525ddf4ba770df
+test -z "$(git -C "$TEMP_PETCLINIC" status --porcelain)"
+
+cd "$TEMP_SPEED_COPY"
+PYTHONDONTWRITEBYTECODE=1 /Users/sanjay/Documents/code/workbench-prs/.venv/bin/python \
+  -m pytest -p no:cacheprovider -q \
+  tests/test_language_registry.py \
+  tests/test_business_domain_java_properties.py \
+  tests/test_business_domain_package_manifest.py \
+  tests/test_business_domain_typescript_module_resolution.py \
+  tests/test_business_domain_adapter_conformance.py \
+  tests/test_business_domain_extract.py \
+  tests/test_business_domain_java_semantic.py \
+  tests/test_business_domain_pipeline.py \
+  tests/test_business_domain_candidate_protocol.py \
+  tests/test_business_domain_snapshots.py \
+  tests/test_repository_digest_runtime.py \
+  tests/test_business_domain_contract_alignment.py
+
+PYTHONDONTWRITEBYTECODE=1 /Users/sanjay/Documents/code/workbench-prs/.venv/bin/python tests/test_unit_layer1.py
+PYTHONDONTWRITEBYTECODE=1 /Users/sanjay/Documents/code/workbench-prs/.venv/bin/python tests/test_clustering.py
+
+PYTHONDONTWRITEBYTECODE=1 /Users/sanjay/Documents/code/workbench-prs/.venv/bin/python \
+  -m pytest -p no:cacheprovider -q tests/test_business_domain_*.py \
+  tests/test_language_registry.py tests/test_repository_digest_runtime.py \
+  tests/test_repository_digest_build.py tests/test_repository_digest.py
+
+/Users/sanjay/Documents/code/workbench-prs/.venv/bin/python specs/tech/contracts/check_contracts.py
+
+PYTHONDONTWRITEBYTECODE=1 /Users/sanjay/Documents/code/workbench-prs/.venv/bin/python \
+  tests/f1_petclinic_acceptance.py \
+  --repo "$TEMP_PETCLINIC" \
+  --baseline "$BASELINE_FACTS" \
+  --first "$PROOF_ROOT/post-fix-1.json" \
+  --second "$PROOF_ROOT/post-fix-2.json"
+
+git add -A
+git status --short
+git diff --cached --check HEAD
+git diff --cached --stat HEAD
+git diff --cached HEAD
+git -C /Users/sanjay/Documents/code/workbench-prs status --porcelain=v1 > "$PROOF_ROOT/real-status-after"
+git -C /Users/sanjay/Documents/code/workbench-prs diff --binary -- lib specs/tech/contracts/business-domain-artifacts.md > "$PROOF_ROOT/real-production-diff-after"
+git -C /Users/sanjay/Documents/code/workbench-prs diff --cached --binary -- lib specs/tech/contracts/business-domain-artifacts.md > "$PROOF_ROOT/real-production-index-after"
+git -C /Users/sanjay/Documents/code/workbench-prs ls-files -co --exclude-standard -z -- lib specs/tech/contracts/business-domain-artifacts.md | xargs -0 -I{} shasum -a 256 "/Users/sanjay/Documents/code/workbench-prs/{}" > "$PROOF_ROOT/real-production-hashes-after"
+cmp "$REAL_STATUS_BEFORE" "$PROOF_ROOT/real-status-after"
+cmp "$REAL_PRODUCTION_DIFF_BEFORE" "$PROOF_ROOT/real-production-diff-after"
+cmp "$REAL_PRODUCTION_INDEX_BEFORE" "$PROOF_ROOT/real-production-index-after"
+cmp "$REAL_PRODUCTION_HASHES_BEFORE" "$PROOF_ROOT/real-production-hashes-after"
```

`tests/f1_petclinic_acceptance.py` exists only in the temporary implementation.
It imports `load_speed_toml` from `lib.context.utils`, creates
`config = business_domain_schema.settings(load_speed_toml(str(repo)))`, and runs
`Extractor(repo, config, fixed_build_id).extract()`. It fixes the build ID and
monkeypatches `business_domain_extract.now`; installs
raising, incrementing traps at `business_domains.Synthesis.__init__` and
`business_domain_synthesis.Synthesis._speed_call_unlogged`; runs extraction
twice; and asserts both counters remain zero. After run 1 it atomically writes
that FactsArtifact to
`$TEMP_PETCLINIC/.speed/context/business-domain-facts.json` before constructing
run 2, so run 2 exercises `Extractor.previous_snapshots`. It also copies run 1
to `--first`, writes run 2 to `--second`, preserves each run's canonical snapshot
blobs, validates the facts schema plus all references and evidence, and compares
the two facts files and corresponding snapshot blobs byte for byte.

The harness calls
`business_domain_schema.atomic_write(repo/'.speed/context/business-domain-facts.json',
facts)`, `validate(facts, 'FactsArtifact')`, `validate_references(facts)`,
`validate_source_warning_coverage(facts)` and
`validate_evidence(repo, facts, config['max_artifact_bytes'])` directly. Those are the
acceptance APIs; it must not substitute an ad hoc JSON or reference check.

The final temporary Git diff is a required reviewed artifact. It must contain
only files authorized by this specification plus their named tests, with no
cache, generated dashboard or unrelated change. The four final `cmp` commands
must be silent and return zero, proving the pre-existing real-worktree status
and production diffs were unchanged.

The harness loads the baseline artifact rather than reconstructing it. It first
asserts exactly 26 `SOURCE_CAPABILITY_UNAVAILABLE` warnings, zero
`coverage.unsupported_source_ids`, and exactly one separate `SOURCE_ENCODING`
warning whose message names `messages_de.properties`. It asserts the exact set
of those 26 warning subject paths equals the set accounted for by routing, with
one disposition each and a 7 analyze, 3 supporting, 2 reference-only and 14
ignore partition. For the post-fix artifact it asserts eight analyzed Properties Resources, 54
configuration declarations with zero Properties parse diagnostics, two ignored
tool Properties paths, zero `SOURCE_CAPABILITY_UNAVAILABLE` warnings, zero
unsupported repository source IDs, no `SOURCE_ENCODING` for
`messages_de.properties`, three consumed supporting Resources, two reference
Resources and two distinct production Spring observations linked only to the
main `petclinic.security.enable=false` binding. It also asserts the binding is
described as repository-declared, never effective. The harness prints actual
pre/post counts, hashes and trap counters. Record that output and the pytest
pass counts here only after execution; never label these targets as executed
results.

## Acceptance criteria

F1 is complete only when executed evidence proves:

- the 26 warning subjects map once to 7 analyze, 3 supporting, 2
  reference-only and 14 ignore decisions;
- all eight relevant Properties files are analyzed and two tool files ignored;
- source-derived declaration totals have an explicit denominator and no
  unexplained parse loss;
- Petclinic has zero source-capability warnings, zero unsupported repository
  source IDs and no encoding warning for `messages_de.properties`;
- the false security declaration has exact evidence and a safe binding;
- both production conditions link only to it, remain distinct and unresolved;
- supporting sources are consumed once; references are evidenced; ignored
  sources create no facts;
- no repository value is called effective deployment state;
- schema/reference/evidence validation and all listed tests pass;
- the two runs are byte-stable and provider/synthesis call counts are zero; and
- the real worktree contains only the intended defect change until production
  implementation is separately authorized.

## Evidence limitation

Verified evidence establishes the pre-fix failure, source population,
prototype behavior and required ownership boundaries. It does not establish
post-fix SPEED output. Post-fix counts become verified only after this design is
implemented and executed in a fresh temporary copy.
