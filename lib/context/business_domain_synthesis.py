"""Evidence-packet interpretation, schema normalization and validated caching.

All stages operate on language-independent records. No repository, framework,
business entity or expected domain name is a classification input here.
"""
from __future__ import annotations
import copy
from collections import Counter
from itertools import product
import json
import math
import os
import signal
import subprocess
import tempfile
import time
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .business_domain_schema import (
    DEFINITIONS, REFERENCE_TARGETS, COLLECTIONS, DomainError, atomic_write, canonical, digest, identifier,
    now, read_json, record, validate, validate_references, implementation_hash,
    validation_finding, validation_findings, candidate_scope_findings,
    verification_report_findings,
)
from .business_domain_work import whole_graph_scope

AGENTS = Path(__file__).resolve().parents[2]/'agents'
POLICY = json.loads(Path(__file__).with_name('business_domain_policies.json').read_text())
TERMINAL_PROVIDER_CODES = frozenset({'PROVIDER_UNAVAILABLE', 'PROVIDER_CAPABILITY_UNAVAILABLE'})
PROVIDER_FAILURE_CODES = {
    'authentication_required':'PROVIDER_UNAVAILABLE',
    'authorization_denied':'PROVIDER_UNAVAILABLE',
    'capability_unavailable':'PROVIDER_CAPABILITY_UNAVAILABLE',
    'rate_limited':'PROVIDER_FAILED',
    'transport_unavailable':'PROVIDER_FAILED',
    'timeout':'PROVIDER_TIMEOUT',
    'process_failed':'PROVIDER_FAILED',
    'response_incomplete':'PROVIDER_FAILED',
    'response_invalid':'INVALID_PROVIDER_OUTPUT',
    'unknown':'PROVIDER_FAILED',
}
OPERATIONS = {
    'synthesize': ('CandidatePayload', 'synthesis'),
    'verify': ('VerificationReport', 'verification'),
    'repair': ('RepairPayload', 'synthesis'),
}
PROVIDER_PROJECTION_VERSION = 1


def allowed_evidence_ids(packet):
    """Return the single authoritative provider-visible evidence catalog."""
    identifiers = set(packet['context']['evidence'])
    identifiers.update(
        key for key, reference in packet['context']['record_refs'].items()
        if reference['collection'] == 'evidence'
    )
    return sorted(identifiers)


def _projection_counts(value):
    counts = {'objects': 0, 'arrays': 0, 'strings': 0, 'records': 0}
    def walk(item):
        if isinstance(item, dict):
            counts['objects'] += 1
            counts['records'] += isinstance(item.get('id'), str)
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            counts['arrays'] += 1
            for child in item:
                walk(child)
        elif isinstance(item, str):
            counts['strings'] += 1
    walk(value)
    return counts


def _record_ids(value):
    identifiers = set()
    def walk(item):
        if isinstance(item, dict):
            if isinstance(item.get('id'), str) and ':' in item['id']:
                identifiers.add(item['id'])
            for key, child in item.items():
                if isinstance(key, str) and ':' in key:
                    identifiers.add(key)
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
    walk(value)
    return identifiers


def _packet_reference_gaps(packet, identifiers):
    missing = set()
    def walk(item, parent=''):
        if isinstance(item, dict):
            for key, child in item.items():
                targets = REFERENCE_TARGETS.get(
                    parent+'.'+key, REFERENCE_TARGETS.get(key))
                if targets:
                    values = child if isinstance(child, list) else (
                        [child] if isinstance(child, str) else [])
                    missing.update(value for value in values
                                   if ':' in value and value not in identifiers)
                walk(child, key)
        elif isinstance(item, list):
            for child in item:
                walk(child, parent)
    walk(packet)
    return missing


