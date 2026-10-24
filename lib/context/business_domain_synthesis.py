"""Run provider synthesis over evidence packets, normalize the output and cache validated results."""
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
from dataclasses import dataclass
from pathlib import Path
from .business_domain_schema import (
    DEFINITIONS, REFERENCE_TARGETS, COLLECTIONS, DomainError, atomic_write, canonical, digest, identifier,
    now, read_json, record, validate, validate_references, implementation_hash,
    validation_finding, validation_findings, candidate_scope_findings,
    verification_report_findings, activity_closure, information_use_closure,
    required_scope_subjects,
)
from .business_domain_work import (
    SEMANTIC_COLLECTIONS, UNFOCUSED, repair_focus, restore_unseen_incorporations,
    whole_graph_scope)

AGENTS = Path(__file__).resolve().parents[2]/'agents'
POLICY = json.loads(Path(__file__).with_name('business_domain_policies.json').read_text())
TERMINAL_PROVIDER_CODES = frozenset({'PROVIDER_UNAVAILABLE', 'PROVIDER_CAPABILITY_UNAVAILABLE'})


DEADLINE_EXCEEDED = ('Discovery deadline exceeded. Raise deadline_seconds under '
                     '[business_domains] in the project speed.toml and run again.')

def _budget_error(kind, reserved, needed, maximum):
    """A BUILD_BUDGET error that says which budget ran out and how to raise it."""
    setting = f'max_build_{kind}_tokens'
    return DomainError('BUILD_BUDGET', (
        f'Discovery {kind}-token budget exhausted: the next request needs '
        f'{needed:,} {kind} tokens but {reserved:,} of {setting} = {maximum:,} are '
        f'already reserved. Raise {setting} under [business_domains] in the '
        'project speed.toml and run again.'))
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
PROVIDER_PROJECTION_VERSION = 2


def allowed_evidence_ids(packet):
    """Return the evidence IDs the provider may cite."""
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
    """Compact, lossless encoding of a packet for the provider.

    Storage metadata the provider doesn't need is kept in a local sidecar and
    restored on decode. The canonical packet is never changed.
    """
    FORMAT = 'speed-domain-wire'
    VERSION = PROVIDER_PROJECTION_VERSION
    _OMITTED_EVIDENCE_FIELDS = ('content_hash', 'extractor', 'extractor_version')
    _OMITTED_LOCATOR_FIELDS = ('source_hash', 'snapshot_id', 'pointer')

    def __init__(self, packet, focus=None, referenced=()):
        """Project `packet`; with `focus`, send only those context records.

        Aliases are numbered over the whole packet either way, so `_ref:N`
        names the same record in focused and complete requests. Records left
        out of the focus go to the sidecar; any that the sent records or
        `referenced` still mention are sent as identity-only record_refs.
        """
        self.packet = copy.deepcopy(packet)
        self.canonical_hash = digest(self.packet)
        self.counts = _projection_counts(self.packet)
        semantic, self.sidecar = self._semantic_packet(self.packet)
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
        self.omitted_records = 0
        self.visible_evidence = None
        if focus is not None:
            self._focus(semantic, set(focus), set(referenced))
        self.semantic_hash = digest(semantic)
        aliased = self._rewrite(semantic, self.aliases)
        self.wire_packet = self._pack(aliased)
        # Check the round trip now, before sizing or dispatch.
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
        # A record_ref's hash only proves identity locally; the provider can't
        # use it, and every hash is a long unique string.
        sidecar['record_refs'] = {
            record_id: reference.pop('content_hash')
            for record_id, reference in context.get('record_refs', {}).items()
            if 'content_hash' in reference}
        # Send embedded anchor records as IDs; the full records are already in
        # the top-level indexes.
        if ('anchor_representations' in context
                and 'anchor_correspondences' in context):
            for anchor in context.get('anchors', {}).values():
                anchor['representations'] = [
                    value['id'] for value in anchor['representations']]
                anchor['correspondences'] = [
                    value['id'] for value in anchor['correspondences']]
        return value, sidecar

    def _focus(self, semantic, keep, referenced):
        """Move context records outside `keep` to the sidecar."""
        context = semantic['context']
        omitted = {}
        for collection, records in context.items():
            if collection in UNFOCUSED or not isinstance(records, dict):
                continue
            dropped = {record_id: item for record_id, item in records.items()
                       if record_id not in keep}
            if dropped:
                context[collection] = {record_id: item for record_id, item in records.items()
                                       if record_id in keep}
                omitted[collection] = dropped
        references = context.get('record_refs', {})
        sent = {key: value for key, value in semantic.items() if key != 'context'}
        sent['context'] = {key: value for key, value in context.items()
                           if key != 'record_refs'}
        mentioned = set(self._strings(sent)) | referenced
        stubs = {record_id: {'id': record_id, 'collection': collection}
                 for collection, records in omitted.items()
                 for record_id in records if record_id in mentioned}
        unmentioned = {record_id: reference for record_id, reference in references.items()
                       if record_id not in mentioned}
        context['record_refs'] = {
            **{record_id: reference for record_id, reference in references.items()
               if record_id in mentioned},
            **stubs}
        self.sidecar['focus'] = {'omitted': omitted, 'record_refs': unmentioned,
                                 'stubs': sorted(stubs)}
        self.omitted_records = sum(len(records) for records in omitted.values())
        self.visible_evidence = set(context.get('evidence', {})) | {
            record_id for record_id, reference in context['record_refs'].items()
            if reference['collection'] == 'evidence'}
        gaps = _packet_reference_gaps(semantic, _record_ids(semantic))
        if gaps:
            raise DomainError('INVALID_REFERENCE',
                              'Focused provider projection left a reference unresolved',
                              sorted(gaps)[0])

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
        focus = self.sidecar.get('focus')
        if focus is not None:
            references = context.get('record_refs', {})
            for record_id in focus['stubs']:
                if record_id not in references:
                    raise DomainError('INVALID_ARTIFACT',
                                      'Provider projection lost a focus reference', record_id)
                del references[record_id]
            references.update(copy.deepcopy(focus['record_refs']))
            for collection, records in focus['omitted'].items():
                context[collection].update(copy.deepcopy(records))
        for record_id, content_hash in self.sidecar['record_refs'].items():
            reference = context.get('record_refs', {}).get(record_id)
            if reference is None:
                raise DomainError('INVALID_ARTIFACT',
                                  'Provider projection lost a record reference', record_id)
            reference['content_hash'] = content_hash
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

    def extend_aliases(self, *values, registry=None):
        """Alias request-owned records that aren't in the graph.

        With a run-level registry, a record keeps the same alias across requests.
        """
        identifiers = set()
        for value in values:
            identifiers.update(_record_ids(value))
        additions = sorted(identifiers - set(self.aliases))
        offset = len(self.aliases)
        if registry is not None:
            numbers = registry.assign(additions, offset)
            aliases = {identifier: f'_ref:{numbers[identifier]}'
                       for identifier in additions}
        else:
            aliases = {identifier: f'_ref:{offset + index}'
                       for index, identifier in enumerate(additions)}
        self.aliases.update(aliases)
        self.canonical_ids.update(
            {alias: identifier for identifier, alias in aliases.items()})

    def decode_response(self, value):
        return self._rewrite(copy.deepcopy(value), self.canonical_ids)


