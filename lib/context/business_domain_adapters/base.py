"""Language-neutral source adapter records and semantic result contract."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..treesitter_extract import SymbolDef, Reference, RuleOutput


SEMANTIC_CONTRACT_VERSION = 1
MAX_SEMANTIC_CANDIDATES = 8
SEMANTIC_OUTCOMES = frozenset({
    'exact', 'ambiguous', 'unresolved', 'external', 'unsupported',
})
TRACE_ROLES = frozenset({
    'contract', 'declaration', 'interface', 'abstract_declaration',
    'implementation', 'external_boundary',
})
ANCHOR_REPRESENTATION_ROLES = frozenset({
    'registration', 'exposure', 'contract', 'implementation',
})
ANCHOR_ELIGIBILITY = frozenset({'unresolved', 'eligible', 'supporting'})
ANCHOR_VISIBILITY = frozenset({'unknown', 'external', 'public', 'internal'})
OPERATION_CONTRACT_VERSION = 1
OPERATION_KINDS = frozenset({
    'data_read', 'data_write', 'external_action', 'event_publish',
    'response', 'render', 'navigation', 'audit', 'cache_write',
})
OPERATION_COMPLETION = frozenset({
    'declared', 'invoked', 'acknowledged', 'committed', 'observed', 'unknown',
})


@dataclass(frozen=True)
class SemanticResult:
    """One adapter-neutral semantic decision with its complete evidence.

    Adapters may use any parser or resolver internally, but they return this
    shape before the core projects the result into edges, anchors or
    diagnostics.  In particular, ``external`` and ``unsupported`` cannot be
    confused with an unresolved local name.
    """

    capability: str
    outcome: str
    subject_id: str
    target_id: str | None = None
    candidate_target_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    diagnostic_code: str | None = None
    reason: str | None = None
    contract_version: int = SEMANTIC_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != SEMANTIC_CONTRACT_VERSION:
            raise ValueError('Unsupported semantic result contract')
        if self.outcome not in SEMANTIC_OUTCOMES:
            raise ValueError('Unsupported semantic resolution outcome')
        if not self.capability or not self.subject_id:
            raise ValueError('Semantic results require capability and subject identity')
        if not self.evidence_ids:
            raise ValueError('Semantic results require exact evidence')
        if (self.candidate_target_ids != tuple(sorted(set(self.candidate_target_ids)))
                or len(self.candidate_target_ids) > MAX_SEMANTIC_CANDIDATES):
            raise ValueError('Semantic candidates must be unique, sorted and bounded')
        if self.outcome == 'exact':
            if not self.target_id or self.candidate_target_ids or self.diagnostic_code or self.reason:
                raise ValueError('Exact semantic result must contain only one proven target')
        elif self.outcome == 'ambiguous':
            if self.target_id or len(self.candidate_target_ids) < 2 or not self.diagnostic_code or not self.reason:
                raise ValueError('Ambiguous semantic result requires bounded candidates and a diagnostic')
        elif self.outcome == 'external':
            if not self.target_id or self.candidate_target_ids or not self.diagnostic_code or not self.reason:
                raise ValueError('External semantic result requires an identified boundary and a diagnostic')
        elif self.target_id or self.candidate_target_ids or not self.diagnostic_code or not self.reason:
            raise ValueError('Unresolved and unsupported results require a diagnostic without a target')

    def normalized(self) -> dict:
        """Return the stable JSON shape shared by every adapter language."""
        return {
            'contract_version': self.contract_version,
            'capability': self.capability,
            'outcome': self.outcome,
            'subject_id': self.subject_id,
            'target_id': self.target_id,
            'candidate_target_ids': list(self.candidate_target_ids),
            'evidence_ids': list(self.evidence_ids),
            'diagnostic_code': self.diagnostic_code,
            'reason': self.reason,
        }

@dataclass
class Source:
    path: str
    language: str
    text: str
    source_hash: str
    resource_id: str
    matches: list[dict] = field(default_factory=list)
    units: list[Unit] = field(default_factory=list)
    definitions: list[SymbolDef] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    rule_outputs: list[RuleOutput] = field(default_factory=list)
    semantic_results: list[dict] = field(default_factory=list)
    capability_statuses: dict[str, set[str]] = field(default_factory=dict)
    declared_capabilities: dict[str, str] = field(default_factory=dict)
    adapter_id: str = 'business-domain-static'
    adapter_version: str = '1'
    parser_required: bool = False
    adapter_failed: bool = False
    service_scope: str = 'repository'

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

    @property
    def text(self) -> str:
        return self.source.text[self.start:self.end]


def declare_trace_contract(unit: Unit, role: str | None = None) -> None:
    """Attach one language-neutral semantic completion contract to a symbol."""
    role = role or ('implementation' if unit.executable_body else 'declaration')
    if role not in TRACE_ROLES:
        raise ValueError('Unsupported normalized trace role')
    unit.trace_role = role
    unit.required_relationships = (() if role == 'implementation' else
                                   ('implementation_selection',))
    detection = 'entrypoint_detection' if unit.anchor_kind else 'parsing'
    unit.required_capabilities = ((detection,) if role == 'implementation' else
                                  (detection, 'relationship_resolution'))
    unit.valid_terminal = role == 'implementation'


def http_identity(source: Source, method: str | None, route: str | None) -> str | None:
    """Return an exact service-scoped HTTP identity, never a display-name key."""
    if not method or not route:
        return None
    scope = source.service_scope.strip() if source.service_scope else 'repository'
    return f'http:{scope or "repository"}:{method.upper()}:{route}'


def declare_anchor_representation(
    unit: Unit,
    role: str,
    identity_key: str | None,
    eligibility: str,
    visibility: str,
) -> None:
    """Attach the language-neutral representation decision owned by an adapter."""
    if role not in ANCHOR_REPRESENTATION_ROLES:
        raise ValueError('Unsupported anchor representation role')
    if eligibility not in ANCHOR_ELIGIBILITY:
        raise ValueError('Unsupported anchor eligibility')
    if visibility not in ANCHOR_VISIBILITY:
        raise ValueError('Unsupported anchor visibility')
    if eligibility == 'eligible' and not identity_key:
        raise ValueError('Eligible anchor representation requires exact identity')
    unit.anchor_role = role
    unit.anchor_identity_key = identity_key
    unit.anchor_eligibility = eligibility
    unit.anchor_visibility = visibility


def declare_anchor_registration(
    unit: Unit,
    kind: str,
    *,
    event: str | None = None,
    timing: str | None = None,
    target: str | None = None,
    scope: str | None = None,
    condition: str | None = None,
    label: str | None = None,
    candidate_targets: list[str] | tuple[str, ...] = (),
    resolution: str,
    reason: str | None,
    evidence_spans: list[tuple[Source, int, int]] | None = None,
) -> None:
    """Attach one technology-neutral evidenced entry-point registration."""
    candidates = sorted(set(candidate_targets))
    if (not kind or resolution not in {'resolved', 'ambiguous', 'unresolved'}
            or len(candidates) > MAX_SEMANTIC_CANDIDATES):
        raise ValueError('Registration requires a kind and explicit resolution')
    if (resolution == 'resolved') != (reason is None):
        raise ValueError('Resolved registration has no reason; incomplete registration requires one')
    unit.anchor_registration = {
        'kind': kind, 'event': event, 'timing': timing, 'target': target,
        'scope': scope, 'condition': condition, 'label': label,
        'candidate_targets': candidates,
        'resolution': resolution, 'reason': reason,
    }
    unit.anchor_registration_evidence_spans = list(evidence_spans or [])


def declare_operation_observation(
    unit: Unit,
    *,
    position: int,
    end: int,
    kind: str,
    outcome: str,
    resource: dict | None = None,
    input_binding_names: list[str] | tuple[str, ...] = (),
    output_binding_names: list[str] | tuple[str, ...] = (),
    input_bindings: list[dict] | tuple[dict, ...] = (),
    output_bindings: list[dict] | tuple[dict, ...] = (),
    input_binding_ids: list[str] | tuple[str, ...] = (),
    output_binding_ids: list[str] | tuple[str, ...] = (),
    condition: str | None = None,
    protocol: str | None = None,
    status: str | None = None,
    media_type: str | None = None,
    header_binding_ids: list[str] | tuple[str, ...] = (),
    transaction_scope: str | None = None,
    completion: str = 'declared',
    supporting_evidence_spans: list[tuple[int, int]] | tuple[tuple[int, int], ...] = (),
    projection_gaps: list[dict] | tuple[dict, ...] = (),
    resolution: str,
    reason: str | None,
) -> dict:
    """Build the single versioned operation shape consumed by the core.

    Parsing remains adapter-owned.  This boundary makes every adapter state
    the exact span, origin, capability and provenance before common hydration.
    """
    if not unit.symbol_id:
        raise ValueError('Operation observation requires a normalized origin symbol')
    if (type(position) is not int or type(end) is not int
            or not 0 <= position < end <= len(unit.text)):
        raise ValueError('Operation observation requires a valid unit-relative span')
    if kind not in OPERATION_KINDS:
        raise ValueError('Operation observation has an unsupported kind')
    if completion not in OPERATION_COMPLETION:
        raise ValueError('Operation observation has an unsupported completion state')
    if completion != 'declared':
        raise ValueError(
            'Static source operation completion must remain declared')
    if resolution not in {'resolved', 'ambiguous', 'unresolved'}:
        raise ValueError('Operation observation requires explicit resolution')
    if (resolution == 'resolved') != (reason is None):
        raise ValueError('Incomplete operation observations require a reason')
    if not isinstance(outcome, str) or not outcome.strip():
        raise ValueError('Operation observation requires an evidenced outcome expression')
    if resource is not None:
        resource_fields = {
            'kind', 'name', 'language', 'framework', 'version', 'locator',
            'resolution', 'reason',
        }
        if (not isinstance(resource, dict)
                or set(resource) - resource_fields
                or not {'kind', 'name', 'resolution', 'reason'} <= set(resource)
                or not isinstance(resource.get('kind'), str) or not resource['kind']
                or not isinstance(resource.get('name'), str) or not resource['name']
                or resource['resolution'] not in {'resolved', 'ambiguous', 'unresolved'}
                or (resource['resolution'] == 'resolved') != (resource['reason'] is None)):
            raise ValueError('Operation target must be a normalized resource observation')
    if resource is None and resolution == 'resolved':
        raise ValueError('Resolved operation observation requires a target resource')
    if resolution == 'resolved' and resource['resolution'] != 'resolved':
        raise ValueError('Resolved operation observation requires a resolved target resource')
    if kind == 'data_write' and resolution == 'resolved':
        raise ValueError(
            'Static data write requires an unresolved completion projection')
    capability = 'data_access' if kind in {'data_read', 'data_write'} else 'outputs'
    if unit.source.declared_capabilities.get(capability) not in {'supported', 'partial'}:
        raise ValueError('Adapter emitted an operation outside its declared capability')
    def names(values, field):
        if (not isinstance(values, (list, tuple))
                or any(not isinstance(value, str) or not value for value in values)):
            raise ValueError(f'Operation observation has invalid {field}')
        return sorted(set(values))
    def gaps(values):
        if (not isinstance(values, (list, tuple))
                or any(not isinstance(value, dict)
                       or set(value) != {'projection', 'code', 'reason'}
                       or value['projection'] not in {
                           'target', 'input_bindings', 'output_bindings',
                           'condition', 'transaction_scope', 'completion'}
                       or not isinstance(value['code'], str) or not value['code']
                       or not isinstance(value['reason'], str) or not value['reason']
                       for value in values)):
            raise ValueError('Operation observation has invalid projection gaps')
        return sorted(values, key=lambda value: (
            value['projection'], value['code'], value['reason']))
    def bindings(values, field):
        if not isinstance(values, (list, tuple)):
            raise ValueError(f'Operation observation has invalid {field}')
        normalized = []
        expected = {'name', 'value_type', 'expression', 'position', 'end',
                    'resolution', 'reason'}
        for value in values:
            if not isinstance(value, dict) or set(value) != expected:
                raise ValueError(f'Operation observation has invalid {field}')
            if (not isinstance(value['name'], str) or not value['name']
                    or not isinstance(value['value_type'], str)
                    or (value['expression'] is not None
                        and not isinstance(value['expression'], str))
                    or type(value['position']) is not int or type(value['end']) is not int
                    or not 0 <= value['position'] < value['end'] <= len(unit.text)
                    or value['resolution'] not in {'resolved', 'ambiguous', 'unresolved'}
                    or ((value['resolution'] == 'resolved') != (value['reason'] is None))):
                raise ValueError(f'Operation observation has invalid {field}')
            normalized.append(dict(value))
        return sorted(normalized, key=lambda item: (
            item['position'], item['end'], item['name'], item['value_type']))
    def spans(values):
        if (not isinstance(values, (list, tuple))
                or any(not isinstance(value, (list, tuple)) or len(value) != 2
                       or any(type(offset) is not int for offset in value)
                       or not 0 <= value[0] < value[1] <= len(unit.text)
                       for value in values)):
            raise ValueError('Operation observation has invalid supporting evidence spans')
        return sorted(set(tuple(value) for value in values))
    normalized_gaps = gaps(projection_gaps)
    gap_projections = {gap['projection'] for gap in normalized_gaps}
    normalized_input_bindings = bindings(input_bindings, 'input bindings')
    normalized_output_bindings = bindings(output_bindings, 'output bindings')
    for projection, values in (
            ('input_bindings', normalized_input_bindings),
            ('output_bindings', normalized_output_bindings)):
        if any(value['resolution'] != 'resolved' for value in values):
            if resolution == 'resolved':
                raise ValueError(
                    'Resolved operation observation cannot contain incomplete bindings')
            if projection not in gap_projections:
                raise ValueError(
                    'Incomplete operation binding requires a matching projection gap')
    if resolution == 'resolved' and normalized_gaps:
        raise ValueError('Resolved operation observation cannot retain projection gaps')
    if resolution != 'resolved' and not normalized_gaps:
        raise ValueError('Incomplete operation observation requires a structured projection gap')
    return {
        'contract_version': OPERATION_CONTRACT_VERSION,
        'capability': capability,
        'origin_ref': {'kind': 'symbol', 'id': unit.symbol_id},
        'adapter_id': unit.source.adapter_id,
        'adapter_version': unit.source.adapter_version,
        'position': position,
        'end': end,
        'kind': kind,
        'resource': resource,
        'input_binding_names': names(input_binding_names, 'input binding names'),
        'output_binding_names': names(output_binding_names, 'output binding names'),
        'input_bindings': normalized_input_bindings,
        'output_bindings': normalized_output_bindings,
        'input_binding_ids': names(input_binding_ids, 'input binding IDs'),
        'output_binding_ids': names(output_binding_ids, 'output binding IDs'),
        'condition': condition,
        'outcome': outcome,
        'protocol': protocol,
        'status': status,
        'media_type': media_type,
        'header_binding_ids': names(header_binding_ids, 'header binding IDs'),
        'transaction_scope': transaction_scope,
        'completion': completion,
        'supporting_evidence_spans': spans(supporting_evidence_spans),
        'projection_gaps': normalized_gaps,
        'resolution': resolution,
        'reason': reason,
    }


def normalize_operation_observation(unit: Unit, value: dict) -> dict:
    """Reject loose/unversioned adapter output at the common boundary."""
    if not isinstance(value, dict):
        raise ValueError('Adapter operation output must be a normalized object')
    expected = {
        'contract_version', 'capability', 'origin_ref', 'adapter_id',
        'adapter_version', 'position', 'end', 'kind', 'resource',
        'input_binding_names', 'output_binding_names', 'input_binding_ids',
        'output_binding_ids', 'input_bindings', 'output_bindings',
        'condition', 'outcome', 'protocol', 'status',
        'media_type', 'header_binding_ids', 'transaction_scope', 'completion',
        'supporting_evidence_spans', 'projection_gaps', 'resolution', 'reason',
    }
    if set(value) != expected:
        raise ValueError('Adapter operation output does not match the normalized contract')
    normalized = declare_operation_observation(unit, **{
        key: value[key] for key in expected - {
            'contract_version', 'capability', 'origin_ref', 'adapter_id',
            'adapter_version',
        }
    })
    if value != normalized:
        raise ValueError('Adapter operation output has inconsistent identity or provenance')
    return normalized