class ProviderProjection:
    """Lossless local codec for the provider boundary only.

    The provider receives every interpretation-bearing value. Repeated storage
    metadata is retained in this local sidecar and restored before the exact
    round-trip proof; it never changes the canonical packet or persisted graph.
    """
    FORMAT = 'speed-domain-wire'
    VERSION = PROVIDER_PROJECTION_VERSION
    _OMITTED_EVIDENCE_FIELDS = ('content_hash', 'extractor', 'extractor_version')
    _OMITTED_LOCATOR_FIELDS = ('source_hash', 'snapshot_id', 'pointer')

    def __init__(self, packet):
        self.packet = copy.deepcopy(packet)
        self.canonical_hash = digest(self.packet)
        self.counts = _projection_counts(self.packet)
        semantic, self.sidecar = self._semantic_packet(self.packet)
        self.semantic_hash = digest(semantic)
        self.identifiers = _record_ids(semantic)
        self.reference_gaps = _packet_reference_gaps(
            self.packet, _record_ids(self.packet))
        if self.reference_gaps:
            raise DomainError('INVALID_REFERENCE',
                              'Provider projection requires closed packet references',
                              sorted(self.reference_gaps)[0])
        self.aliases = {ident: f'_ref:{index}' for index, ident in
                        enumerate(sorted(self.identifiers))}
        self.canonical_ids = {alias: ident for ident, alias in self.aliases.items()}
        aliased = self._rewrite(semantic, self.aliases)
        self.wire_packet = self._pack(aliased)
        # Fail closed at construction, before sizing or provider dispatch.
        self.decode_packet(self.wire_packet)

    def _semantic_packet(self, packet):
        value = copy.deepcopy(packet)
        context = value.get('context', {})
        sidecar = {'input_fingerprint': value.pop('input_fingerprint', None),
                   'source_snapshots': context.pop('source_snapshots', None),
                   'evidence': {}}
        for evidence_id, evidence in context.get('evidence', {}).items():
            omitted = {}
            for field in self._OMITTED_EVIDENCE_FIELDS:
                if field in evidence:
                    omitted[field] = evidence.pop(field)
            locator = evidence.get('locator', {})
            locator_omitted = {}
            for field in self._OMITTED_LOCATOR_FIELDS:
                if field in locator:
                    locator_omitted[field] = locator.pop(field)
            if locator_omitted:
                omitted['locator'] = locator_omitted
            if omitted:
                sidecar['evidence'][evidence_id] = omitted
        # GraphContext retains both canonical indexes and embedded anchor
        # records. The wire sends the embedded association as IDs and keeps
        # each interpretation-bearing record once in the top-level index.
        if ('anchor_representations' in context
                and 'anchor_correspondences' in context):
            for anchor in context.get('anchors', {}).values():
                anchor['representations'] = [
                    value['id'] for value in anchor['representations']]
                anchor['correspondences'] = [
                    value['id'] for value in anchor['correspondences']]
        return value, sidecar

    @staticmethod
    def _rewrite(value, replacements):
        if isinstance(value, str):
            return replacements.get(value, value)
        if isinstance(value, list):
            return [ProviderProjection._rewrite(child, replacements)
                    for child in value]
        if isinstance(value, dict):
            return {replacements.get(key, key):
                    ProviderProjection._rewrite(child, replacements)
                    for key, child in value.items()}
        return value

    def _pack(self, value):
        frequencies = Counter(self._strings(value))
        strings = sorted(frequencies, key=lambda item: (-frequencies[item], item))
        string_index = {item: index for index, item in enumerate(strings)}
        layouts = sorted(set(self._layouts(value)))
        layout_index = {item: index for index, item in enumerate(layouts)}

        def encode(item):
            if isinstance(item, dict):
                if self._is_record_map(item):
                    return [-1, *[encode(item[key]) for key in sorted(item)]]
                layout = tuple(sorted(item))
                return [layout_index[layout],
                        *[encode(item[key]) for key in layout]]
            if isinstance(item, list):
                return [None, *[encode(child) for child in item]]
            if isinstance(item, str):
                return string_index[item]
            if item is None or type(item) is bool:
                return item
            if type(item) is int and item >= 0:
                return -item-2
            if type(item) in (int, float):
                return [False, item]
            raise DomainError('INVALID_ARTIFACT',
                              'Provider projection encountered an unsupported value')

        return {'format': self.FORMAT, 'version': self.VERSION,
                'semantic_hash': self.semantic_hash, 'strings': strings,
                'layouts': [list(layout) for layout in layouts],
                'root': encode(value)}

    @staticmethod
    def _is_record_map(value):
        return bool(value) and all(isinstance(child, dict)
                                   and child.get('id') == key
                                   for key, child in value.items())

    @classmethod
    def _strings(cls, value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for child in value.values():
                yield from cls._strings(child)
        elif isinstance(value, list):
            for child in value:
                yield from cls._strings(child)

    @classmethod
    def _layouts(cls, value):
        if isinstance(value, dict):
            if not cls._is_record_map(value):
                yield tuple(sorted(value))
            for child in value.values():
                yield from cls._layouts(child)
        elif isinstance(value, list):
            for child in value:
                yield from cls._layouts(child)

    def _unpack(self, wire):
        if (not isinstance(wire, dict) or wire.get('format') != self.FORMAT
                or wire.get('version') != self.VERSION
                or wire.get('semantic_hash') != self.semantic_hash):
            raise DomainError('INVALID_ARTIFACT',
                              'Provider projection identity is invalid')
        strings, layouts = wire.get('strings'), wire.get('layouts')
        if not isinstance(strings, list) or not isinstance(layouts, list):
            raise DomainError('INVALID_ARTIFACT',
                              'Provider projection dictionaries are invalid')

        def decode(item):
            if not isinstance(item, list):
                if item is None or type(item) in (bool, float):
                    return item
                if type(item) is int:
                    if item <= -2:
                        return -item-2
                    if item == -1:
                        raise DomainError('INVALID_ARTIFACT',
                                          'Provider projection scalar is invalid')
                    try:
                        return strings[item]
                    except IndexError as exc:
                        raise DomainError('INVALID_ARTIFACT',
                                          'Provider projection string reference is invalid') from exc
                raise DomainError('INVALID_ARTIFACT',
                                  'Provider projection value is invalid')
            if item and item[0] is None:
                return [decode(child) for child in item[1:]]
            if item and item[0] == -1:
                records = [decode(child) for child in item[1:]]
                if any(not isinstance(child, dict)
                       or not isinstance(child.get('id'), str)
                       for child in records):
                    raise DomainError('INVALID_ARTIFACT',
                                      'Provider projection record map is invalid')
                result = {child['id']: child for child in records}
                if len(result) != len(records):
                    raise DomainError('INVALID_ARTIFACT',
                                      'Provider projection repeated a record ID')
                return result
            if len(item) == 2 and item[0] is False and type(item[1]) in (int, float):
                return item[1]
            if item and type(item[0]) is int and item[0] >= 0:
                try:
                    layout = layouts[item[0]]
                except IndexError as exc:
                    raise DomainError('INVALID_ARTIFACT',
                                      'Provider projection layout reference is invalid') from exc
                if not isinstance(layout, list) or len(layout) != len(item)-1:
                    raise DomainError('INVALID_ARTIFACT',
                                      'Provider projection object layout is invalid')
                return {key: decode(child) for key, child in
                        zip(layout, item[1:])}
            raise DomainError('INVALID_ARTIFACT',
                              'Provider projection tag is invalid')
        return decode(wire.get('root'))

    def decode_packet(self, wire):
        value = self._rewrite(self._unpack(wire), self.canonical_ids)
        if self.sidecar['input_fingerprint'] is not None:
            value['input_fingerprint'] = self.sidecar['input_fingerprint']
        context = value.get('context', {})
        if ('anchor_representations' in context
                and 'anchor_correspondences' in context):
            for anchor in context.get('anchors', {}).values():
                anchor['representations'] = [copy.deepcopy(
                    context['anchor_representations'][identifier])
                    for identifier in anchor['representations']]
                anchor['correspondences'] = [copy.deepcopy(
                    context['anchor_correspondences'][identifier])
                    for identifier in anchor['correspondences']]
        snapshots = self.sidecar['source_snapshots']
        if snapshots is not None:
            context['source_snapshots'] = copy.deepcopy(snapshots)
        for evidence_id, omitted in self.sidecar['evidence'].items():
            evidence = context.get('evidence', {}).get(evidence_id)
            if evidence is None:
                raise DomainError('INVALID_ARTIFACT',
                                  'Provider projection lost an evidence record',
                                  evidence_id)
            for field, field_value in omitted.items():
                if field == 'locator':
                    evidence['locator'].update(copy.deepcopy(field_value))
                else:
                    evidence[field] = copy.deepcopy(field_value)
        if (_projection_counts(value) != self.counts
                or digest(value) != self.canonical_hash
                or canonical(value) != canonical(self.packet)):
            raise DomainError('INVALID_ARTIFACT',
                              'Provider projection failed exact round-trip validation')
        if _packet_reference_gaps(value, _record_ids(value)) != self.reference_gaps:
            raise DomainError('INVALID_REFERENCE',
                              'Provider projection changed packet reference closure')
        return value

    def project_schema(self, schema):
        return self._rewrite(copy.deepcopy(schema), self.aliases)

    def extend_aliases(self, *values):
        """Alias request-owned records that are not part of the graph."""
        identifiers = set()
        for value in values:
            identifiers.update(_record_ids(value))
        additions = sorted(identifiers - set(self.aliases))
        offset = len(self.aliases)
        aliases = {identifier: f'_ref:{offset + index}'
                   for index, identifier in enumerate(additions)}
        self.aliases.update(aliases)
        self.canonical_ids.update(
            {alias: identifier for identifier, alias in aliases.items()})

    def decode_response(self, value):
        return self._rewrite(copy.deepcopy(value), self.canonical_ids)


PROJECTION_INSTRUCTIONS = (
    'The packet uses speed-domain-wire version 1. Decode root recursively: '
    'an array beginning null is a list; an array beginning -1 is an ID-keyed '
    'record map; any other array begins with layout index L and is an object '
    'whose sorted field names are layouts[L]. A nonnegative integer N is '
    'strings[N]; a negative integer -N-2 is the original nonnegative integer. '
    'Values named _ref:N are stable aliases '
    'for supplied record IDs. Reuse those aliases exactly in response reference '
    'fields. New semantic record IDs must use their contract prefix and must not '
    'use _ref:. Storage-only snapshot and integrity metadata is intentionally '
    'local. Anchor representation/correspondence arrays contain IDs into their '
    'complete top-level maps. Every semantic graph record and evidence excerpt is present.'
)


def provider_packet_identity(packet, projection=None):
    projection = projection or ProviderProjection(packet)
    return digest({
        'provider_projection_version': projection.VERSION,
        'semantic_hash': projection.semantic_hash,
    }), projection


def normalize_provider_capabilities(value):
    expected = {'provider_context_tokens','provider_max_output_tokens',
                'output_limit_enforcement'}
    if not isinstance(value,dict) or set(value) != expected:
        raise DomainError('PROVIDER_CAPABILITY_UNAVAILABLE',
                          'Provider returned invalid model capability metadata')
    for field in ('provider_context_tokens','provider_max_output_tokens'):
        cap = value[field]
        if cap is not None and (type(cap) is not int or cap < 1):
            raise DomainError('PROVIDER_CAPABILITY_UNAVAILABLE',
                              'Provider returned invalid model capability metadata',field)
    if value['output_limit_enforcement'] not in ('unknown','provider','local_estimate'):
        raise DomainError('PROVIDER_CAPABILITY_UNAVAILABLE',
                          'Provider returned invalid output-limit enforcement metadata',
                          'output_limit_enforcement')
    return copy.deepcopy(value)


def injected_provider_capabilities(provider):
    return normalize_provider_capabilities({
        'provider_context_tokens':getattr(provider,'provider_context_tokens',None),
        'provider_max_output_tokens':getattr(provider,'provider_max_output_tokens',None),
        'output_limit_enforcement':getattr(provider,'output_limit_enforcement','unknown'),
    })


def provider_fingerprint(provider):
    return digest({'transport':type(provider).__name__,'model':provider.model,
        'capabilities':injected_provider_capabilities(provider),
        'implementation':implementation_hash(Path(__file__))})


def prompt_fingerprint():
    return digest(agent_instructions())


def agent_instructions():
    instructions = {}
    for role in ('synthesis', 'verification'):
        path = AGENTS/f'business-domain-{role}.md'
        try:
            instructions[role] = path.read_text(encoding='utf-8')
        except (OSError,UnicodeError) as exc:
            raise DomainError('AGENT_UNAVAILABLE',f'Cannot load the business-domain {role} agent definition') from exc
        if not instructions[role].strip():
            raise DomainError('AGENT_UNAVAILABLE',f'The business-domain {role} agent definition is empty')
    return instructions


def input_token_estimate(request, schema):
    """Local tokenizer estimate with explicit framing and uncertainty allowance."""
    import tiktoken
    encoding = tiktoken.get_encoding(POLICY['input_token_encoding'])
    text = canonical({'request':request,'output_schema':schema}).decode('utf-8')
    count = len(encoding.encode(text,disallowed_special=()))
    return math.ceil(count*(100+POLICY['input_token_margin_percent'])/100)+POLICY['input_framing_tokens']


def projected_input_token_estimate(request, schema):
    """Exact token count of the deterministic final wire plus framing."""
    import tiktoken
    encoding = tiktoken.get_encoding(POLICY['input_token_encoding'])
    text = canonical({'request': request, 'output_schema': schema}).decode('utf-8')
    return (len(encoding.encode(text, disallowed_special=())) +
            POLICY['input_framing_tokens'])


def semantic_request_identity_input(request):
    """Remove only transport-attempt fields from stable semantic identity."""
    return {key: copy.deepcopy(value) for key, value in request.items()
            if key not in ('request_id', 'deadline_at')}


def strict_conditional_variants(schema):
    """Compile finite canonical if/then rules into strict-output anyOf."""
    rules = schema.get('allOf', [])
    if not rules:
        return copy.deepcopy(schema)
    if any(set(rule) != {'if', 'then'}
           or set(rule['if']) != {'properties'}
           or set(rule['then']) != {'properties'} for rule in rules):
        raise DomainError(
            'INVALID_ARTIFACT',
            'Provider schema contains unsupported conditional rules')
    discriminants = sorted({
        field for rule in rules for field in rule['if']['properties']})
    choices = []
    for field in discriminants:
        values = schema['properties'][field].get('enum')
        if not values:
            raise DomainError(
                'INVALID_ARTIFACT',
                'Provider schema conditional requires a finite discriminator',
                field)
        choices.append(values)

    def matches(condition, assignment):
        for field, constraint in condition['properties'].items():
            value = assignment[field]
            if ('const' in constraint and value != constraint['const']) or \
                    ('enum' in constraint and value not in constraint['enum']):
                return False
        return True

    def narrow(target, constraint):
        if 'type' in constraint and 'anyOf' in target:
            options = [option for option in target['anyOf']
                       if option.get('type') == constraint['type']]
            if len(options) != 1:
                return False
            target.clear()
            target.update(copy.deepcopy(options[0]))
        if ('type' in constraint and 'type' in target
                and target['type'] != constraint['type']):
            return False
        for key, value in constraint.items():
            if key == 'enum' and 'enum' in target:
                value = [item for item in target['enum'] if item in value]
                if not value:
                    return False
            target[key] = copy.deepcopy(value)
        return not (target.get('minItems', 0)
                    > target.get('maxItems', math.inf))

    variants = []
    for values in product(*choices):
        assignment = dict(zip(discriminants, values))
        variant = {key: copy.deepcopy(value) for key, value in schema.items()
                   if key != 'allOf'}
        valid = True
        for field, value in assignment.items():
            variant['properties'][field]['enum'] = [value]
        for rule in rules:
            if not matches(rule['if'], assignment):
                continue
            for field, constraint in rule['then']['properties'].items():
                if not narrow(variant['properties'][field], constraint):
                    valid = False
                    break
            if not valid:
                break
        if valid:
            variants.append(variant)
    if not variants:
        raise DomainError(
            'INVALID_ARTIFACT',
            'Provider schema conditional has no valid variants')
    changed = True
    while changed:
        changed = False
        for left_index, left in enumerate(variants):
            for right_index in range(left_index+1, len(variants)):
                right = variants[right_index]
                for field, order in zip(discriminants, choices):
                    left_shape = copy.deepcopy(left)
                    right_shape = copy.deepcopy(right)
                    left_values = left_shape['properties'][field].pop('enum')
                    right_values = right_shape['properties'][field].pop('enum')
                    if left_shape != right_shape:
                        continue
                    allowed = set(left_values) | set(right_values)
                    left['properties'][field]['enum'] = [
                        value for value in order if value in allowed]
                    variants.pop(right_index)
                    changed = True
                    break
                if changed:
                    break
            if changed:
                break
    return {'anyOf': variants}


def wire_schema(type_name: str, packet=None) -> dict:
    """Lossless map-to-record-array codec for strict-output providers.

    Canonical artifacts keep ID-keyed maps. The wire uses arrays because
    strict structured-output APIs cannot express arbitrary object keys.
    """
    needed = set()
    def convert(schema, definition=None):
        if 'allOf' in schema:
            schema = strict_conditional_variants(schema)
        if '$ref' in schema:
            needed.add(schema['$ref'].rsplit('/',1)[1])
            return dict(schema)
        if schema.get('type') == 'object' and isinstance(schema.get('additionalProperties'),dict):
            return {'type':'array','items':convert(schema['additionalProperties'])}
        result = {}
        for key,value in schema.items():
            if key == 'uniqueItems':
                # Enforced by the canonical validator after decoding; this
                # keyword is unsupported by strict-output transports.
                continue
            if key == 'properties':
                result[key] = {name:convert(child) for name,child in value.items()}
                for name, child in result[key].items():
                    targets = REFERENCE_TARGETS.get(str(definition)+'.'+name,REFERENCE_TARGETS.get(name))
                    if targets:
                        child['description'] = (child.get('description','')+' References must identify records of kind: '+
                            ', '.join(targets)+'. Reuse exact supplied IDs; do not substitute names or another record kind.').strip()
            elif key in ('anyOf','oneOf'):
                result['anyOf'] = [convert(child) for child in value]
            elif key == 'items':
                result[key] = convert(value)
            else:
                result[key] = value
        return result
    result = convert(DEFINITIONS[type_name],type_name); definitions = {}
    while needed-set(definitions):
        name = sorted(needed-set(definitions))[0]
        definitions[name] = convert(DEFINITIONS[name],name)
    if definitions:
        _constrain_provider_record_ids(definitions)
        result['$defs'] = definitions
    # Semantic providers propose records; only the review workflow may assign
    # a human review state.  Encode that write boundary in the provider schema
    # instead of spending a repair request on a value the runtime must reject.
    for name in ('Activity','Ownership','Domain'):
        definition = definitions.get(name)
        if definition and 'review_state' in definition.get('properties',{}):
            definition['properties']['review_state']['enum'] = ['proposed']
    claim = definitions.get('Claim')
    if claim:
        claim['properties']['semantic_review']['enum'] = ['uncertain']
    # An InformationUse is a resource-backed read/write assertion. Local form
    # state or a concept without a trace-reachable resource is not such a use.
    information_use = definitions.get('InformationUse')
    if information_use:
        information_use['properties']['resource_ids']['minItems'] = 1
    activity = definitions.get('Activity')
    if activity:
        for field in ('trace_ids', 'evidence_ids', 'claim_ids'):
            activity['properties'][field]['minItems'] = 1
    relationship = definitions.get('RuleRelationship')
    if relationship:
        relationship['properties']['verification']['enum'] = ['inferred', 'unresolved']
        relationship['properties']['evidence_ids']['minItems'] = 1
        relationship['properties']['explanation']['minLength'] = 1
    domain = definitions.get('Domain')
    if domain:
        for field in ('activity_memberships', 'evidence_ids', 'claim_ids'):
            domain['properties'][field]['minItems'] = 1
        domain['properties']['boundary_rationale']['minLength'] = 1
    membership = definitions.get('ActivityMembership')
    if membership:
        membership['properties']['claim_ids']['minItems'] = 1
    if packet is not None:
        produced = set(DEFINITIONS[type_name]['properties'])
        fixed = {}
        evidence_ids = allowed_evidence_ids(packet)
        evidence_definition = None
        if evidence_ids:
            evidence_definition = 'AllowedEvidenceId'
            definitions[evidence_definition] = {
                'type': 'string', 'enum': evidence_ids}
            result.setdefault('$defs', definitions)
        for kind,collection in COLLECTIONS.items():
            if collection in produced or kind == 'ev':
                continue
            ids = sorted(packet['context'].get(collection, {}))
            if 0 < len(ids) <= POLICY['max_reference_enum_values']:
                fixed[kind] = ids
        def constrain(shape, values):
            if shape.get('type') == 'string':
                shape['enum'] = values
            elif shape.get('type') == 'array':
                constrain(shape['items'],values)
            for option in shape.get('anyOf',[]):
                constrain(option,values)
        def constrain_reference(shape, reference):
            if shape.get('type') == 'string':
                shape.clear()
                shape['$ref'] = reference
            elif shape.get('type') == 'array':
                constrain_reference(shape['items'],reference)
            for option in shape.get('anyOf',[]):
                constrain_reference(option,reference)
        def annotate(shape, definition=None):
            for name,child in shape.get('properties',{}).items():
                targets = REFERENCE_TARGETS.get(str(definition)+'.'+name,REFERENCE_TARGETS.get(name))
                if targets == ['ev'] and evidence_definition is not None:
                    constrain_reference(
                        child, '#/$defs/'+evidence_definition)
                elif targets and len(targets)==1 and targets[0] in fixed:
                    constrain(child,fixed[targets[0]])
                annotate(child, definition)
            if isinstance(shape.get('items'), dict):
                annotate(shape['items'], definition)
            for option in shape.get('anyOf', []):
                annotate(option, definition)
            for name,child in shape.get('$defs',{}).items():
                annotate(child,name)
        annotate(result,type_name)
    return result


def from_wire(value, schema):
    if '$ref' in schema:
        return from_wire(value, DEFINITIONS[schema['$ref'].rsplit('/',1)[1]])
    if value is None:
        return None
    if 'anyOf' in schema:
        return from_wire(value,schema['anyOf'][0])
    if schema.get('type') == 'object' and isinstance(schema.get('additionalProperties'),dict):
        items = [from_wire(item,schema['additionalProperties']) for item in value]
        if len({item['id'] for item in items}) != len(items):
            raise DomainError('INVALID_PROVIDER_OUTPUT','Provider repeated a record ID')
        return {item['id']:item for item in items}
    if schema.get('type') == 'object':
        return {key:from_wire(child,schema['properties'][key]) for key,child in value.items()}
    if schema.get('type') == 'array':
        result = [from_wire(child,schema['items']) for child in value]
        if schema.get('uniqueItems'):
            unique = []
            seen = set()
            for child in result:
                key = canonical(child)
                if key not in seen:
                    seen.add(key)
                    unique.append(child)
            return unique
        return result
    return value


ID_PREFIX_BY_TYPE = {
    'Activity': 'activity', 'Rule': 'rule', 'Concept': 'concept',
    'InformationUse': 'information_use', 'Ownership': 'ownership',
    'RuleRelationship': 'rule_relationship', 'Claim': 'claim',
    'Domain': 'domain', 'Relationship': 'relationship',
    'ScopeDisposition': 'disposition',
    'VerificationFinding': 'verification_finding',
}


def _set_record_id_pattern(shape, pattern):
    """Apply one ID pattern across direct and conditional record schemas."""
    properties = shape.get('properties', {})
    if 'id' in properties:
        properties['id']['pattern'] = pattern

    for keyword in ('anyOf', 'oneOf', 'allOf'):
        for variant in shape.get(keyword, []):
            _set_record_id_pattern(variant, pattern)


def _constrain_provider_record_ids(definitions):
    """Constrain provider-created IDs using the normalization prefix owner."""
    for record_type, prefix in ID_PREFIX_BY_TYPE.items():
        definition = definitions.get(record_type)
        if definition is not None:
            _set_record_id_pattern(
                definition, f'^{prefix}:[^ ]+$')


DEPENDENCY_GROUPS = (
    ('concepts', 'rules', 'rule_relationships', 'dispositions'),
    ('activities',),
    ('domains', 'information_uses'),
    ('relationships', 'ownerships'),
    ('claims', 'findings'),
)


def _contract_record_collections():
    mappings, sequences = {}, {}
    for output_type in ('CandidatePayload', 'VerificationReport'):
        for name, shape in DEFINITIONS[output_type]['properties'].items():
            child = shape.get('additionalProperties')
            if isinstance(child, dict) and '$ref' in child:
                mappings[name] = child['$ref'].rsplit('/', 1)[1]
            child = shape.get('items')
            if isinstance(child, dict) and '$ref' in child:
                sequences[name] = child['$ref'].rsplit('/', 1)[1]
    return mappings, sequences


MAPPING_RECORD_TYPES, SEQUENCE_RECORD_TYPES = _contract_record_collections()
CANDIDATE_RECORD_COLLECTIONS = tuple(
    name for name in DEFINITIONS['CandidatePayload']['properties']
    if name in MAPPING_RECORD_TYPES or name in SEQUENCE_RECORD_TYPES)


def _declared_set_paths(shape, path=(), seen=frozenset()):
    if '$ref' in shape:
        name = shape['$ref'].rsplit('/', 1)[1]
        if name in seen:
            return set()
        return _declared_set_paths(
            DEFINITIONS[name], path, seen | {name})
    paths = {path} if shape.get('type') == 'array' and shape.get('uniqueItems') else set()
    if shape.get('type') == 'object':
        for name, child in shape.get('properties', {}).items():
            paths.update(_declared_set_paths(
                child, path + (name,), seen))
    if shape.get('type') == 'array' and isinstance(shape.get('items'), dict):
        paths.update(_declared_set_paths(
            shape['items'], path + ('[]',), seen))
    for keyword in ('allOf', 'anyOf', 'oneOf'):
        for child in shape.get(keyword, []):
            paths.update(_declared_set_paths(child, path, seen))
    return paths


SET_PATHS_BY_TYPE = {
    name: _declared_set_paths(DEFINITIONS[name], seen=frozenset({name}))
    for name in ID_PREFIX_BY_TYPE
}


def _provider_records(payload):
    records, key_findings, id_findings, owners = {}, [], [], {}
    collections = {**MAPPING_RECORD_TYPES, **SEQUENCE_RECORD_TYPES}
    for collection, record_type in collections.items():
        if collection not in payload:
            continue
        values = payload[collection]
        entries = (sorted(values.items()) if isinstance(values, dict)
                   else [(item['id'], item) for item in values])
        records[collection] = entries
        expected = ID_PREFIX_BY_TYPE[record_type] + ':'
        for key, item in entries:
            ident = item['id']
            if isinstance(values, dict) and key != ident:
                key_findings.append(validation_finding(
                    'INVALID_PROVIDER_OUTPUT',
                    f'{collection} map key differs from its record ID',
                    subject_ids=[key, ident]))
            if ident.startswith('_ref:') or not ident.startswith(expected):
                id_findings.append(validation_finding(
                    'INVALID_ID',
                    f'{record_type} requires a {expected} response-local ID',
                    subject_ids=[ident]))
            previous = owners.get(ident)
            if previous is not None:
                id_findings.append(validation_finding(
                    'INVALID_ID',
                    'One response-local ID identifies more than one new record',
                    subject_ids=[ident]))
            else:
                owners[ident] = collection
    findings = key_findings or id_findings
    if findings:
        raise DomainError(
            findings[0]['code'], findings[0]['message'], findings=findings,
            rejected_candidate=copy.deepcopy(payload),
            repair_kind='schema' if key_findings else 'semantic')
    return records


def _resolved(ident, aliases):
    return aliases.get(ident, ident)


def _identity_basis(collection, item, graph, aliases):
    anchors = sorted(graph.get(
        'canonical_anchor_ids', graph.get('anchor_ids', [])))
    resolved = lambda ident: _resolved(ident, aliases)
    if collection == 'concepts':
        return [anchors, sorted(item['qualified_type_names']), item['name']]
    if collection == 'rules':
        return [anchors, sorted(item['observation_ids']),
                item['predicate_or_formula'], item['scope'],
                item['evaluation_kind'], sorted(item['preconditions']),
                item['outcome']]
    if collection == 'rule_relationships':
        return [item['from_observation_id'], item['to_observation_id'],
                item['kind']]
    if collection == 'dispositions':
        return [graph['scope_id'], item['subject_kind'], item['subject_id']]
    if collection == 'activities':
        return {
            'anchor_ids': sorted(item['anchor_ids']),
            'trace_ids': sorted(item['trace_ids']),
            'input_binding_ids': sorted(item['input_binding_ids']),
            'output_binding_ids': sorted(item['output_binding_ids']),
            'effect_ids': sorted(item['effect_ids']),
            'concept_ids': sorted(map(resolved, item['concept_ids'])),
            'rule_ids': sorted(map(resolved, item['rule_ids'])),
        }
    if collection == 'domains':
        return sorted((resolved(member['activity_id']), member['role'])
                      for member in item['activity_memberships'])
    if collection == 'information_uses':
        return [resolved(item['activity_id']), resolved(item['concept_id']),
                sorted(item['resource_ids']), item['access'],
                sorted(item['binding_ids']), sorted(item['effect_ids']),
                sorted(item['trace_ids'])]
    if collection == 'relationships':
        return [resolved(item['from_domain_id']),
                resolved(item['to_domain_id']),
                resolved(item['from_activity_id']),
                resolved(item['to_activity_id']), item['kind'],
                sorted(item['trace_ids'])]
    if collection == 'ownerships':
        return [resolved(item['concept_id']), resolved(item['domain_id']),
                item['kind'], sorted(map(resolved, item['activity_ids'])),
                sorted(map(resolved, item['information_use_ids']))]
    if collection == 'claims':
        return [resolved(item['subject_id']), item['kind'], item['text'],
                sorted(item['evidence_ids']), sorted(item['trace_ids'])]
    if collection == 'findings':
        return [graph['scope_id'], item['category'], item['severity'],
                item['message'], sorted(map(resolved, item['subject_ids'])),
                sorted(item['evidence_ids'])]
    raise DomainError('INVALID_ARTIFACT', f'Unknown semantic collection {collection}')


def _allocate_collision_safe_ids(records, collections, graph, aliases):
    proposed = {}
    for collection in collections:
        record_type = (MAPPING_RECORD_TYPES.get(collection)
                       or SEQUENCE_RECORD_TYPES.get(collection))
        kind = ID_PREFIX_BY_TYPE[record_type]
        for temporary_id, item in records.get(collection, []):
            basis = _identity_basis(collection, item, graph, aliases)
            basis_bytes = canonical(basis)
            short_id = identifier(kind, basis)
            proposed.setdefault(short_id, []).append(
                (basis_bytes, temporary_id))
    for short_id in sorted(proposed):
        group = proposed[short_id]
        distinct = {basis for basis, _ in group}
        for basis_bytes, temporary_id in group:
            aliases[temporary_id] = (
                short_id if len(distinct) == 1
                else f'{short_id}:{digest(basis_bytes)}')


def _rewrite(value, aliases, rejected_candidate):
    if isinstance(value, str):
        return aliases.get(value, value)
    if isinstance(value, list):
        return [_rewrite(item, aliases, rejected_candidate) for item in value]
    if not isinstance(value, dict):
        return value
    rewritten, original_key = {}, {}
    for old_key in sorted(value):
        new_key = aliases.get(old_key, old_key)
        if new_key in rewritten:
            subjects = [key for key in
                        (original_key[new_key], old_key, new_key)
                        if ':' in key]
            finding = validation_finding(
                'CANONICAL_KEY_COLLISION',
                'Two dictionary keys resolve to the same canonical ID',
                subject_ids=subjects)
            raise DomainError(
                finding['code'], finding['message'], findings=[finding],
                rejected_candidate=copy.deepcopy(rejected_candidate),
                repair_kind='semantic')
        original_key[new_key] = old_key
        rewritten[new_key] = _rewrite(
            value[old_key], aliases, rejected_candidate)
    return rewritten


def _canonicalize_sets(value, set_paths, path=()):
    if isinstance(value, dict):
        return {key: _canonicalize_sets(child, set_paths, path + (key,))
                for key, child in value.items()}
    if not isinstance(value, list):
        return value
    items = [_canonicalize_sets(child, set_paths, path + ('[]',))
             for child in value]
    if path not in set_paths:
        return items
    by_value = {}
    for item in items:
        by_value.setdefault(canonical(item), item)
    return [by_value[key] for key in sorted(by_value)]


def _evidence_ids(value):
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'evidence_ids' and isinstance(child, list):
                found.update(child)
            else:
                found.update(_evidence_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_evidence_ids(child))
    return found


def _normalize_records(collection, entries, aliases, set_paths, payload):
    groups, group_order = {}, []
    for temporary_id, item in entries:
        canonical_id = aliases[temporary_id]
        body = _canonicalize_sets(
            _rewrite(item, aliases, payload), set_paths)
        if canonical_id not in groups:
            groups[canonical_id] = []
            group_order.append(canonical_id)
        groups[canonical_id].append((temporary_id, body))
    normalized, findings = [], []
    for canonical_id in group_order:
        group = groups[canonical_id]
        bodies = {}
        for _, body in group:
            bodies.setdefault(canonical(body), body)
        if len(bodies) == 1:
            normalized.append(next(iter(bodies.values())))
            continue
        temporary_ids = [temporary_id for temporary_id, _ in group]
        evidence_ids = {evidence_id for _, body in group
                        for evidence_id in _evidence_ids(body)}
        findings.append(validation_finding(
            'CANONICAL_ID_COLLISION',
            f'Unequal {collection} records resolve to one canonical ID',
            subject_ids=[canonical_id, *temporary_ids],
            evidence_ids=evidence_ids))
    return normalized, findings


def _normalize_payload(payload, aliases, output_type):
    normalized, findings = copy.deepcopy(payload), []
    for collection, record_type in MAPPING_RECORD_TYPES.items():
        if collection not in payload:
            continue
        items, item_findings = _normalize_records(
            collection, sorted(payload[collection].items()), aliases,
            SET_PATHS_BY_TYPE[record_type], payload)
        normalized[collection] = {item['id']: item for item in items}
        findings.extend(item_findings)
    for collection, record_type in SEQUENCE_RECORD_TYPES.items():
        if collection not in payload:
            continue
        entries = [(item['id'], item) for item in payload[collection]]
        normalized[collection], item_findings = _normalize_records(
            collection, entries, aliases,
            SET_PATHS_BY_TYPE[record_type], payload)
        findings.extend(item_findings)
    if findings:
        raise DomainError(
            findings[0]['code'], findings[0]['message'], findings=findings,
            rejected_candidate=copy.deepcopy(payload), repair_kind='semantic')
    validate(normalized, output_type)
    return normalized


def _normalize_ids_with_aliases(payload, graph):
    """Allocate stable semantic IDs and retain the response-local alias map."""
    records = _provider_records(payload)
    aliases = {}
    for collections in DEPENDENCY_GROUPS:
        _allocate_collision_safe_ids(records, collections, graph, aliases)
    output_type = ('VerificationReport' if 'verdict' in payload
                   else 'CandidatePayload')
    return _normalize_payload(payload, aliases, output_type), aliases


def normalize_ids(payload, graph):
    """Allocate stable semantic IDs and rewrite response-local references."""
    normalized, _ = _normalize_ids_with_aliases(payload, graph)
    return normalized


def _candidate_records(candidate):
    """Map every candidate-owned ID to its collection and record body."""
    indexed = {}
    for collection in CANDIDATE_RECORD_COLLECTIONS:
        records = candidate.get(collection, {})
        records = records.values() if isinstance(records, dict) else records
        indexed.update((item['id'], (collection, item)) for item in records)
    return indexed


def normalize_repair_payload(payload, graph, previous, expected_parent_hash):
    """Normalize and validate a complete replacement plus its identity ledger."""
    findings = []
    if payload['parent_candidate_hash'] != expected_parent_hash:
        findings.append(validation_finding(
            'INVALID_REPAIR_PARENT',
            'Repair response does not identify the exact rejected candidate'))

    replacement, aliases = _normalize_ids_with_aliases(
        payload['candidate'], graph)
    previous_records = _candidate_records(previous)
    replacement_records = _candidate_records(replacement)
    previous_owners = {
        record_id: owned[0] for record_id, owned in previous_records.items()}
    replacement_owners = {
        record_id: owned[0] for record_id, owned in replacement_records.items()}
    normalized_changes = []
    claimed_from, claimed_to = set(), set()

    cardinality = {
        'added': lambda before, after: not before and len(after) == 1,
        'retained': lambda before, after: (
            len(before) == len(after) == 1 and before == after),
        'revised': lambda before, after: len(before) == len(after) == 1,
        'retired': lambda before, after: len(before) == 1 and not after,
        'merged': lambda before, after: len(before) >= 2 and len(after) == 1,
        'split': lambda before, after: len(before) == 1 and len(after) >= 2,
    }

    for change in payload['identity_changes']:
        normalized = copy.deepcopy(change)
        normalized['from_ids'] = sorted(set(change['from_ids']))
        normalized['to_ids'] = sorted({
            aliases.get(record_id, record_id)
            for record_id in change['to_ids']
        })
        before, after = normalized['from_ids'], normalized['to_ids']
        subjects = sorted(set(before) | set(after))

        if (len(before) != len(change['from_ids'])
                or len(after) != len(change['to_ids'])):
            findings.append(validation_finding(
                'INVALID_IDENTITY_CHANGE',
                'Identity change cannot repeat a record ID',
                subject_ids=subjects))
        if not normalized['reason'].strip():
            findings.append(validation_finding(
                'INVALID_IDENTITY_CHANGE',
                'Identity change requires a concrete reason',
                subject_ids=subjects))
        if not cardinality[normalized['kind']](before, after):
            findings.append(validation_finding(
                'INVALID_IDENTITY_CHANGE',
                f"{normalized['kind']} identity change has invalid cardinality",
                subject_ids=subjects))

        missing_from = set(before) - set(previous_owners)
        missing_to = set(after) - set(replacement_owners)
        if missing_from or missing_to:
            findings.append(validation_finding(
                'INVALID_IDENTITY_CHANGE',
                'Identity change refers outside its parent or replacement candidate',
                subject_ids=sorted(missing_from | missing_to)))

        collections = {
            previous_owners[record_id]
            for record_id in before if record_id in previous_owners
        } | {
            replacement_owners[record_id]
            for record_id in after if record_id in replacement_owners
        }
        if len(collections) > 1:
            findings.append(validation_finding(
                'INVALID_IDENTITY_CHANGE',
                'Identity change cannot cross semantic collections',
                subject_ids=subjects))

        repeated_from = claimed_from & set(before)
        repeated_to = claimed_to & set(after)
        if repeated_from or repeated_to:
            findings.append(validation_finding(
                'INVALID_IDENTITY_CHANGE',
                'A record identity cannot participate in two changes',
                subject_ids=sorted(repeated_from | repeated_to)))
        claimed_from.update(before)
        claimed_to.update(after)
        normalized_changes.append(normalized)

    removed = set(previous_owners) - set(replacement_owners)
    added = set(replacement_owners) - set(previous_owners)
    modified = {
        record_id for record_id in set(previous_owners) & set(replacement_owners)
        if previous_records[record_id] != replacement_records[record_id]
    }
    transitioned_from = {
        record_id
        for change in normalized_changes if change['kind'] != 'retained'
        for record_id in change['from_ids']
    }
    transitioned_to = {
        record_id
        for change in normalized_changes if change['kind'] != 'retained'
        for record_id in change['to_ids']
    }
    expected_from = removed | modified
    expected_to = added | modified
    if expected_from != transitioned_from:
        findings.append(validation_finding(
            'INCOMPLETE_IDENTITY_CHANGE',
            'Identity ledger must account for every removed or revised parent record',
            subject_ids=sorted(expected_from ^ transitioned_from)))
    if expected_to != transitioned_to:
        findings.append(validation_finding(
            'INCOMPLETE_IDENTITY_CHANGE',
            'Identity ledger must account for every added or revised replacement record',
            subject_ids=sorted(expected_to ^ transitioned_to)))

    if findings:
        first = findings[0]
        raise DomainError(
            first['code'], first['message'], findings=findings,
            rejected_candidate=copy.deepcopy(payload['candidate']),
            repair_kind='semantic')
    return {
        'parent_candidate_hash': payload['parent_candidate_hash'],
        'candidate': replacement,
        'identity_changes': normalized_changes,
    }


def _model_ready_context(model: dict, subject_ids: list[str]) -> dict:
    stage = 'activity'
    context = record('PacketContext')
    # Capability gaps are deterministic graph facts, not provider-side
    # assumptions.  Every complete scope receives them with its obligations.
    context['capabilities'] = copy.deepcopy(model.get('capabilities', []))
    if stage == 'activity':
        anchor_ids = set(subject_ids)
        context['anchors'] = {k:v for k,v in model['anchors'].items() if k in anchor_ids}
        identity_edges = {edge_id for anchor in context['anchors'].values()
            for correspondence in anchor.get('correspondences', [])
            for edge_id in correspondence['relationship_edges']}
        context['traces'] = {k:v for k,v in model['traces'].items() if v['anchor_id'] in anchor_ids}
        obligation_ids = {oid for trace in context['traces'].values() for oid in trace.get('obligation_ids', [])}
        context['trace_obligations'] = {k:v for k,v in model.get('trace_obligations', {}).items() if k in obligation_ids}
        symbols = {s for t in context['traces'].values() for s in t['symbol_ids']}
        symbols.update(representation['symbol_id'] for anchor in context['anchors'].values()
            for representation in anchor.get('representations', [])
            if representation['symbol_id'])
        for edge_id in identity_edges:
            edge = model['edges'][edge_id]
            if edge['from_ref']['kind'] == 'symbol':
                symbols.add(edge['from_ref']['id'])
            if edge['to_ref'] and edge['to_ref']['kind'] == 'symbol':
                symbols.add(edge['to_ref']['id'])
            symbols.update(edge.get('candidate_target_ids', []))
        context['symbols'] = {k:v for k,v in model['symbols'].items() if k in symbols}
        edge_ids = identity_edges | {e for t in context['traces'].values() for e in t['edge_ids']}
        context['edges'] = {k:v for k,v in model['edges'].items() if k in edge_ids}
        context['bindings'] = {k:v for k,v in model['bindings'].items()
                               if any(v[side] and v[side]['id'] in symbols for side in ('source','target'))}
        context['effects'] = {k:v for k,v in model['effects'].items()
                             if set(v['trace_ids']) & set(context['traces'])}
        evidence = {eid for t in context['traces'].values() for eid in t['evidence_ids']}
        evidence.update(eid for anchor in context['anchors'].values()
            for eid in anchor['evidence_ids'])
        evidence.update(eid for anchor in context['anchors'].values()
            for representation in anchor.get('representations', [])
            for eid in representation['evidence_ids'])
        evidence.update(eid for anchor in context['anchors'].values()
            for correspondence in anchor.get('correspondences', [])
            for eid in correspondence['evidence_ids'])
        evidence.update(eid for edge in context['edges'].values() for eid in edge['evidence_ids'])
        evidence.update(eid for obligation in context['trace_obligations'].values() for eid in obligation['evidence_ids'])
        # Include observations nested in the traced source spans, with exact
        # excerpt evidence even when it differs from the enclosing symbol span.
        spans = [model['evidence'][eid]['locator'] for eid in evidence]
        for key, observation in model['rule_observations'].items():
            for eid in observation['evidence_ids']:
                loc = model['evidence'][eid]['locator']
                if any(loc.get('path') == outer.get('path') and
                       loc.get('start_line',0) >= outer.get('start_line',0) and
                       loc.get('end_line',0) <= outer.get('end_line',0) for outer in spans):
                    context['rule_observations'][key] = observation
                    evidence.update(observation['evidence_ids'])
    elif stage == 'grouping':
        selected = set(subject_ids)
        context['activities'] = {k:copy.deepcopy(v) for k,v in model['activities'].items() if k in selected}
        rule_ids = {rid for a in context['activities'].values() for rid in a['rule_ids']}
        context['rules'] = {k:copy.deepcopy(v) for k,v in model['rules'].items() if k in rule_ids}
        observation_ids = {oid for rule in context['rules'].values() for oid in rule['observation_ids']}
        context['rule_observations'] = {k:copy.deepcopy(v) for k,v in model['rule_observations'].items() if k in observation_ids}
        context['information_uses'] = {k:copy.deepcopy(v) for k,v in model['information_uses'].items() if v['activity_id'] in selected}
        concept_ids = {cid for a in context['activities'].values() for cid in a['concept_ids']}
        concept_ids.update(v['concept_id'] for v in context['information_uses'].values())
        concept_ids.update(cid for rule in context['rules'].values() for cid in rule['concept_ids'])
        context['concepts'] = {k:copy.deepcopy(v) for k,v in model['concepts'].items() if k in concept_ids}
        # Grouping proposes boundaries from interpreted behaviors. Referenced
        # evidence remains hash-identified; the later review receives excerpts.
        evidence = set()
    else:
        context['claims'] = {k:copy.deepcopy(v) for k,v in model['claims'].items()
                             if k in subject_ids}
        # Verification input is the claim and its evidence, never a prior
        # verifier verdict. This keeps the semantic checkpoint stable when a
        # verified candidate is revalidated under changed execution code.
        for claim in context['claims'].values():
            claim['semantic_review'] = 'uncertain'
        evidence = {eid for claim in context['claims'].values() for eid in claim['evidence_ids']}
        subjects = {c['subject_id'] for c in context['claims'].values()}
        for collection in ('activities','domains','ownerships','concepts','rules','information_uses','relationships','rule_relationships'):
            context[collection] = {k:v for k,v in model[collection].items() if k in subjects}
        observation_ids = {relation[key] for relation in context['rule_relationships'].values()
                           for key in ('from_observation_id','to_observation_id')}
        context['rule_observations'] = {k:v for k,v in model['rule_observations'].items() if k in observation_ids}
        context['rules'].update({k:v for k,v in model['rules'].items() if observation_ids & set(v['observation_ids'])})
    if stage != 'activity':
        binding_ids = {bid for observation in context['rule_observations'].values()
                       for key in ('input_binding_ids','output_binding_ids','dependency_ids') for bid in observation[key]}
        binding_ids.update(bid for rule in context['rules'].values()
                           for key in ('parameter_binding_ids','dependency_ids') for bid in rule[key])
        context['bindings'] = {k:v for k,v in model['bindings'].items() if k in binding_ids}
    resources = {v['source_id'] for v in context['anchors'].values()}
    resources.update(v['operation']['service_resource_id']
        for v in context['anchors'].values() if v['operation'])
    resources.update(representation['source_id'] for anchor in context['anchors'].values()
        for representation in anchor.get('representations', []))
    resources.update(representation['operation']['service_resource_id']
        for anchor in context['anchors'].values()
        for representation in anchor.get('representations', [])
        if representation['operation'])
    for collection in ('edges', 'bindings'):
        for item in context[collection].values():
            for field in ('from_ref', 'to_ref', 'source', 'target'):
                ref = item.get(field)
                if ref and ref['kind'] == 'resource':
                    resources.add(ref['id'])
    resources.update(effect['target']['id'] for effect in context['effects'].values()
                     if effect['target'] and effect['target']['kind'] == 'resource')
    resources.update(k for k,v in model['resources'].items() if set(v['evidence_ids']) & evidence)
    context['resources'] = {k:v for k,v in model['resources'].items() if k in resources}
    evidence.update(eid for collection in ('bindings', 'effects', 'resources')
                    for item in context[collection].values() for eid in item['evidence_ids'])
    context['evidence'] = {k:v for k,v in model['evidence'].items() if k in evidence}
    snapshots = {v['locator'].get('snapshot_id') for v in context['evidence'].values()}
    context['source_snapshots'] = {k:v for k,v in model['source_snapshots'].items() if k in snapshots}
    if stage == 'activity':
        for oid,observation in model['rule_observations'].items():
            if set(observation['dependency_ids']) & resources:
                context['rule_observations'][oid] = observation
                for eid in observation['evidence_ids']:
                    context['evidence'][eid] = model['evidence'][eid]
                    snapshot_id = model['evidence'][eid]['locator'].get('snapshot_id')
                    if snapshot_id:
                        context['source_snapshots'][snapshot_id] = model['source_snapshots'][snapshot_id]
    _reference_manifest(model,context)
    validate(context, 'PacketContext')
    return context


def _reference_manifest(model,context):
    """Explicit hashes identify referenced records omitted from this packet.

    They establish identity only, never proof of content the model has not
    received. Interpretation cannot promote them to source observations.
    """
    index = {}
    def collect(value,collection):
        if isinstance(value,dict):
            if 'id' in value and len(value) > 2:
                index[value['id']] = (collection,value)
            for child in value.values():
                collect(child,collection)
        elif isinstance(value,list):
            for child in value:
                collect(child,collection)
    for collection,value in model.items():
        if collection != 'record_refs':
            collect(value,collection)
    previous_refs = model.get('record_refs',{})
    context['record_refs'] = {}
    included = set()
    def present(value):
        if isinstance(value,dict):
            if 'id' in value and len(value)>2:
                included.add(value['id'])
            for child in value.values():present(child)
        elif isinstance(value,list):
            for child in value:present(child)
    present(context)
    referenced = set()
    def refs(value):
        if isinstance(value,str) and (value in index or value in previous_refs):
            referenced.add(value)
        elif isinstance(value,dict):
            for child in value.values():refs(child)
        elif isinstance(value,list):
            for child in value:refs(child)
    refs(context)
    context['record_refs'] = {ident:({'id':ident,'collection':index[ident][0],
        'content_hash':digest(index[ident][1])} if ident in index else previous_refs[ident])
        for ident in sorted(referenced-included)}


def fit_packet(packet, max_bytes):
    """Admit a complete scope; limits cannot erase graph or evidence records."""
    if len(canonical(packet)) <= max_bytes:
        return packet
    raise DomainError('PACKET_LIMIT','Complete graph scope exceeds request allowance; previous publication and validated work are preserved')


class Synthesis:
    def __init__(self, root, config, provider, counters, cancelled=lambda:False,
                 heartbeat=lambda:None, recorder=None):
        self.root, self.config, self.provider = Path(root), config, provider
        self.recorder = recorder
        self.counters = counters
        self.cancelled, self.heartbeat = cancelled, heartbeat
        self.deadline = time.monotonic()+config['deadline_seconds']
        self.output_reserved = 0
        self.cache_hits = 0
        self.cache_promotions = 0
        self.stopping = threading.Event()
        self.provider_failure = None
        self.project_instructions = ''
        if provider is None:
            self.agent_config = self._speed_call('config')
            capabilities = normalize_provider_capabilities({key:self.agent_config[key] for key in (
                'provider_context_tokens','provider_max_output_tokens','output_limit_enforcement')})
            if self.agent_config['agent_file']:
                instruction_path = Path(self.agent_config['agent_file'])
                if self.recorder:
                    with self.recorder.boundary('provider.instructions.read',{
                            'path':instruction_path.name}) as boundary:
                        self.project_instructions = instruction_path.read_text(encoding='utf-8')
                        boundary.success(self.project_instructions,
                                         schema='ProviderInstructions')
                else:
                    self.project_instructions = instruction_path.read_text(encoding='utf-8')
            speed_root = AGENTS.parent
            self.provider_hash = digest({'config':self.agent_config,
                'implementation':implementation_hash(Path(__file__),speed_root/'lib/cmd/digest.sh',
                    speed_root/'lib/provider.sh',speed_root/'providers'/(self.agent_config['provider']+'.sh'),
                    *([Path(self.agent_config['agent_file'])] if self.agent_config['agent_file'] else []))})
        else:
            capabilities = injected_provider_capabilities(provider)
            self.provider_hash = provider_fingerprint(provider)
        self.provider_context_tokens = capabilities['provider_context_tokens']
        self.provider_max_output_tokens = capabilities['provider_max_output_tokens']
        self.effective_request_input_tokens = min(
            config['max_request_input_tokens'],
            self.provider_context_tokens or config['max_request_input_tokens'])
        self.effective_request_output_tokens = min(
            config['max_request_output_tokens'],
            self.provider_max_output_tokens or config['max_request_output_tokens'])
        self.counters.update({
            'provider_context_tokens':self.provider_context_tokens,
            'provider_max_output_tokens':self.provider_max_output_tokens,
            'effective_request_input_tokens':self.effective_request_input_tokens,
            'effective_request_output_tokens':self.effective_request_output_tokens,
            'output_limit_enforcement':capabilities['output_limit_enforcement'],
            'token_estimator':(
                f"tiktoken:{POLICY['input_token_encoding']}+exact-provider-projection+"
                f"{POLICY['input_framing_tokens']}-framing"),
        })
        self.agents = agent_instructions()
        self.accounting_lock = threading.RLock()
        self.provider_gate = threading.Condition(self.accounting_lock)
        self.provider_healthy = False
        self.provider_probe_owner = None
        self.provider_generation = 0
        self.provider_recovery_cause = None
        self.provider_recovery_signature = None
        self.provider_open_signature = None
        self.completion_reservations = {}
        self.completion_protected = {'input': 0, 'output': 0}
        self.cached_unit_threads = set()
        self.last_response_keys = {}
        self.last_identity_changes = {}
        self.pending_responses = {}

    def _speed_call(self, action, *args, timeout=30):
        boundary = (self.recorder.boundary(
            'provider.'+action,{'action':action,'argument_count':len(args)})
            if self.recorder else None)
        try:
            value = self._speed_call_unlogged(action,*args,timeout=timeout)
            if boundary:
                boundary.success(value,schema='ProviderResponse')
            return value
        except Exception as exc:
            if boundary:
                boundary.__exit__(type(exc),exc,exc.__traceback__)
            raise

    def _speed_call_unlogged(self, action, *args, timeout=30):
        """Call digest's command-owned provider entry point."""
        if self.is_cancelled():
            raise DomainError('CANCELLED','Discovery cancelled')
        bridge = AGENTS.parent/'lib/cmd/digest.sh'
        with tempfile.TemporaryFile(mode='w+b') as output, tempfile.TemporaryFile(mode='w+b') as errors:
            process = subprocess.Popen(['bash',str(bridge),action,*map(str,args)],
                cwd=self.root,env={**os.environ,'SPEED_PROJECT_ROOT':str(self.root)},
                stdout=output,stderr=errors,start_new_session=True)
            end = time.monotonic()+timeout
            try:
                while process.poll() is None:
                    if self.is_cancelled():
                        raise DomainError('CANCELLED','Discovery cancelled')
                    if time.monotonic() >= end:
                        failure = {'schema_version':1,'category':'timeout','scope':'provider',
                            'retryable':True,'native_status':None,
                            'message':'Provider request timed out','diagnostic_log':None}
                        raise DomainError('PROVIDER_TIMEOUT',failure['message'],retryable=True,
                                          provider_failure=failure)
                    self.heartbeat()
                    try:process.wait(timeout=0.2)
                    except subprocess.TimeoutExpired:pass
                if process.returncode:
                    errors.seek(0)
                    # Drain bridge stderr, but never persist native output. It
                    # may contain credentials, prompts or response bodies.
                    errors.read(self.config['max_artifact_bytes'])
                    output.seek(0)
                    raw_failure = output.read(self.config['max_artifact_bytes']+1)
                    try:
                        failure = json.loads(raw_failure)
                        validate(failure,'ProviderFailure')
                    except (DomainError,ValueError,UnicodeError):
                        failure = {'schema_version':1,'category':'unknown','scope':'provider',
                            'retryable':action != 'config','native_status':f'exit_{process.returncode}',
                            'message':'Provider invocation failed','diagnostic_log':None}
                    logs = self.root/'.speed/logs'
                    logs.mkdir(parents=True,exist_ok=True)
                    path = logs/('business-domain-'+uuid.uuid4().hex+'.log')
                    summary = canonical({'schema_version':1,
                        'category':failure['category'],'scope':failure['scope'],
                        'retryable':failure['retryable'],
                        'native_status':failure['native_status'],
                        'bridge_exit':process.returncode})
                    path.write_bytes(summary[:min(self.config['max_artifact_bytes'],2048)])
                    failure['diagnostic_log'] = str(path.relative_to(self.root))[:512]
                    code = ('PROVIDER_UNAVAILABLE' if action == 'config' else
                            PROVIDER_FAILURE_CODES[failure['category']])
                    if failure['scope'] == 'request' and failure['category'] == 'response_incomplete':
                        code = 'INVALID_PROVIDER_OUTPUT'
                    raise DomainError(code,failure['message'],retryable=failure['retryable'],
                                      provider_failure=failure)
                output.seek(0)
                raw = output.read(self.config['max_artifact_bytes']+1)
                if len(raw)>self.config['max_artifact_bytes']:
                    raise DomainError('INVALID_PROVIDER_OUTPUT','SPEED agent response exceeds artifact allowance')
                try:return json.loads(raw)
                except (ValueError,UnicodeError) as exc:
                    raise DomainError('INVALID_PROVIDER_OUTPUT','SPEED agent returned invalid JSON') from exc
            finally:
                if process.poll() is None:
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGKILL)
                        process.wait()

    def _run_agent(self, request, schema, timeout, role):
        if timeout <= 0:
            raise DomainError('BUILD_TIMEOUT', 'Discovery deadline exceeded')
        attempt_timeout = min(
            max(1, math.ceil(timeout)), self.agent_config['agent_timeout'])
        watchdog_timeout = min(
            timeout, attempt_timeout + self.agent_config['kill_grace'] + 2)
        with tempfile.TemporaryDirectory(prefix='speed-domain-request-') as directory:
            directory = Path(directory)
            (directory/'request.json').write_bytes(canonical(request))
            (directory/'schema.json').write_bytes(canonical(schema))
            value = self._speed_call('agent',
                AGENTS/f'business-domain-{role}.md',
                directory/'request.json',directory/'schema.json',request['model'],
                attempt_timeout,timeout=watchdog_timeout)
            return value,{}  # Shared invoker returns payload; budget reservations remain in force.

    def is_cancelled(self):
        return self.provider_failure is not None or self.stopping.is_set() or self.cancelled()

    def _is_provider_failure(self, exc):
        failure = exc.provider_failure
        if failure is not None:
            return failure['scope'] == 'provider'
        return exc.code in TERMINAL_PROVIDER_CODES | set(POLICY['transient_retry_codes'])

    def _is_retryable_provider_failure(self, exc):
        failure = exc.provider_failure
        if failure is not None:
            return failure['scope'] == 'provider' and failure['retryable']
        return exc.code in POLICY['transient_retry_codes']

    def _can_recover_provider_failure(self, exc):
        """Retry transient failures, or confirm one failure after proven health."""
        return (self._is_provider_failure(exc) and
                (self._is_retryable_provider_failure(exc)
                 or self.provider_generation > 0))

    def _provider_failure_signature(self, exc):
        """Stable build-local identity; variable prose and log paths are excluded."""
        failure = exc.provider_failure
        if failure is None:
            category, native_status = exc.code, None
        else:
            category, native_status = failure['category'], failure['native_status']
        return self.provider_hash, category, native_status

    def _latch_provider_failure(self, cause, blocked_by=None):
        """Open the existing build-scoped gate. Caller holds provider_gate."""
        signature = self._provider_failure_signature(cause)
        repeated = (self.provider_recovery_signature is not None and
                    signature == self.provider_recovery_signature)
        reason = ('repeated equivalent provider failure' if repeated else
                  'terminal provider failure' if blocked_by is None else
                  f'provider recovery blocked by {blocked_by.code}')
        failure = copy.deepcopy(cause.provider_failure)
        # Keep the normalized native/request policy in the provider envelope.
        # The wrapping DomainError is the build-scoped decision and is not
        # retryable inside this attempt.
        self.provider_failure = DomainError(
            'PROVIDER_UNAVAILABLE', f'{reason} ({cause.code}): {cause}',
            retryable=False, provider_failure=failure)
        self.provider_healthy = False
        self.provider_open_signature = signature
        self.stopping.set()
        self.provider_gate.notify_all()

    def _begin_provider_recovery(self, exc):
        """Give one worker ownership of the existing probe/recovery gate."""
        owner = threading.get_ident()
        failure_generation = getattr(exc, '_provider_generation', self.provider_generation)
        if failure_generation < self.provider_generation:
            # This response was dispatched before a successful recovery. Its
            # work may replay once, but it cannot close a second recovery gate.
            return
        if self.provider_probe_owner is None:
            self.provider_healthy = False
            self.provider_probe_owner = owner
        if self.provider_probe_owner == owner and self.provider_recovery_cause is None:
            self.provider_recovery_cause = exc
            self.provider_recovery_signature = self._provider_failure_signature(exc)

    def _request_limits(self, model):
        if self.provider is not None:
            return (self.effective_request_input_tokens,
                    self.effective_request_output_tokens)
        capabilities = self.agent_config['models'].get(model)
        if capabilities is None:
            raise DomainError(
                'INVALID_CONFIG', 'Request model is not a configured digest model')
        capabilities = normalize_provider_capabilities(capabilities)
        return (
            min(self.effective_request_input_tokens,
                capabilities['provider_context_tokens']
                or self.effective_request_input_tokens),
            min(self.effective_request_output_tokens,
                capabilities['provider_max_output_tokens']
                or self.effective_request_output_tokens),
        )

    def packet_allowance(self, operation):
        output_type, role = OPERATIONS[operation]
        prompt = self.agents[role].encode()
        schema = wire_schema(output_type)
        return self.effective_request_input_tokens*3-len(canonical(schema))-len(prompt)-len(canonical({'budget':self.config}))

    def request_for(self, operation, graph, candidate=None,
                    deterministic_findings=(), verification_report=None):
        output_type, _ = OPERATIONS[operation]
        deadline_at = datetime.fromtimestamp(
            time.time() + max(0, self.deadline-time.monotonic()),
            timezone.utc).isoformat()
        request = record(
            'SemanticRequest', request_id=str(uuid.uuid4()), operation=operation,
            input_fingerprint=graph['input_fingerprint'], graph=copy.deepcopy(graph),
            candidate=copy.deepcopy(candidate),
            parent_candidate_hash=(digest(candidate) if candidate is not None else None),
            deterministic_findings=copy.deepcopy(list(deterministic_findings)),
            verification_report=copy.deepcopy(verification_report),
            allowed_evidence_ids=allowed_evidence_ids(graph),
            output_schema={'$ref': f'#/$defs/{output_type}'},
            model=(self.agent_config['model'] if self.provider is None
                   else self.provider.model),
            max_output_tokens=self.effective_request_output_tokens,
            deadline_at=deadline_at)
        validate(request, 'SemanticRequest')
        return request

    def project_exchange(self, request, schema, projection=None):
        """Create the sole compact provider representation."""
        projection = projection or ProviderProjection(request['graph'])
        projection.extend_aliases(
            request['candidate'], request['deterministic_findings'],
            request['verification_report'])
        projected = copy.deepcopy(request)
        projected['graph'] = copy.deepcopy(projection.wire_packet)
        projected['provider_projection'] = {
            'version': projection.VERSION,
            'semantic_hash': projection.semantic_hash,
            'instructions': PROJECTION_INSTRUCTIONS,
        }
        for field in ('candidate', 'deterministic_findings',
                      'verification_report', 'allowed_evidence_ids'):
            projected[field] = projection._rewrite(
                projected[field], projection.aliases)
        return projected, projection.project_schema(schema), projection

    def estimate_input(self, request, schema):
        if request.get('graph', {}).get('format') != ProviderProjection.FORMAT:
            request, schema, _ = self.project_exchange(request, schema)
        if self.project_instructions:
            request = {**request,'project_instructions':self.project_instructions}
        return projected_input_token_estimate(request, schema)

    def _size_graph(self, graph):
        graph = copy.deepcopy(graph)
        estimates = []
        for _ in range(2):
            request = self.request_for('synthesize', graph)
            estimates.append(self.estimate_input(
                semantic_request_identity_input(request),
                wire_schema('CandidatePayload', graph)))
            graph['estimated_input_tokens'] = max(estimates)
            validate(graph, 'GraphScope')
        return graph

    def graph_scope(self, model):
        """Build and size the mandatory whole-graph-first request."""
        selected = _model_ready_context(
            model, sorted(model.get('anchors', {})))
        return self._size_graph(whole_graph_scope(model, selected))

    def run(self, graph: dict, validate_candidate) -> dict:
        """Synthesize, verify and run the bounded semantic repair chain."""
        owner = threading.get_ident() not in self.completion_reservations
        if owner:
            with self.accounting_lock:
                self.completion_reservations[threading.get_ident()] = None
        with self.accounting_lock:
            self.counters['semantic_units_active'] += 1
        try:
            synthesis_request = self.request_for('synthesize', graph)
            initial_findings = None
            try:
                candidate, cached = self._run_with_retries(
                    synthesis_request, allow_candidate_cache=True)
            except DomainError as exc:
                if not (exc.repair_kind == 'semantic' and exc.findings
                        and exc.rejected_candidate is not None):
                    raise
                candidate = exc.rejected_candidate
                cached = False
                initial_findings = exc.findings
            if cached:
                self.cached_unit_threads.add(threading.get_ident())
                result = candidate
            else:
                result = self._validate_verify_repair(
                    graph, synthesis_request, candidate, validate_candidate,
                    initial_findings=initial_findings)
            if owner:
                with self.accounting_lock:
                    self.counters['semantic_units_validated'] += 1
                    self.counters['semantic_units_pending'] = max(
                        0, self.counters['semantic_units_total'] -
                        self.counters['semantic_units_validated'])
                    if threading.get_ident() in self.cached_unit_threads:
                        self.counters['semantic_units_cached'] += 1
            return result
        except DomainError:
            if owner:
                with self.accounting_lock:
                    self.counters['semantic_units_failed'] += 1
            raise
        finally:
            self.last_identity_changes.pop(threading.get_ident(), None)
            with self.accounting_lock:
                self.counters['semantic_units_active'] -= 1
                if owner:
                    self.cached_unit_threads.discard(threading.get_ident())
                    reservation = self.completion_reservations.pop(
                        threading.get_ident(), None)
                    if reservation:
                        for kind in ('input', 'output'):
                            self.completion_protected[kind] -= reservation[kind]
                    self.provider_gate.notify_all()
            # Keep ownership across the probe's bounded retry, but release it
            # on every exit (including local validation failures/cancellation).
            with self.provider_gate:
                if self.provider_probe_owner == threading.get_ident():
                    self.provider_probe_owner = None
                    self.provider_gate.notify_all()

    def _candidate_findings(self, graph, candidate, validate_candidate):
        findings = candidate_scope_findings(graph, candidate)
        try:
            extra = validate_candidate(candidate)
            if extra:
                findings.extend(copy.deepcopy(extra))
        except DomainError as exc:
            findings.extend(exc.findings or [{
                'code': exc.code, 'severity': 'error', 'message': str(exc),
                'subject_ids': ([exc.field]
                                if exc.field and ':' in exc.field else []),
                'evidence_ids': [],
            }])
        return findings

    @staticmethod
    def _repair_subject_closure(candidate, subject_ids):
        """Include candidate records whose content references a named subject."""
        allowed = set(subject_ids)

        def references(value):
            if isinstance(value, str):
                return value in allowed
            if isinstance(value, list):
                return any(references(item) for item in value)
            if isinstance(value, dict):
                return any(references(item) for item in value.values())
            return False

        changed = True
        while changed:
            changed = False
            for collection in CANDIDATE_RECORD_COLLECTIONS:
                records = candidate.get(collection, {})
                records = (records.values()
                           if isinstance(records, dict) else records)
                for item in records:
                    record_id = item['id']
                    if record_id not in allowed and references(item):
                        allowed.add(record_id)
                        changed = True
        return allowed

    @classmethod
    def _repair_regressions(cls, previous, identity_changes,
                            findings, report):
        """Return changed records outside the requested dependency closure."""
        named = {
            subject_id
            for finding in [*(findings or []),
                            *((report or {}).get('findings', []))]
            for subject_id in finding.get('subject_ids', [])
        }
        allowed = cls._repair_subject_closure(previous, named)
        changed = {
            record_id
            for change in identity_changes
            for record_id in change['from_ids']
        }
        return sorted(changed - allowed)

    @staticmethod
    def _finding_signature(findings, report):
        """Stable rejection identity used to detect a stalled repair."""
        return digest({
            'deterministic': sorted(
                (finding['code'], tuple(sorted(finding['subject_ids'])))
                for finding in findings or []),
            'verdict': (report or {}).get('verdict'),
            'blocking': sorted(
                (finding['category'],
                 tuple(sorted(finding['subject_ids'])))
                for finding in (report or {}).get('findings', [])
                if finding['severity'] == 'blocking'),
        })

    @staticmethod
    def _combined_repair_findings(findings, report):
        """Return deterministic findings and independent semantic blockers."""
        combined = copy.deepcopy(findings or [])
        combined.extend(validation_finding(
            'SEMANTIC_VERIFICATION_FAILED', finding['message'],
            subject_ids=finding['subject_ids'],
            evidence_ids=finding['evidence_ids'])
            for finding in (report or {}).get('findings', [])
            if finding['severity'] == 'blocking')
        return combined

    def _validate_verify_repair(self, graph, synthesis_request, candidate,
                                validate_candidate, initial_findings=None):
        findings = (copy.deepcopy(initial_findings)
                    if initial_findings is not None
                    else self._candidate_findings(
                        graph, candidate, validate_candidate))
        verify_request = self.request_for(
            'verify', graph, candidate, findings)
        report, _ = self._run_with_retries(
            verify_request, report_requires_failure=bool(findings))
        verification_key = self.last_response_keys[threading.get_ident()]
        if not findings and report['verdict'] == 'pass':
            self._commit_candidate_response(synthesis_request, verification_key)
            return candidate

        seen = {self._finding_signature(findings, report)}
        for repair_attempt in range(
                1, POLICY['semantic_repair_limit'] + 1):
            repair_request = self.request_for(
                'repair', graph, candidate, findings, report)
            try:
                repaired, _ = self._run_with_retries(repair_request)
            except DomainError as exc:
                if not (exc.repair_kind == 'semantic' and exc.findings
                        and exc.rejected_candidate is not None):
                    raise
                # Identity/canonicalization defects are themselves repairable.
                # The structurally valid raw candidate becomes the exact input
                # to the next round; it is never verified, cached or published.
                repaired = exc.rejected_candidate
                repaired_findings = exc.findings
                repaired_report = report
            else:
                identity_changes = self.last_identity_changes.pop(
                    threading.get_ident(), [])
                repaired_findings = self._candidate_findings(
                    graph, repaired, validate_candidate)
                regressions = self._repair_regressions(
                    candidate, identity_changes, findings, report)
                if regressions:
                    repaired_findings.append(validation_finding(
                        'UNJUSTIFIED_REGRESSION',
                        f'Repair changed {len(regressions)} records outside '
                        'the finding dependency closure',
                        subject_ids=regressions))
                reverify_request = self.request_for(
                    'verify', graph, repaired, repaired_findings)
                repaired_report, _ = self._run_with_retries(
                    reverify_request,
                    report_requires_failure=bool(repaired_findings))
                verification_key = self.last_response_keys[
                    threading.get_ident()]
                if (not repaired_findings
                        and repaired_report['verdict'] == 'pass'):
                    break

            signature = self._finding_signature(
                repaired_findings, repaired_report)
            stalled = signature in seen
            exhausted = repair_attempt == POLICY['semantic_repair_limit']
            if stalled or exhausted:
                reason = ('repeated the same blocking defect set' if stalled
                          else 'reached the configured repair limit')
                raise DomainError(
                    'SEMANTIC_VERIFICATION_FAILED',
                    'Repaired candidate did not pass complete-scope '
                    f'verification after {repair_attempt} repair attempt(s): '
                    f'{reason}',
                    findings=self._combined_repair_findings(
                        repaired_findings, repaired_report),
                    rejected_candidate=repaired,
                    verification_report=repaired_report)
            seen.add(signature)
            candidate, findings, report = (
                repaired, repaired_findings, repaired_report)
        self._commit_candidate_response(repair_request, verification_key)
        # The unchanged whole-graph synthesis request is the stable checkpoint.
        self._commit_or_store_repaired_synthesis(
            synthesis_request, repaired, verification_key)
        return repaired

    def _reserve_completion(self, estimated_input):
        """Protect the complete bounded synthesis/verification repair chain."""
        owner = threading.get_ident()
        if owner not in self.completion_reservations:
            return
        if self.completion_reservations[owner] is not None:
            return
        candidate = self.effective_request_output_tokens
        operations = (4 if self.counters['completion_output_tokens_reserved'] == 0
                      else 2)
        reservation = {
            'input': (4*estimated_input + 4*candidate if operations == 4
                      else 2*estimated_input + candidate),
            'output': operations*self.effective_request_output_tokens,
        }
        if not self._completion_request_fits(estimated_input):
            raise DomainError('PACKET_LIMIT',
                              'Complete semantic repair sequence exceeds the request input allowance')
        while True:
            blocked = False
            for kind in ('input', 'output'):
                used = (self.counters['input_tokens_reserved'] if kind == 'input'
                        else self.output_reserved)
                maximum = self.config[f'max_build_{kind}_tokens']
                if used + reservation[kind] > maximum:
                    raise DomainError(
                        'BUILD_BUDGET',
                        'Complete semantic repair sequence exceeds the remaining build budget')
                blocked |= (used + self.completion_protected[kind]
                            + reservation[kind] > maximum)
            if not blocked:
                break
            remaining = self.deadline-time.monotonic()
            if remaining <= 0:
                raise DomainError('BUILD_TIMEOUT',
                                  'Discovery deadline exceeded while reserving semantic completion')
            self.provider_gate.wait(timeout=min(0.2, remaining))
        self.completion_reservations[owner] = reservation
        for kind in ('input', 'output'):
            self.completion_protected[kind] += reservation[kind]
            field = f'completion_{kind}_tokens_reserved'
            self.counters[field] = max(self.counters[field],
                                       self.completion_protected[kind])

    def _completion_request_fits(self, estimated_input):
        """Require room to resend a candidate plus verifier report for repair."""
        return (estimated_input + 2*self.effective_request_output_tokens
                <= self.effective_request_input_tokens)

    def _consume_completion(self, reservations):
        reservation = self.completion_reservations.get(threading.get_ident())
        if not reservation:
            return
        for kind in ('input', 'output'):
            consumed = min(reservation[kind], reservations[kind])
            reservation[kind] -= consumed
            self.completion_protected[kind] -= consumed

    def _await_provider_gate(self):
        """Pause dispatch while one real request probes or recovers health."""
        owner = threading.get_ident()
        with self.provider_gate:
            while True:
                if self.provider_failure is not None:
                    raise self.provider_failure
                if self.is_cancelled():
                    raise DomainError('CANCELLED', 'Discovery cancelled')
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    if self.provider_recovery_cause is not None:
                        timeout = DomainError('BUILD_TIMEOUT', 'Discovery deadline exceeded')
                        self._latch_provider_failure(self.provider_recovery_cause, timeout)
                        raise self.provider_failure
                    raise DomainError('BUILD_TIMEOUT', 'Discovery deadline exceeded')
                if self.provider_healthy:
                    return
                if self.provider_probe_owner in (None, owner):
                    self.provider_probe_owner = owner
                    return
                self.provider_gate.wait(timeout=min(0.2, remaining))

    @staticmethod
    def _request_key(request):
        return digest(semantic_request_identity_input(request))

    def _cache_identity(self, request, provider_schema):
        request_key = self._request_key(request)
        _, role = OPERATIONS[request['operation']]
        prompt_hash = digest(self.agents[role].encode())
        schema_hash = digest(provider_schema)
        response_key = digest({
            'request_key': request_key,
            'prompt_hash': prompt_hash,
            'output_schema_hash': schema_hash,
            'provider_fingerprint': self.provider_hash,
        })
        return request_key, response_key, prompt_hash, schema_hash

    @staticmethod
    def _citation_findings(value, allowed):
        findings = []
        def walk(item, subject_id=None):
            if isinstance(item, dict):
                subject_id = item.get('id', subject_id)
                for key, child in item.items():
                    if key.endswith('evidence_ids') and isinstance(child, list):
                        invalid = set(child)-allowed
                        if invalid:
                            findings.append({
                                'code': 'INVALID_EVIDENCE',
                                'severity': 'error',
                                'message': 'Provider cited evidence outside its graph scope',
                                'subject_ids': ([subject_id] if subject_id else []),
                                'evidence_ids': sorted(invalid),
                            })
                    walk(child, subject_id)
            elif isinstance(item, list):
                for child in item:
                    walk(child, subject_id)
        walk(value)
        return findings

    def _load_cached_response(self, directory, request, response_key,
                              prompt_hash, schema_hash):
        path = directory/(response_key+'.json')
        artifact = read_json(path, self.config['max_artifact_bytes'])
        if not artifact:
            return None
        validate(artifact, 'CacheArtifact')
        request_key = self._request_key(request)
        expected = {
            'key': response_key,
            'request_key': request_key,
            'prompt_hash': prompt_hash,
            'output_schema_hash': schema_hash,
            'provider_fingerprint': self.provider_hash,
        }
        if any(artifact.get(field) != value
               for field, value in expected.items()):
            raise DomainError('INVALID_CACHE', 'Cache fingerprint mismatch')
        stored_request_artifact = read_json(
            directory/(request_key+'.json'),
            self.config['max_artifact_bytes'])
        if not stored_request_artifact:
            raise DomainError('INVALID_CACHE', 'Cached response request is missing')
        validate(stored_request_artifact, 'CacheArtifact')
        stored_request = stored_request_artifact['request']
        if (stored_request_artifact['key'] != request_key
                or self._request_key(stored_request) != request_key):
            raise DomainError('INVALID_CACHE', 'Cached request key is invalid')
        response = artifact['response']
        if (response['request_id'] != stored_request['request_id']
                or response['operation'] != request['operation']
                or response['input_fingerprint'] != request['input_fingerprint']):
            raise DomainError('INVALID_CACHE',
                              'Cached response does not match its semantic request')
        payload = (response['verification_report']
                   if request['operation'] == 'verify'
                   else response['candidate'])
        findings = self._citation_findings(
            payload, set(request['allowed_evidence_ids']))
        if request['operation'] == 'verify':
            findings.extend(verification_report_findings(
                request['graph'], payload))
            if artifact['verification_response_key'] is not None:
                findings.append({
                    'code': 'INVALID_CACHE', 'severity': 'error',
                    'message': 'Verifier cache entry cannot link to another verifier',
                    'subject_ids': [], 'evidence_ids': [],
                })
        else:
            link = artifact['verification_response_key']
            if not link:
                findings.append({
                    'code': 'INVALID_CACHE', 'severity': 'error',
                    'message': 'Candidate cache entry has no verifier linkage',
                    'subject_ids': [], 'evidence_ids': [],
                })
            else:
                linked = read_json(
                    directory/(link+'.json'),
                    self.config['max_artifact_bytes'])
                if not linked:
                    findings.append({
                        'code': 'INVALID_CACHE', 'severity': 'error',
                        'message': 'Linked verifier cache entry is missing',
                        'subject_ids': [], 'evidence_ids': [],
                    })
                else:
                    validate(linked, 'CacheArtifact')
                    linked_response = linked['response']
                    linked_request_artifact = read_json(
                        directory/(linked['request_key']+'.json'),
                        self.config['max_artifact_bytes'])
                    if not linked_request_artifact:
                        findings.append({
                            'code': 'INVALID_CACHE', 'severity': 'error',
                            'message': 'Linked verifier request is missing',
                            'subject_ids': [], 'evidence_ids': [],
                        })
                    else:
                        validate(linked_request_artifact, 'CacheArtifact')
                        linked_request = linked_request_artifact['request']
                        report = linked_response['verification_report']
                        if (linked['key'] != link
                                or linked_response['operation'] != 'verify'
                                or linked_response['request_id']
                                != linked_request['request_id']
                                or linked_request['candidate'] != payload
                                or report['verdict'] != 'pass'):
                            findings.append({
                                'code': 'INVALID_CACHE', 'severity': 'error',
                                'message': 'Candidate verifier linkage does not pass for the exact candidate',
                                'subject_ids': [], 'evidence_ids': [],
                            })
                        else:
                            findings.extend(verification_report_findings(
                                request['graph'], report))
        if findings:
            raise DomainError(
                findings[0]['code'], findings[0]['message'], findings=findings)
        self.cache_hits += 1
        self.last_response_keys[threading.get_ident()] = response_key
        return copy.deepcopy(payload)

    def _store_request(self, directory, request, request_key):
        artifact = {
            'schema_version': 1, 'kind': 'request', 'key': request_key,
            'created_at': now(), 'request': copy.deepcopy(request),
        }
        validate(artifact, 'CacheArtifact')
        boundary = (self.recorder.boundary('semantic.cache.write',artifact,
                    metadata={'kind':'request'}) if self.recorder else None)
        try:
            atomic_write(directory/(request_key+'.json'), artifact,
                         self.config['max_artifact_bytes'])
            if boundary:
                boundary.success({'written':True},artifact=
                    '.speed/context/business-domain-cache/'+request_key+'.json')
        except Exception as exc:
            if boundary: boundary.__exit__(type(exc),exc,exc.__traceback__)
            raise

    def _store_response(self, directory, metadata, verification_key):
        artifact = {
            'schema_version': 1, 'kind': 'response',
            'key': metadata['response_key'], 'created_at': now(),
            'request_key': metadata['request_key'],
            'prompt_hash': metadata['prompt_hash'],
            'output_schema_hash': metadata['schema_hash'],
            'provider_fingerprint': self.provider_hash,
            'validated_at': now(),
            'verification_response_key': verification_key,
            'response': copy.deepcopy(metadata['response']),
        }
        validate(artifact, 'CacheArtifact')
        boundary = (self.recorder.boundary('semantic.cache.write',artifact,
                    metadata={'kind':'response'}) if self.recorder else None)
        try:
            atomic_write(directory/(metadata['response_key']+'.json'), artifact,
                         self.config['max_artifact_bytes'])
            if boundary:
                boundary.success({'written':True},artifact=
                    '.speed/context/business-domain-cache/'+metadata['response_key']+'.json')
        except Exception as exc:
            if boundary: boundary.__exit__(type(exc),exc,exc.__traceback__)
            raise
        self.last_response_keys[threading.get_ident()] = metadata['response_key']

    def _commit_candidate_response(self, request, verification_key,
                                   candidate=None):
        request_key = self._request_key(request)
        metadata = copy.deepcopy(self.pending_responses.get(request_key))
        if metadata is None:
            raise DomainError(
                'INVALID_CACHE',
                'Validated candidate response is unavailable for verifier linkage')
        if candidate is not None:
            metadata['response']['candidate'] = copy.deepcopy(candidate)
            validate(metadata['response'], 'SemanticResponse')
        directory = self.root/'.speed/context/business-domain-cache'
        self._store_response(directory, metadata, verification_key)
        self.pending_responses.pop(request_key, None)

    def _commit_or_store_repaired_synthesis(
            self, request, repaired, verification_key):
        request_key = self._request_key(request)
        metadata = copy.deepcopy(self.pending_responses.get(request_key))
        directory = self.root/'.speed/context/business-domain-cache'
        if metadata is None:
            schema = wire_schema('CandidatePayload', request['graph'])
            _, provider_schema, _ = self.project_exchange(request, schema)
            request_key, response_key, prompt_hash, schema_hash = \
                self._cache_identity(request, provider_schema)
            response = record(
                'SemanticResponse', request_id=request['request_id'],
                operation='synthesize',
                input_fingerprint=request['input_fingerprint'],
                candidate=copy.deepcopy(repaired),
                verification_report=None,
                usage={'input_tokens': None, 'output_tokens': None},
                provider_revision=None, warnings=[])
            metadata = {
                'request_key': request_key, 'response_key': response_key,
                'prompt_hash': prompt_hash, 'schema_hash': schema_hash,
                'response': response,
            }
            self._store_request(directory, request, request_key)
        else:
            metadata['response']['candidate'] = copy.deepcopy(repaired)
        validate(metadata['response'], 'SemanticResponse')
        self._store_response(directory, metadata, verification_key)
        self.pending_responses.pop(request_key, None)

    def _run_with_retries(self, request, allow_candidate_cache=False,
                          report_requires_failure=False):
        transient = 0
        schema_failures = 0
        last_provider_failure = None
        attempt = 0
        while True:
            attempt += 1
            if self.recorder:
                self.recorder.progress('semantic',
                    f"{request['operation'].capitalize()} attempt {attempt} started")
            boundary = (self.recorder.boundary(
                'semantic.'+request['operation'],request,
                metadata={'attempt':attempt}) if self.recorder else None)
            try:
                with self.accounting_lock:
                    if self.provider_failure is not None:
                        raise self.provider_failure
                result = self._run_once(
                    request, allow_candidate_cache,
                    report_requires_failure)
                if boundary:
                    boundary.success(result[0],metadata={
                        'attempt':attempt,'cache_hit':result[1]})
                    self.recorder.progress('semantic',
                        f"{request['operation'].capitalize()} attempt {attempt} accepted"
                        + (' from validated cache' if result[1] else ''))
                return result
            except DomainError as exc:
                if boundary:
                    boundary.__exit__(type(exc),exc,exc.__traceback__)
                    self.recorder.progress('semantic',
                        f"{request['operation'].capitalize()} attempt {attempt} failed ({exc.code})",
                        level='warning')
                with self.accounting_lock:
                    if self.provider_failure is not None:
                        raise self.provider_failure
                    known = last_provider_failure or self.provider_recovery_cause
                    failure = exc.provider_failure
                    if (self.provider is None and failure is not None
                            and failure['scope'] == 'provider'
                            and failure['category'] == 'timeout'):
                        remaining = self.deadline - time.monotonic()
                        if remaining <= 0:
                            blocked = DomainError(
                                'BUILD_TIMEOUT', 'Discovery deadline exceeded')
                            self._latch_provider_failure(exc, blocked)
                            raise self.provider_failure from exc
                        selection = self._speed_call(
                            'retry-model', request['model'], transient,
                            timeout=min(30, remaining))
                        if selection is None:
                            self._latch_provider_failure(exc)
                            raise self.provider_failure from exc
                        previous_model = request['model']
                        next_model = selection['model']
                        _, output_limit = self._request_limits(next_model)
                        self._begin_provider_recovery(exc)
                        request['model'] = next_model
                        request['request_id'] = str(uuid.uuid4())
                        request['max_output_tokens'] = min(
                            request['max_output_tokens'], output_limit)
                        transient += 1
                        last_provider_failure = exc
                        self.counters['retries'] += 1
                        if self.recorder:
                            self.recorder.progress(
                                'provider',
                                f'Timeout on {previous_model}; '
                                f'escalating to {next_model}',
                                level='warning', details={
                                    'operation': request['operation'],
                                    'from_model': previous_model,
                                    'to_model': next_model,
                                })
                        continue
                    cause = (known if known is not None
                             and exc.code in ('BUILD_BUDGET', 'BUILD_TIMEOUT')
                             else exc)
                    recoverable = self._can_recover_provider_failure(cause)
                    terminal = self._is_provider_failure(cause) and not recoverable
                    if (terminal or recoverable and
                            (transient >= POLICY['transient_retry_limit']
                             or cause is not exc)):
                        self._latch_provider_failure(
                            cause, exc if cause is not exc else None)
                        raise self.provider_failure from exc
                    if self._can_recover_provider_failure(exc):
                        self._begin_provider_recovery(exc)
                if (self._can_recover_provider_failure(exc)
                        and transient < POLICY['transient_retry_limit']):
                    transient += 1
                    last_provider_failure = exc
                elif (exc.repair_kind == 'schema'
                      or exc.code in POLICY['schema_repair_codes']):
                    if schema_failures >= POLICY['schema_repair_limit']:
                        raise
                    schema_failures += 1
                    last_provider_failure = None
                else:
                    raise
                with self.accounting_lock:
                    self.counters['retries'] += 1
            except Exception as exc:
                if boundary:
                    boundary.__exit__(type(exc),exc,exc.__traceback__)
                raise

    def _run_once(self, request, allow_candidate_cache=False,
                  report_requires_failure=False):
        if self.is_cancelled():
            raise DomainError('CANCELLED', 'Discovery cancelled')
        if time.monotonic() >= self.deadline:
            raise DomainError('BUILD_TIMEOUT', 'Discovery deadline exceeded')
        validate(request, 'SemanticRequest')
        operation = request['operation']
        request_input_limit, request_output_limit = self._request_limits(
            request['model'])
        if request['max_output_tokens'] > request_output_limit:
            raise DomainError(
                'PACKET_LIMIT',
                'Semantic request exceeds the selected model output allowance')
        output_type, role = OPERATIONS[operation]
        schema = wire_schema(output_type, request['graph'])
        provider_request, provider_schema, projection = self.project_exchange(
            request, schema)
        request_key, response_key, prompt_hash, schema_hash = \
            self._cache_identity(request, provider_schema)
        directory = self.root/'.speed/context/business-domain-cache'

        if operation == 'verify' or allow_candidate_cache:
            cache_boundary = (self.recorder.boundary(
                'semantic.cache',{'operation':operation,
                                  'response_key':response_key})
                if self.recorder else None)
            try:
                cached = self._load_cached_response(
                    directory, request, response_key, prompt_hash, schema_hash)
                if cache_boundary:
                    cache_boundary.success({'hit':cached is not None})
                if cached is not None:
                    if self.recorder:
                        self.recorder.progress('cache',
                            f'{operation.capitalize()} reused a verified cached response')
                    return cached, True
                if self.recorder:
                    self.recorder.progress('cache',
                        f'{operation.capitalize()} cache miss; provider request required')
            except DomainError as exc:
                if cache_boundary:
                    cache_boundary.__exit__(type(exc),exc,exc.__traceback__)
                    self.recorder.progress('cache',
                        f'{operation.capitalize()} cache entry rejected ({exc.code}); provider request required',
                        level='warning')
                pass

        projected_provider = (
            self.provider is None
            or getattr(self.provider, 'accepts_projected_wire', False))
        dispatch_request = provider_request if projected_provider else request
        dispatch_schema = provider_schema if projected_provider else schema
        projected_input = self.estimate_input(provider_request, provider_schema)
        estimated_input = (
            projected_input if projected_provider
            else input_token_estimate(dispatch_request, dispatch_schema))
        reservations = {
            'input': estimated_input,
            'output': request['max_output_tokens'],
        }
        if estimated_input > request_input_limit:
            raise DomainError(
                'PACKET_LIMIT', 'Semantic request exceeds request input allowance')
        with self.accounting_lock:
            self._await_provider_gate()
            if self.provider_failure is not None:
                raise self.provider_failure
            self._reserve_completion(projected_input)
            self._consume_completion(reservations)
            for kind in ('input', 'output'):
                used = (self.counters['input_tokens_reserved']
                        if kind == 'input' else self.output_reserved)
                if (used + self.completion_protected[kind]
                        + reservations[kind]
                        > self.config[f'max_build_{kind}_tokens']):
                    raise DomainError(
                        'BUILD_BUDGET', 'Discovery token budget exhausted')
            self.counters['input_tokens_reserved'] += reservations['input']
            self.output_reserved += reservations['output']
            self.counters['requests'] += 1
            generation = self.provider_generation

        remaining = self.deadline-time.monotonic()
        if remaining <= 0:
            raise DomainError('BUILD_TIMEOUT', 'Discovery deadline exceeded')
        provider_boundary = (self.recorder.boundary(
            'provider.generate',dispatch_request,
            metadata={'operation':operation,'model':request['model'],
                      'input_limit':request_input_limit,
                      'output_limit':request['max_output_tokens']})
            if self.recorder else None)
        if self.recorder:
            self.recorder.progress('provider',
                f"Sending {operation} request to {request['model']}")
        try:
            value, usage = (
                self.provider.generate(
                    dispatch_request, dispatch_schema, remaining,
                    self.is_cancelled, self.heartbeat)
                if self.provider is not None else
                self._run_agent(
                    provider_request, provider_schema, remaining, role))
            if provider_boundary:
                provider_boundary.success(
                    {'response':value,'usage':usage},schema='ProviderExchange')
                self.recorder.progress('provider',
                    f'{operation.capitalize()} response received')
        except Exception as exc:
            if provider_boundary:
                provider_boundary.__exit__(type(exc),exc,exc.__traceback__)
            if isinstance(exc,DomainError):
                exc._provider_generation = generation
            raise

        with self.provider_gate:
            if self.provider_failure is not None:
                raise self.provider_failure
            if self.provider_probe_owner == threading.get_ident():
                self.provider_healthy = True
                self.provider_probe_owner = None
                self.provider_generation += 1
                self.provider_recovery_cause = None
                self.provider_recovery_signature = None
                self.provider_gate.notify_all()

        actual = usage.get('last', {})
        exceeded = False
        with self.accounting_lock:
            for kind in ('input', 'output'):
                tokens = actual.get(kind+'Tokens')
                if tokens is not None:
                    if type(tokens) is not int or tokens < 0:
                        raise DomainError(
                            'INVALID_PROVIDER_USAGE',
                            'Provider returned invalid token usage')
                    field = kind+'_tokens_reported'
                    self.counters[field] = (self.counters[field] or 0)+tokens
                    adjustment = tokens-reservations[kind]
                    if kind == 'input':
                        self.counters['input_tokens_reserved'] += adjustment
                    else:
                        self.output_reserved += adjustment
                    exceeded |= tokens > (
                        request_input_limit if kind == 'input'
                        else request['max_output_tokens'])
        if exceeded:
            raise DomainError(
                'PROVIDER_BUDGET',
                'Provider exceeded per-request token allowance')

        findings = validation_findings(
            value, dispatch_schema, 'ProviderOutput',
            'INVALID_PROVIDER_OUTPUT')
        if findings:
            raise DomainError(
                'INVALID_PROVIDER_OUTPUT', findings[0]['message'],
                findings=findings, rejected_candidate=value,
                repair_kind='schema')
        normalization = (self.recorder.boundary(
            'semantic.normalize',value,metadata={'operation':operation})
            if self.recorder else None)
        if self.recorder:
            self.recorder.progress('semantic',
                f'Normalizing and validating {operation} response')
        try:
            identity_changes = []
            if projected_provider:
                value = projection.decode_response(value)
            payload = from_wire(value, DEFINITIONS[output_type])
            validate(payload, output_type)
            if output_type == 'RepairPayload':
                repair = normalize_repair_payload(
                    payload, request['graph'], request['candidate'],
                    request['parent_candidate_hash'])
                payload = repair['candidate']
                identity_changes = repair['identity_changes']
                self.last_identity_changes[threading.get_ident()] = \
                    identity_changes
                validate(payload, 'CandidatePayload')
            else:
                payload = normalize_ids(payload, request['graph'])
                validate(payload, output_type)
            if normalization:
                normalization.success(
                    payload,
                    schema=('CandidatePayload'
                            if output_type == 'RepairPayload'
                            else output_type))
        except (KeyError, TypeError, ValueError, DomainError) as exc:
            error = (exc if isinstance(exc,DomainError) else DomainError(
                'INVALID_PROVIDER_OUTPUT',
                'Provider output cannot be decoded into the canonical contract',
                findings=[{
                    'code': 'INVALID_PROVIDER_OUTPUT', 'severity': 'error',
                    'message': 'Provider output cannot be decoded into the canonical contract',
                    'subject_ids': [], 'evidence_ids': [],
                }],
                rejected_candidate=value, repair_kind='schema'))
            if normalization:
                normalization.__exit__(type(error),error,error.__traceback__)
            if error is exc:
                raise
            raise error from exc

        contract_findings = self._citation_findings(
            payload, set(request['allowed_evidence_ids']))
        if output_type == 'VerificationReport':
            contract_findings.extend(
                verification_report_findings(request['graph'], payload))
            if report_requires_failure and payload['verdict'] == 'pass':
                contract_findings.append({
                    'code': 'INVALID_REVIEW', 'severity': 'error',
                    'message': 'Verifier passed a deterministically invalid candidate',
                    'subject_ids': [], 'evidence_ids': [],
                })
        if contract_findings:
            raise DomainError(
                contract_findings[0]['code'],
                contract_findings[0]['message'],
                findings=contract_findings, rejected_candidate=payload,
                repair_kind='schema')

        response = record(
            'SemanticResponse', request_id=request['request_id'],
            operation=operation,
            input_fingerprint=request['input_fingerprint'],
            candidate=(copy.deepcopy(payload)
                       if output_type in ('CandidatePayload', 'RepairPayload')
                       else None),
            verification_report=(
                copy.deepcopy(payload)
                if output_type == 'VerificationReport' else None),
            identity_changes=copy.deepcopy(identity_changes),
            usage={
                'input_tokens': actual.get('inputTokens'),
                'output_tokens': actual.get('outputTokens'),
            },
            provider_revision=None, warnings=[])
        validate(response, 'SemanticResponse')
        self._store_request(directory, request, request_key)
        metadata = {
            'request_key': request_key, 'response_key': response_key,
            'prompt_hash': prompt_hash, 'schema_hash': schema_hash,
            'response': response,
        }
        if operation == 'verify':
            self._store_response(directory, metadata, None)
        else:
            self.pending_responses[request_key] = metadata
            self.last_response_keys[threading.get_ident()] = response_key
        return payload, False