class AliasRegistry:
    """Run-level ``_ref:N`` numbers for records outside the graph.

    The provider cites these numbers in prose, which normalization can't rewrite,
    so a number has to keep pointing at the same record across repairs. Numbers
    are never reused and only move to a new ID through ``inherit``.
    """

    def __init__(self):
        self.numbers: dict[str, int] = {}
        self.next_number: int | None = None
        self.lock = threading.Lock()

    def assign(self, identifiers, first_number):
        """Return the number of every identifier, numbering new ones in order."""
        with self.lock:
            if self.next_number is None or self.next_number < first_number:
                self.next_number = first_number
            for identifier in identifiers:
                if identifier not in self.numbers:
                    self.numbers[identifier] = self.next_number
                    self.next_number += 1
            return {identifier: self.numbers[identifier]
                    for identifier in identifiers}

    def inherit(self, previous_id, record_id):
        """Move a re-identified record's number to its new identity."""
        with self.lock:
            if previous_id in self.numbers and record_id not in self.numbers:
                self.numbers[record_id] = self.numbers.pop(previous_id)
                return True
            return False


PROJECTION_INSTRUCTIONS = (
    'The packet uses speed-domain-wire version 2. Decode root recursively: '
    'an array beginning null is a list; an array beginning -1 is an ID-keyed '
    'record map; any other array begins with layout index L and is an object '
    'whose sorted field names are layouts[L]. A nonnegative integer N is '
    'strings[N]; a negative integer -N-2 is the original nonnegative integer. '
    'Values named _ref:N are stable aliases '
    'for supplied record IDs. Reuse those aliases exactly in response reference '
    'fields. New semantic record IDs must use their contract prefix and must not '
    'use _ref:. Storage-only snapshot and integrity metadata, including '
    'record_refs content hashes, is intentionally local. Anchor '
    'representation/correspondence arrays contain IDs into their complete '
    'top-level maps.'
)
COMPLETE_PACKET_INSTRUCTIONS = ' Every semantic graph record and evidence excerpt is present.'
FOCUSED_PACKET_INSTRUCTIONS = (
    ' This repair packet is focused on the findings. It supplies in full the '
    'records the findings name or cite, the graph records that the candidate '
    'records you may change rest on, the records one reference away from '
    'those, whole traces, and the evidence all of them cite. The rest of the '
    'scope was already validated and is left out to save input; a left-out '
    'record that something still references is listed in context.record_refs '
    'with its ID and collection only. A left-out record is not missing, '
    'unsupported or retired: keep every reference to it exactly as the '
    'candidate has it, and do not remove, retire, revise or mark unresolved '
    'anything because its content is not shown. New citations must come from '
    'context.evidence. Change only what the findings require, and apply the '
    'completion gate to the records the findings name.'
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
    """Estimate input tokens locally, with a safety margin and framing overhead."""
    import tiktoken
    encoding = tiktoken.get_encoding(POLICY['input_token_encoding'])
    text = canonical({'request':request,'output_schema':schema}).decode('utf-8')
    count = len(encoding.encode(text,disallowed_special=()))
    return math.ceil(count*(100+POLICY['input_token_margin_percent'])/100)+POLICY['input_framing_tokens']


def projected_input_token_estimate(request, schema):
    """Count tokens for the final wire request plus framing."""
    import tiktoken
    encoding = tiktoken.get_encoding(POLICY['input_token_encoding'])
    text = canonical({'request': request, 'output_schema': schema}).decode('utf-8')
    return (len(encoding.encode(text, disallowed_special=())) +
            POLICY['input_framing_tokens'])


def semantic_request_identity_input(request):
    """Drop per-attempt fields (request_id, deadline_at) from a request."""
    return {key: copy.deepcopy(value) for key, value in request.items()
            if key not in ('request_id', 'deadline_at')}


def strict_conditional_variants(schema):
    """Compile if/then rules into anyOf variants for strict-output providers."""
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
    """Return the provider schema for *type_name*, with ID-keyed maps as arrays.

    Strict structured-output APIs can't express arbitrary object keys.
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
                # Strict-output transports don't support this keyword; the canonical
                # validator checks it after decoding.
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
    # Only the review workflow may set a review state, so keep it out of the
    # provider schema instead of rejecting it later.
    for name in ('Activity','Ownership','Domain'):
        definition = definitions.get(name)
        if definition and 'review_state' in definition.get('properties',{}):
            definition['properties']['review_state']['enum'] = ['proposed']
    claim = definitions.get('Claim')
    if claim:
        claim['properties']['semantic_review']['enum'] = ['uncertain']
    # An InformationUse must be backed by a resource reachable from a trace.
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
        # A repair produces a whole candidate, so its records may cite the
        # candidate's own records, as a synthesis answer may.
        if type_name == 'RepairPayload':
            produced |= set(DEFINITIONS['CandidatePayload']['properties'])
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
        _constrain_scope_subjects(result, type_name, packet)
    return result


def _constrain_scope_subjects(schema, type_name, packet):
    """Restrict a scope's subject fields to the subjects it must cover.

    Missing subjects aren't caught here; they come back as findings for repair.
    """
    if 'scope_kind' not in packet:
        return
    subjects = sorted(required_scope_subjects(packet))
    if not subjects:
        return
    every = ' Include every one of the enumerated scope subjects exactly once.'
    if type_name == 'VerificationReport':
        checked = schema['properties']['checked_subject_ids']
        checked['items'] = {'type': 'string', 'enum': subjects}
        checked['description'] = (checked.get('description', '') + every).strip()
    elif type_name == 'CandidatePayload':
        dispositions = schema['properties']['dispositions']
        dispositions['description'] = (dispositions.get('description', '') + every).strip()
        # Conditional rules compile to one `anyOf` variant per case.
        disposition = schema['$defs']['ScopeDisposition']
        for variant in disposition.get('anyOf', [disposition]):
            variant['properties']['subject_id']['enum'] = subjects


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
    """Constrain provider-created IDs to the expected prefix for each record type."""
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


def _derive_deterministic_fields(payload, graph):
    """Overwrite provider-supplied fields that can be derived from the graph.

    Activity and information-use traces, bindings and effects are recomputed from
    the accepted traces, and rule/use resolution is capped by trace and
    operation-fact resolution. Doing this before IDs are allocated keeps record
    identity stable. The provider's semantic choices are left alone.
    """
    if not isinstance(payload.get('activities'), dict):
        return payload
    context = (graph or {}).get('context', {})
    if any(key not in context for key in ('traces', 'edges', 'bindings', 'effects')):
        return payload
    payload = copy.deepcopy(payload)
    traces = context['traces']
    model = {key: context[key] for key in ('traces', 'edges', 'bindings', 'effects')}
    model['anchors'] = context.get('anchors', {})
    model['activities'] = payload['activities']
    model['information_uses'] = payload.get('information_uses', {})
    for activity in payload['activities'].values():
        if not set(activity.get('trace_ids', [])) <= set(traces):
            continue
        for field, identifiers in activity_closure(model, activity).items():
            activity[field] = sorted(identifiers)
        # A rule on an incompletely traced activity can't be verified on that trace.
        if any(traces[trace_id]['resolution'] != 'resolved'
               for trace_id in activity['trace_ids']):
            for rule_id in activity.get('rule_ids', []):
                rule = payload.get('rules', {}).get(rule_id)
                if rule is not None and rule.get('enforcement_status') == 'verified_on_trace':
                    rule['enforcement_status'] = 'declared_only'
    for use in model['information_uses'].values():
        activity = payload['activities'].get(use.get('activity_id'))
        if activity is None or not set(activity.get('trace_ids', [])) <= set(traces):
            continue
        try:
            closure = information_use_closure(model, use)
        except DomainError:
            # Leave ungrounded uses as they are; acceptance and Verify report them.
            continue
        for field in ('trace_ids', 'binding_ids', 'effect_ids'):
            use[field] = sorted(closure[field])
        # A use can't be resolved while any of its edges or effects are unresolved
        # (e.g. persistence writes not yet proven complete).
        if use.get('resolution') == 'resolved':
            facts = ([model['edges'][edge_id] for edge_id in sorted(closure['edge_ids'])]
                     + [model['effects'][effect_id]
                        for effect_id in sorted(closure['effect_ids'])])
            open_facts = [fact for fact in facts if fact['resolution'] != 'resolved']
            if open_facts:
                use['resolution'] = ('ambiguous' if all(
                    fact['resolution'] == 'ambiguous' for fact in open_facts)
                    else 'unresolved')
                if not use.get('reason'):
                    reasons = sorted({fact['reason'] for fact in open_facts
                                      if fact.get('reason')})
                    use['reason'] = (
                        f'The operation facts of this use are {use["resolution"]}'
                        + (f': {reasons[0]}' if reasons else '.'))
    # Acceptance rejects a supported activity on an unresolved trace
    # (INVALID_TRACE), so settle it here rather than spend a verify and repair
    # round on it. Activities citing traces outside the graph are left for
    # acceptance to report.
    for activity in payload['activities'].values():
        trace_ids = activity.get('trace_ids') or []
        if (activity.get('support') == 'supported' and trace_ids
                and set(trace_ids) <= set(traces)
                and any(traces[trace_id]['resolution'] != 'resolved'
                        for trace_id in trace_ids)):
            activity['support'] = 'partial'
    return payload


def _normalize_ids_with_aliases(payload, graph):
    """Allocate stable semantic IDs and retain the response-local alias map."""
    payload = _derive_deterministic_fields(payload, graph)
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


def derive_identity_changes(previous, replacement):
    """Return the exact record-level diff for a normalized repair candidate."""
    before = _candidate_records(previous)
    after = _candidate_records(replacement)
    common = set(before) & set(after)
    changed = []

    for record_id in sorted(common):
        before_collection, before_record = before[record_id]
        after_collection, after_record = after[record_id]
        if before_collection != after_collection:
            raise DomainError(
                'INVALID_IDENTITY_CHANGE',
                'A stable candidate record ID cannot change semantic collection',
                record_id)
        if before_record != after_record:
            changed.append(record(
                'IdentityChange', kind='revised',
                from_ids=[record_id], to_ids=[record_id],
                reason=('Record body changed under its stable canonical '
                        'identity.')))

    changed.extend(record(
        'IdentityChange', kind='retired', from_ids=[record_id], to_ids=[],
        reason='Record is absent from the complete replacement candidate.')
        for record_id in sorted(set(before) - set(after)))
    changed.extend(record(
        'IdentityChange', kind='added', from_ids=[], to_ids=[record_id],
        reason='Record is new in the complete replacement candidate.')
        for record_id in sorted(set(after) - set(before)))
    return changed


def normalize_repair_payload(payload, graph, previous, expected_parent_hash):
    """Normalize a repair candidate and derive its identity changes."""
    if payload['parent_candidate_hash'] != expected_parent_hash:
        finding = validation_finding(
            'INVALID_REPAIR_PARENT',
            'Repair response does not identify the exact rejected candidate')
        raise DomainError(
            finding['code'], finding['message'], findings=[finding],
            rejected_candidate=copy.deepcopy(payload['candidate']),
            repair_kind='semantic')

    replacement, provider_ids = _normalize_ids_with_aliases(
        payload['candidate'], graph)
    normalized_changes = derive_identity_changes(previous, replacement)
    return {
        'parent_candidate_hash': payload['parent_candidate_hash'],
        'candidate': replacement,
        'identity_changes': normalized_changes,
        'provider_ids': provider_ids,
    }


def _model_ready_context(model: dict, subject_ids: list[str]) -> dict:
    stage = 'activity'
    context = record('PacketContext')
    # Capability gaps come from the graph and go to every complete scope.
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
        edge_ids = identity_edges | {
            edge_id for trace in context['traces'].values()
            for edge_id in trace['edge_ids']}
        context['edges'] = {k:v for k,v in model['edges'].items() if k in edge_ids}
        # Tracing doesn't follow test or documentation edges, so add tests that
        # exercise traced code and docs that describe a selected anchor.
        traced = {s for t in context['traces'].values() for s in t['symbol_ids']}
        attached = {k: v for k, v in model['edges'].items() if v['to_ref'] and (
            (v['kind'] == 'tests_behavior' and v['to_ref']['id'] in traced)
            or (v['kind'] == 'documents_behavior' and v['to_ref']['kind'] == 'anchor'
                and v['to_ref']['id'] in anchor_ids))}
        context['edges'].update(attached)
        test_symbols = {v['from_ref']['id'] for v in attached.values()
                        if v['kind'] == 'tests_behavior'}
        symbols = {s for t in context['traces'].values() for s in t['symbol_ids']}
        symbols.update(representation['symbol_id'] for anchor in context['anchors'].values()
            for representation in anchor.get('representations', [])
            if representation['symbol_id'])
        for edge in context['edges'].values():
            if edge['from_ref']['kind'] == 'symbol':
                symbols.add(edge['from_ref']['id'])
            if edge['to_ref'] and edge['to_ref']['kind'] == 'symbol':
                symbols.add(edge['to_ref']['id'])
            symbols.update(edge.get('candidate_target_ids', []))
        context['symbols'] = {k:v for k,v in model['symbols'].items() if k in symbols}
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
        # The test's span has its assertions; the edge only cites the call.
        evidence.update(eid for symbol_id in test_symbols
                        for eid in model['symbols'][symbol_id]['evidence_ids'])
        evidence.update(eid for obligation in context['trace_obligations'].values() for eid in obligation['evidence_ids'])
        # Include rule observations nested in traced spans, with their own excerpts.
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
        # Grouping only needs evidence hashes; review gets the excerpts later.
        evidence = set()
    else:
        context['claims'] = {k:copy.deepcopy(v) for k,v in model['claims'].items()
                             if k in subject_ids}
        # Drop prior verdicts so the request (and its checkpoint) stays the same
        # when a verified candidate is revalidated.
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
    """Add hashed refs for referenced records that aren't in the packet.

    The hashes identify records only; they aren't evidence of their content.
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
    """Return the packet if it fits in *max_bytes*, else raise PACKET_LIMIT."""
    if len(canonical(packet)) <= max_bytes:
        return packet
    raise DomainError('PACKET_LIMIT','Complete graph scope exceeds request allowance; previous publication and validated work are preserved')


def _as_returned(graph, candidate):
    return graph, candidate


def _restorable_child_records(graph, findings, report):
    """Return the child records of a reconciliation that no finding names."""
    named = {subject_id
             for finding in [*(findings or []), *((report or {}).get('findings') or [])]
             for subject_id in finding.get('subject_ids') or ()}
    return {record_id for collection in SEMANTIC_COLLECTIONS
            for record_id in graph['context'].get(collection, {})} - named


def _repair_limit(graph):
    """Return the repair limit for a scope.

    Reconciliations usually need more rounds, so they have their own limit.
    """
    if graph.get('scope_kind') == 'reconciliation':
        return POLICY['reconciliation_repair_limit']
    return POLICY['semantic_repair_limit']


@dataclass(frozen=True)
class RepairState:
    """Repair chain state: the rejected candidate and why it was rejected."""
    candidate: dict
    findings: list
    report: dict
    attempts: int
    signatures: tuple


SHUTDOWN = threading.Event()


def _descendants(pid):
    """Return all descendant PIDs of `pid`."""
    table = subprocess.run(['ps', '-Ao', 'pid=,ppid='], capture_output=True,
                           text=True, check=False).stdout
    children = {}
    for line in table.splitlines():
        fields = line.split()
        if len(fields) == 2 and all(field.isdigit() for field in fields):
            children.setdefault(int(fields[1]), []).append(int(fields[0]))
    found, stack = [], [pid]
    while stack:
        for child in children.get(stack.pop(), []):
            found.append(child)
            stack.append(child)
    return found


def _terminate_tree(process, grace=2.0):
    """Kill a provider call and all of its descendants.

    Killing the process group isn't enough because wrappers like `timeout` start
    their own groups. The tree is collected before signalling, since orphaned
    children get re-parented and can't be found afterwards.
    """
    victims = [process.pid, *_descendants(process.pid)]

    def signal_all(signum):
        for pid in victims:
            try:
                os.kill(pid, signum)
            except (ProcessLookupError, PermissionError):
                pass

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    signal_all(signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and _any_alive(victims):
        time.sleep(0.1)
    signal_all(signal.SIGKILL)
    process.wait()


def _any_alive(pids):
    for pid in pids:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            continue
    return False


def request_shutdown():
    """Stop all running syntheses and kill their provider process groups."""
    SHUTDOWN.set()


USAGE_FIELDS = ('inputTokens', 'outputTokens', 'peakInputTokens', 'peakOutputTokens',
                'cacheReadInputTokens', 'cacheCreationInputTokens')
# Parts of the reported input that came from, or went into, the prompt cache.
CACHE_USAGE_FIELDS = {'cacheReadInputTokens': 'input_cache_read_tokens_reported',
                      'cacheCreationInputTokens': 'input_cache_creation_tokens_reported'}


def _reported_usage(path):
    """Return the token usage the provider reported for a request, or None.

    Totals cover all model turns and count against the build budget. Peaks are
    the largest single turn, which is what the per-request limit applies to.
    """
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError, UnicodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in USAGE_FIELDS
            if type(value.get(key)) is int and value[key] >= 0}


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
            # Timeouts don't change the request or the answer, so they shouldn't
            # invalidate cached responses.
            semantic_config = {key: value for key, value in self.agent_config.items()
                               if key not in ('agent_timeout', 'kill_grace')}
            self.provider_hash = digest({'config':semantic_config,
                'implementation':implementation_hash(Path(__file__),speed_root/'lib/cmd/domains.sh',
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
        self.alias_registries = {}
        self.alias_registries_lock = threading.Lock()

    def _speed_call(self, action, *args, timeout=30, env=None):
        boundary = (self.recorder.boundary(
            'provider.'+action,{'action':action,'argument_count':len(args)})
            if self.recorder else None)
        try:
            value = self._speed_call_unlogged(action,*args,timeout=timeout,env=env)
            if boundary:
                boundary.success(value,schema='ProviderResponse')
            return value
        except Exception as exc:
            if boundary:
                boundary.__exit__(type(exc),exc,exc.__traceback__)
            raise

    def _speed_call_unlogged(self, action, *args, timeout=30, env=None):
        """Call the provider bridge script (lib/cmd/domains.sh)."""
        if self.is_cancelled():
            raise DomainError('CANCELLED','Discovery cancelled')
        bridge = AGENTS.parent/'lib/cmd/domains.sh'
        with tempfile.TemporaryFile(mode='w+b') as output, tempfile.TemporaryFile(mode='w+b') as errors:
            process = subprocess.Popen(['bash',str(bridge),action,*map(str,args)],
                cwd=self.root,env={**os.environ,'SPEED_PROJECT_ROOT':str(self.root),
                                   **(env or {})},
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
                    # Drain stderr but never store it; it may contain credentials, prompts or
                    # response bodies.
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
                    _terminate_tree(process)

    def _run_agent(self, request, schema, timeout, role):
        if timeout <= 0:
            raise DomainError('BUILD_TIMEOUT', DEADLINE_EXCEEDED)
        attempt_timeout = min(
            max(1, math.ceil(timeout)), self.agent_config['agent_timeout'])
        watchdog_timeout = min(
            timeout, attempt_timeout + self.agent_config['kill_grace'] + 2)
        with tempfile.TemporaryDirectory(prefix='speed-domain-request-') as directory:
            directory = Path(directory)
            (directory/'request.json').write_bytes(canonical(request))
            (directory/'schema.json').write_bytes(canonical(schema))
            usage_path = directory/'usage.json'
            value = self._speed_call('agent',
                AGENTS/f'business-domain-{role}.md',
                directory/'request.json',directory/'schema.json',request['model'],
                attempt_timeout,timeout=watchdog_timeout,
                env={'SPEED_PROVIDER_USAGE_FILE':str(usage_path)})
            usage = _reported_usage(usage_path)
            return value,({'last':usage} if usage else {})

    def is_cancelled(self):
        return (self.provider_failure is not None or self.stopping.is_set()
                or SHUTDOWN.is_set() or self.cancelled())

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
        """Return True for retryable failures, or any provider failure after a recovery."""
        return (self._is_provider_failure(exc) and
                (self._is_retryable_provider_failure(exc)
                 or self.provider_generation > 0))

    def _provider_failure_signature(self, exc):
        """Identify a failure by provider, category and native status, not message text."""
        failure = exc.provider_failure
        if failure is None:
            category, native_status = exc.code, None
        else:
            category, native_status = failure['category'], failure['native_status']
        return self.provider_hash, category, native_status

    def _latch_provider_failure(self, cause, blocked_by=None):
        """Mark the provider as failed for this build. Caller holds provider_gate."""
        signature = self._provider_failure_signature(cause)
        repeated = (self.provider_recovery_signature is not None and
                    signature == self.provider_recovery_signature)
        reason = ('repeated equivalent provider failure' if repeated else
                  'terminal provider failure' if blocked_by is None else
                  f'provider recovery blocked by {blocked_by.code}')
        failure = copy.deepcopy(cause.provider_failure)
        # Keep the provider failure details; the wrapping error is a build-level
        # decision and isn't retryable.
        self.provider_failure = DomainError(
            'PROVIDER_UNAVAILABLE', f'{reason} ({cause.code}): {cause}',
            retryable=False, provider_failure=failure)
        self.provider_healthy = False
        self.provider_open_signature = signature
        self.stopping.set()
        self.provider_gate.notify_all()

    def _begin_provider_recovery(self, exc):
        """Make this worker the owner of the provider recovery probe."""
        owner = threading.get_ident()
        failure_generation = getattr(exc, '_provider_generation', self.provider_generation)
        if failure_generation < self.provider_generation:
            # Dispatched before the last recovery: it may retry once but can't start
            # another recovery.
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
                    deterministic_findings=(), verification_report=None,
                    focus=None):
        """Build a semantic request; `focus` lists the context records to send.

        The request always carries the whole graph, which validation,
        normalization and caching use. The focus only narrows what the
        projection sends, and it is part of the request, so it is part of the
        cache key.
        """
        output_type, _ = OPERATIONS[operation]
        extra = ({'provider_focus': {'version': 1, 'record_ids': list(focus)}}
                 if focus is not None else {})
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
            deadline_at=deadline_at, **extra)
        if focus is None:
            # record() fills every optional field; an unfocused request has none.
            request.pop('provider_focus', None)
        validate(request, 'SemanticRequest')
        return request

    def alias_registry(self, graph):
        """Return the alias registry for a graph scope."""
        with self.alias_registries_lock:
            return self.alias_registries.setdefault(
                graph['scope_id'], AliasRegistry())

    def _inherit_aliases(self, graph, projection, provider_ids, candidate):
        """Move each re-identified record's alias to its new ID.

        When normalization gives a continued record a new ID and the old one is gone,
        the new ID keeps the ``_ref:N`` number the provider cited.
        """
        registry = self.alias_registry(graph)
        present = set(_candidate_records(candidate))
        inherited = []
        for provider_id, record_id in sorted(provider_ids.items()):
            kind, _, number = provider_id.partition(':')
            previous = (projection.canonical_ids.get(f'_ref:{number}')
                        if number.isdigit() else None) or provider_id
            if (previous == record_id
                    or previous in present
                    or previous.partition(':')[0] != kind
                    or record_id.partition(':')[0] != kind):
                continue
            if registry.inherit(previous, record_id):
                inherited.append((previous, record_id))
        return inherited

    def project_exchange(self, request, schema, projection=None):
        """Build the compact request and schema sent to the provider."""
        focus = (request.get('provider_focus')
                 if request['operation'] == 'repair' else None)
        projection = projection or ProviderProjection(
            request['graph'],
            focus=focus['record_ids'] if focus else None,
            referenced=ProviderProjection._strings([
                request['candidate'], request['deterministic_findings'],
                request['verification_report']]))
        projection.extend_aliases(
            request['candidate'], request['deterministic_findings'],
            request['verification_report'],
            registry=self.alias_registry(request['graph']))
        projected = copy.deepcopy(request)
        projected.pop('provider_focus', None)
        projected['graph'] = copy.deepcopy(projection.wire_packet)
        projected['provider_projection'] = {
            'version': projection.VERSION,
            'semantic_hash': projection.semantic_hash,
            'instructions': PROJECTION_INSTRUCTIONS + (
                FOCUSED_PACKET_INSTRUCTIONS if focus else COMPLETE_PACKET_INSTRUCTIONS),
        }
        provider_schema = projection.project_schema(schema)
        if projection.visible_evidence is not None:
            # Offer only evidence the provider can see: what is sent and what the
            # candidate already cites. Canonical validation keeps the whole set.
            projected['allowed_evidence_ids'] = [
                evidence_id for evidence_id in projected['allowed_evidence_ids']
                if evidence_id in projection.visible_evidence]
            allowed = provider_schema.get('$defs', {}).get('AllowedEvidenceId')
            visible = [alias for alias in (allowed or {}).get('enum', ())
                       if projection.canonical_ids.get(alias, alias)
                       in projection.visible_evidence]
            if visible:
                allowed['enum'] = visible
        for field in ('candidate', 'deterministic_findings',
                      'verification_report', 'allowed_evidence_ids'):
            projected[field] = projection._rewrite(
                projected[field], projection.aliases)
        return projected, provider_schema, projection

    def estimate_input(self, request, schema):
        if request.get('graph', {}).get('format') != ProviderProjection.FORMAT:
            request, schema, _ = self.project_exchange(request, schema)
        if self.project_instructions:
            request = {**request,'project_instructions':self.project_instructions}
        return projected_input_token_estimate(request, schema)

    def _projected_provider(self):
        """Return whether this provider accepts the compact projected wire."""
        return (self.provider is None
                or getattr(self.provider, 'accepts_projected_wire', False))

    def _size_graph(self, graph):
        """Estimate a scope's synthesis request size the same way dispatch does.

        Using the same measure means a scope admitted at planning isn't rejected at
        dispatch.
        """
        graph = copy.deepcopy(graph)
        estimates = []
        for _ in range(2):
            # The estimate is part of the scope and its cache keys, so leave out
            # per-attempt fields like the request ID and deadline.
            request = semantic_request_identity_input(
                self.request_for('synthesize', graph))
            schema = wire_schema('CandidatePayload', graph)
            if self._projected_provider():
                estimates.append(self.estimate_input(request, schema))
            else:
                estimates.append(input_token_estimate(request, schema))
            graph['estimated_input_tokens'] = max(estimates)
            validate(graph, 'GraphScope')
        return graph

    def graph_scope(self, model):
        """Build and size the whole-graph request, which always runs first."""
        selected = _model_ready_context(
            model, sorted(model.get('anchors', {})))
        return self._size_graph(whole_graph_scope(model, selected))

    def run(self, graph: dict, validate_candidate, review=None) -> dict:
        """Synthesize, verify and repair a candidate for one scope.

        `review(graph, candidate)` returns what verification should see, e.g. the
        expanded candidate for a reconciliation. Without it the candidate is verified
        as returned.
        """
        review = review or _as_returned
        owner = threading.get_ident() not in self.completion_reservations
        if owner:
            with self.accounting_lock:
                self.completion_reservations[threading.get_ident()] = None
        with self.accounting_lock:
            self.counters['semantic_units_active'] += 1
        try:
            synthesis_request = self.request_for('synthesize', graph)
            resumed = self._resumed_state(synthesis_request)
            initial_findings = None
            if resumed is not None:
                if self.recorder:
                    self.recorder.progress(
                        'semantic', f'Resuming an interrupted repair chain after '
                        f'{resumed.attempts} repair round(s)')
                # Reserve based on the scope size, not the larger repair request.
                with self.accounting_lock:
                    self._reserve_completion(graph['estimated_input_tokens'],
                                             graph.get('scope_kind'))
                candidate, cached = None, False
            else:
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
            if resumed is not None:
                result = self._repair_chain(
                    graph, synthesis_request, validate_candidate, resumed, review)
            elif cached:
                self.cached_unit_threads.add(threading.get_ident())
                result = candidate
            else:
                result = self._validate_verify_repair(
                    graph, synthesis_request, candidate, validate_candidate,
                    review, initial_findings=initial_findings)
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
            # Hold the gate across the probe's retry and release it on every exit.
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

    def _repair_focus(self, graph, candidate, findings, report, attempt):
        """Return the context records a repair round sends, or None for all.

        Set SPEED_DISCOVER_FOCUSED_REPAIR=0 to always send the whole scope.
        """
        if os.environ.get('SPEED_DISCOVER_FOCUSED_REPAIR', '1') == '0':
            return None
        focus = repair_focus(graph, candidate, findings, report)
        if focus is not None and self.recorder:
            total = sum(len(records) for collection, records in graph['context'].items()
                        if collection not in UNFOCUSED and isinstance(records, dict))
            self.recorder.progress('semantic',
                f'Repair round {attempt} sends {len(focus)} of {total} graph records '
                'its findings need')
        return focus

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
    def _restore_out_of_scope_revisions(cls, previous, repaired,
                                        identity_changes, findings, report):
        """Undo unrequested edits to records outside the findings' closure.

        Revised records outside the closure are restored, along with any retired
        records they reference (transitively) that are also outside it. If a needed
        dependency was retired inside the closure, the record stays revised and is
        left to the regression check.
        """
        named = {
            subject_id
            for finding in [*(findings or []),
                            *((report or {}).get('findings', []))]
            for subject_id in finding.get('subject_ids', [])
        }
        allowed = cls._repair_subject_closure(previous, named)
        seeds = sorted({change['from_ids'][0] for change in identity_changes
                        if change['kind'] == 'revised'} - allowed)
        if not seeds:
            return repaired, identity_changes, []
        before = _candidate_records(previous)
        after = _candidate_records(repaired)

        def references(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, list):
                for item in value:
                    yield from references(item)
            elif isinstance(value, dict):
                for item in value.values():
                    yield from references(item)

        def requirement(record_id, chosen):
            """Return the records needed to restore *record_id*, or None if it can't be."""
            needed, pending = {record_id}, [record_id]
            while pending:
                for reference in references(before[pending.pop()][1]):
                    if (reference in after or reference not in before
                            or reference in needed or reference in chosen):
                        continue
                    if reference in allowed:
                        return None
                    needed.add(reference)
                    pending.append(reference)
            return needed

        chosen: set[str] = set()
        for record_id in seeds:
            needed = requirement(record_id, chosen)
            if needed is not None:
                chosen |= needed
        if not chosen:
            return repaired, identity_changes, []
        restored = sorted(chosen)
        repaired = copy.deepcopy(repaired)
        for record_id in restored:
            collection, body = before[record_id]
            records = repaired[collection]
            if isinstance(records, dict):
                records[record_id] = copy.deepcopy(body)
            elif any(item['id'] == record_id for item in records):
                repaired[collection] = [copy.deepcopy(body) if item['id'] == record_id
                                        else item for item in records]
            else:
                records.append(copy.deepcopy(body))
        return repaired, derive_identity_changes(previous, repaired), restored

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
    def _ignored_findings(before, after, findings, report):
        """Return the named subjects if a repair ignored its findings, else [].

        A repair counts as acting on its findings if it changes a named record or any
        non-claim record. Rewording unrelated claims doesn't count.
        """
        named = {subject_id
                 for finding in [*(findings or []),
                                 *((report or {}).get('findings', []))]
                 if finding.get('severity') in ('error', 'blocking')
                 for subject_id in finding.get('subject_ids', [])}
        if not named:
            return []
        previous, current = _candidate_records(before), _candidate_records(after)
        changed = {record_id for record_id in set(previous) | set(current)
                   if previous.get(record_id) != current.get(record_id)}
        structural = {record_id for record_id in changed
                      if (previous.get(record_id) or current.get(record_id))[0] != 'claims'}
        if changed & named or structural:
            return []
        return sorted(named)

    @staticmethod
    def _finding_signature(findings, report):
        """Return a signature of the rejection, used to detect a stalled repair."""
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
                                validate_candidate, review, initial_findings=None):
        findings = (copy.deepcopy(initial_findings)
                    if initial_findings is not None
                    else self._candidate_findings(
                        graph, candidate, validate_candidate))
        verify_request = self.request_for(
            'verify', *review(graph, candidate), findings)
        report, _ = self._run_with_retries(
            verify_request, report_requires_failure=bool(findings))
        verification_key = self.last_response_keys[threading.get_ident()]
        if not findings and report['verdict'] == 'pass':
            self._commit_candidate_response(synthesis_request, verification_key)
            return candidate
        return self._repair_chain(
            graph, synthesis_request, validate_candidate,
            RepairState(candidate, findings, report, 0,
                        (self._finding_signature(findings, report),)), review)

    def _repair_chain(self, graph, synthesis_request, validate_candidate, state,
                      review=None):
        """Run repair rounds until verification passes, starting from `state`.

        Each rejected round is checkpointed under the synthesis request so an
        interrupted chain can resume. The checkpoint is removed when the chain
        succeeds, stalls or runs out of repairs.

        A repair that ignores its findings isn't verified; the next round gets the
        same findings again. Reconciliation answers contain only changes, so nothing
        is restored or treated as a regression for them.
        """
        review = review or _as_returned
        compact = graph['scope_kind'] == 'reconciliation'
        limit = _repair_limit(graph)
        candidate, findings, report = state.candidate, state.findings, state.report
        seen = set(state.signatures)
        self._checkpoint(synthesis_request, state)
        for repair_attempt in range(
                state.attempts + 1, limit + 1):
            focus = self._repair_focus(graph, candidate, findings, report,
                                       repair_attempt)
            repair_request = self.request_for(
                'repair', graph, candidate, findings, report, focus=focus)
            try:
                try:
                    repaired, _ = self._run_with_retries(
                        repair_request,
                        progress_operation=f'Repair round {repair_attempt}, provider')
                except DomainError as exc:
                    if focus is None or exc.repair_kind != 'schema':
                        raise
                    # The focus can't be what made a valid answer impossible, but
                    # don't risk the round on it: ask again with the whole scope.
                    if self.recorder:
                        self.recorder.progress('semantic',
                            'Focused repair answer was invalid; asking again with the '
                            'whole scope', level='warning')
                    focus = None
                    repair_request = self.request_for(
                        'repair', graph, candidate, findings, report)
                    repaired, _ = self._run_with_retries(
                        repair_request,
                        progress_operation=f'Repair round {repair_attempt}, provider')
            except DomainError as exc:
                if not (exc.repair_kind == 'semantic' and exc.findings
                        and exc.rejected_candidate is not None):
                    raise
                # Identity defects can be repaired too. The raw candidate feeds the next
                # round but is never verified, cached or published.
                repaired = exc.rejected_candidate
                if compact and focus is not None:
                    repaired, _ = restore_unseen_incorporations(
                        candidate, repaired, focus,
                        _restorable_child_records(graph, findings, report))
                repaired_findings = exc.findings
                repaired_report = report
            else:
                identity_changes = self.last_identity_changes.pop(
                    threading.get_ident(), [])
                restored = regressions = []
                if compact and focus is not None:
                    repaired, unseen = restore_unseen_incorporations(
                        candidate, repaired, focus,
                        _restorable_child_records(graph, findings, report))
                    if unseen and self.recorder:
                        self.recorder.progress('semantic',
                            f'Repair dropped {len(unseen)} child records it was not '
                            'shown; they were kept', level='warning',
                            details={'record_ids': unseen})
                if not compact:
                    repaired, identity_changes, restored = \
                        self._restore_out_of_scope_revisions(
                            candidate, repaired, identity_changes, findings, report)
                    regressions = self._repair_regressions(
                        candidate, identity_changes, findings, report)
                if restored and self.recorder:
                    self.recorder.progress('semantic',
                        f'Repair revised {len(restored)} records no finding named; '
                        'their previous content was kept', level='warning',
                        details={'record_ids': restored})
                repaired_findings = self._candidate_findings(
                    graph, repaired, validate_candidate)
                if regressions:
                    repaired_findings.append(validation_finding(
                        'UNJUSTIFIED_REGRESSION',
                        f'Repair changed {len(regressions)} records outside '
                        'the finding dependency closure',
                        subject_ids=regressions))
                ignored = self._ignored_findings(
                    review(graph, candidate)[1], review(graph, repaired)[1],
                    findings, report)
                if ignored:
                    if self.recorder:
                        self.recorder.progress('semantic',
                            'Repair changed none of the records its findings name; '
                            'it was not verified', level='warning')
                    repaired_findings.append(validation_finding(
                        'UNCHANGED_REPAIR',
                        'The repair changed none of the records the findings name '
                        'and no record other than claims; return the records the '
                        'findings require', subject_ids=ignored))
                    repaired_report = report
                else:
                    reverify_request = self.request_for(
                        'verify', *review(graph, repaired), repaired_findings)
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
            exhausted = repair_attempt == limit
            if stalled or exhausted:
                self._discard_checkpoint(synthesis_request)
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
            self._checkpoint(synthesis_request, RepairState(
                candidate, findings, report, repair_attempt, tuple(sorted(seen))))
        self._commit_candidate_response(repair_request, verification_key)
        # Cache the result under the original synthesis request.
        self._commit_or_store_repaired_synthesis(
            synthesis_request, repaired, verification_key)
        self._discard_checkpoint(synthesis_request)
        return repaired

    def _checkpoint_path(self, request):
        return (self.root/'.speed/context/business-domain-pending'
                /f'{self._request_key(request)}.json')

    def _checkpoint(self, request, state):
        artifact = record(
            'PendingRepairArtifact', request_key=self._request_key(request),
            provider_projection_version=ProviderProjection.VERSION,
            provider_fingerprint=self.provider_hash,
            prompt_fingerprint=prompt_fingerprint(),
            updated_at=now(),
            attempts_used=state.attempts,
            attempted_signatures=sorted(state.signatures),
            candidate=state.candidate, findings=state.findings,
            verification_report=state.report)
        validate(artifact, 'PendingRepairArtifact')
        atomic_write(self._checkpoint_path(request), artifact,
                     self.config['max_artifact_bytes'])

    def _discard_checkpoint(self, request):
        self._checkpoint_path(request).unlink(missing_ok=True)

    def _resumed_state(self, request):
        """Return the checkpointed repair state for `request`, if it can resume.

        The checkpoint must match the request, projection, provider and agent
        instructions, and have repairs left. Otherwise it's discarded.
        """
        path = self._checkpoint_path(request)
        artifact = read_json(path, self.config['max_artifact_bytes'])
        if not artifact:
            return None
        try:
            validate(artifact, 'PendingRepairArtifact')
        except DomainError:
            artifact = None
        if (artifact is None
                or artifact['request_key'] != self._request_key(request)
                or artifact['provider_projection_version'] != ProviderProjection.VERSION
                or artifact['provider_fingerprint'] != self.provider_hash
                or artifact['prompt_fingerprint'] != prompt_fingerprint()
                or artifact['attempts_used'] >= _repair_limit(request['graph'])):
            path.unlink(missing_ok=True)
            return None
        return RepairState(artifact['candidate'], artifact['findings'],
                           artifact['verification_report'], artifact['attempts_used'],
                           tuple(artifact['attempted_signatures']))

    def _reserve_completion(self, estimated_input, scope_kind=None):
        """Reserve budget for the full synthesis, verification and repair sequence."""
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
        if not self._completion_request_fits(estimated_input, scope_kind):
            raise DomainError('PACKET_LIMIT',
                              'Complete semantic repair sequence exceeds the request input allowance')
        while True:
            blocked = False
            for kind in ('input', 'output'):
                used = (self.counters['input_tokens_reserved'] if kind == 'input'
                        else self.output_reserved)
                maximum = self.config[f'max_build_{kind}_tokens']
                if used + reservation[kind] > maximum:
                    raise _budget_error(kind, used, reservation[kind], maximum)
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

    def _completion_request_fits(self, estimated_input, scope_kind=None):
        """Return whether a review or repair request for this scope fits.

        It needs room for the scope, the candidate and the response allowance. The
        candidate reserve is sized from the scope, except for reconciliations, which
        get the full allowance. Requests are measured again at dispatch.
        """
        output = self.effective_request_output_tokens
        return (estimated_input + output + self._candidate_reserve(estimated_input, scope_kind)
                <= self.effective_request_input_tokens)

    def _candidate_reserve(self, estimated_input, scope_kind=None):
        """Return the input tokens to reserve for the candidate in a review or repair."""
        output = self.effective_request_output_tokens
        if scope_kind == 'reconciliation':
            return output
        return min(output, max(POLICY['candidate_reserve_floor_tokens'],
                               math.ceil(estimated_input * POLICY['candidate_reserve_fraction'])))

    def sequence_fits(self, graph):
        """Return whether a scope's full semantic sequence fits the limits.

        The sequence is synthesize, verify, repair and verify again.
        """
        return self.sequence_limit(graph) is None

    def sequence_limit(self, graph):
        """Return the name of the limit a scope's sequence would exceed, or None."""
        estimated = graph['estimated_input_tokens']
        output = self.effective_request_output_tokens
        if not self._completion_request_fits(estimated, graph.get('scope_kind')):
            return 'max_request_input_tokens'
        if 4*estimated + 4*output > self.config['max_build_input_tokens']:
            return 'max_build_input_tokens'
        if 4*output > self.config['max_build_output_tokens']:
            return 'max_build_output_tokens'
        return None

    def _consume_completion(self, reservations):
        reservation = self.completion_reservations.get(threading.get_ident())
        if not reservation:
            return
        for kind in ('input', 'output'):
            consumed = min(reservation[kind], reservations[kind])
            reservation[kind] -= consumed
            self.completion_protected[kind] -= consumed

    def _await_provider_gate(self):
        """Wait while another request probes or recovers provider health."""
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
                        timeout = DomainError('BUILD_TIMEOUT', DEADLINE_EXCEEDED)
                        self._latch_provider_failure(self.provider_recovery_cause, timeout)
                        raise self.provider_failure
                    raise DomainError('BUILD_TIMEOUT', DEADLINE_EXCEEDED)
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

    @staticmethod
    def _outcome_summary(operation, payload):
        """Return progress text, severity and details that are safe to log."""
        if operation == 'verify':
            finding_count = len(payload['findings'])
            blocking_count = sum(
                finding['severity'] == 'blocking'
                for finding in payload['findings'])
            verdict = payload['verdict']
            # Log only schema-constrained values; finding messages are provider text
            # and are never logged.
            categories = Counter(
                finding['category'] for finding in payload['findings']
                if finding['severity'] == 'blocking')
            blocking = ', '.join(
                f'{category} x{count}' if count > 1 else category
                for category, count in sorted(categories.items()))
            return {
                'summary': (
                    f'verdict {verdict}, {finding_count} finding(s), '
                    f'{blocking_count} blocking'
                    + (f' ({blocking})' if blocking else '')),
                'level': (
                    'warning'
                    if verdict != 'pass' or blocking_count else 'step'),
                'details': {
                    'verdict': verdict,
                    'finding_count': finding_count,
                    'blocking_finding_count': blocking_count,
                    'findings': [
                        {'category': finding['category'],
                         'severity': finding['severity'],
                         'subject_ids': sorted(finding['subject_ids'])}
                        for finding in payload['findings']],
                },
            }

        counts = {
            name: len(payload[name])
            for name in ('activities', 'rules', 'domains')
            if name in payload}
        return {
            'summary': ', '.join(
                f'{count} {name}' for name, count in counts.items()),
            'level': 'step',
            'details': {'record_counts': counts},
        }

    def _run_with_retries(self, request, allow_candidate_cache=False,
                          report_requires_failure=False,
                          progress_operation=None):
        transient = 0
        schema_failures = 0
        last_provider_failure = None
        attempt = 0
        progress_operation = (
            progress_operation or request.get('operation', 'semantic').capitalize())
        while True:
            attempt += 1
            if self.recorder:
                self.recorder.progress('semantic',
                    f'{progress_operation} attempt {attempt} started')
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
                    outcome = self._outcome_summary(
                        request['operation'], result[0])
                    self.recorder.progress('semantic',
                        f'{progress_operation} attempt {attempt} accepted'
                        + (' from validated cache' if result[1] else '')
                        + (f"; {outcome['summary']}"
                           if outcome['summary'] else ''),
                        level=outcome['level'],
                        details=outcome['details'])
                return result
            except DomainError as exc:
                if boundary:
                    boundary.__exit__(type(exc),exc,exc.__traceback__)
                    self.recorder.progress('semantic',
                        f'{progress_operation} attempt {attempt} failed '
                        f'({exc.code})',
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
                                'BUILD_TIMEOUT', DEADLINE_EXCEEDED)
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
            raise DomainError('BUILD_TIMEOUT', DEADLINE_EXCEEDED)
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

        projected_provider = self._projected_provider()
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
            self._reserve_completion(projected_input, request['graph'].get('scope_kind'))
            self._consume_completion(reservations)
            for kind in ('input', 'output'):
                used = (self.counters['input_tokens_reserved']
                        if kind == 'input' else self.output_reserved)
                if (used + self.completion_protected[kind]
                        + reservations[kind]
                        > self.config[f'max_build_{kind}_tokens']):
                    raise _budget_error(kind, used + self.completion_protected[kind],
                                        reservations[kind],
                                        self.config[f'max_build_{kind}_tokens'])
            self.counters['input_tokens_reserved'] += reservations['input']
            self.output_reserved += reservations['output']
            self.counters['requests'] += 1
            generation = self.provider_generation

        remaining = self.deadline-time.monotonic()
        if remaining <= 0:
            raise DomainError('BUILD_TIMEOUT', DEADLINE_EXCEEDED)
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
                    # The per-request limit applies to each model turn, so check the reported
                    # peak.
                    peak = actual.get('peak'+kind.capitalize()+'Tokens', tokens)
                    exceeded |= peak > (
                        request_input_limit if kind == 'input'
                        else request['max_output_tokens'])
            for usage_field, counter in CACHE_USAGE_FIELDS.items():
                tokens = actual.get(usage_field)
                if type(tokens) is int and tokens >= 0:
                    self.counters[counter] = (self.counters.get(counter) or 0) + tokens
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
                if projected_provider:
                    self._inherit_aliases(request['graph'], projection,
                                          repair['provider_ids'], payload)
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
                'cache_read_input_tokens': actual.get('cacheReadInputTokens'),
                'cache_creation_input_tokens': actual.get('cacheCreationInputTokens'),
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
