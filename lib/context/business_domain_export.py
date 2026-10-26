"""Render a published business-domain model as DDD documents.

`speed discover domains --export ddd` writes Markdown with Mermaid diagrams:
an overview with the context map, one page per bounded context (use cases,
entities, call sequences, rules), a business-rules catalog, a glossary and a
page of gaps. Everything comes from the published model, with no provider
calls and no source reads, and one build always renders the same bytes.

The model is honest about what it could not prove, and so are the documents:
support, enforcement and resolution are shown next to every claim, and
sequence diagrams are labelled as static call paths, not observed runtime.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from .business_domain_schema import DomainError

EXPORT_DIRECTORY = '.speed/context/business-domain-ddd'
MANIFEST = 'manifest.json'

SUPPORT = {'supported': 'backed by code', 'partial': 'partly backed by code',
           'insufficient': 'not enough evidence'}
ENFORCEMENT = {
    'verified_on_trace': 'confirmed on a call path we followed',
    'declared_only': 'written in the code, but not confirmed to run',
    'conditional': 'applies only under some settings',
    'unresolved': 'unknown where or whether this is enforced',
}
PLAIN_STATUS = {'declared_only': 'written but not confirmed to run', 'conditional': 'apply only under some settings',
                'unresolved': 'with unknown enforcement'}
ENFORCEMENT_SHORT = {
    'verified_on_trace': 'confirmed to run',
    'declared_only': 'in code, not confirmed',
    'conditional': 'only under some settings',
    'unresolved': 'enforcement unknown',
}
EVIDENCE = {'supported': 'strong evidence', 'partial': 'some evidence',
            'insufficient': 'little evidence'}
IMPLEMENTATION = {
    'implemented': 'implemented',
    'documented_only': 'described in docs only, no code found',
    'implementation_unresolved': 'code path not fully followed',
}
ACCESS_ORDER = ('creates', 'reads', 'updates', 'deletes', 'references')
SOURCE_PREFERENCE = {'source': 0, 'test': 1, 'configuration': 2}
CATEGORY_ORDER = ('validation', 'authorization', 'eligibility', 'calculation',
                  'state_transition', 'invariant', 'cross_record_constraint',
                  'business_ordering', 'timing', 'technical', 'unclassified')
JPA_ASSOCIATIONS = {'OneToMany': ('1', '*'), 'ManyToOne': ('*', '1'),
                    'ManyToMany': ('*', '*'), 'OneToOne': ('1', '1')}
FIELD_DECLARATION = re.compile(
    r'(?:private|protected|public)\s+(?:static\s+)?(?:final\s+)?'
    r'([\w.]+(?:<[\w.<>, ?]+>)?(?:\[\])?)\s+(\w+)\s*[=;]')
ROLE_PREDICATE = re.compile(r'has(?:Any)?Role\(([^)]*)\)')
ROLE_TOKEN = re.compile(r'\b((?:[A-Z][A-Z0-9]*_)*ADMIN|[A-Z][A-Z0-9]*_[A-Z0-9_]*ROLE)\b')
ACCESSOR = re.compile(r'\.(?:get|is)[A-Z]\w*\(')
NO_ROLE = 'no role named in the code'
CONFLICTING_ROLES = 'no one role named in the code is allowed every step'
MERMAID_ESCAPES = {'#': '#35;', '"': '#quot;', ';': '#59;', '<': '#lt;', '>': '#gt;'}
WRITES = ('creates', 'updates', 'deletes')
ACTIVE_PROFILES = re.compile(r'spring\.profiles\.active\s*=\s*([\w.\-]+(?:\s*,\s*[\w.\-]+)*)')
PROFILE = re.compile(r'@Profile\(\s*"([^"]+)"\s*\)\s+on\s+(\w+)')
ACTIVATES = re.compile(r'activates\s+(\w+)\s*\(@Profile\(\s*"([^"]+)"\s*\)\)')
BUILD_CONFIG = re.compile(r'__\w+__|process\.env|import\.meta\.env|API_SERVER_URL', re.I)
CHANNELS = {'ui': 'web UI', 'http': 'API', 'cli': 'CLI', 'event': 'events', 'message': 'messages',
            'scheduled': 'schedule', 'job': 'batch job'}
ACTORS = {'http': 'API client', 'ui': 'User', 'cli': 'Operator', 'event': 'Event source',
          'message': 'Message source', 'scheduled': 'Scheduler', 'job': 'Scheduler'}
# Sequence diagram limits, sized from PetClinic: after filtering, the largest
# trace has 16 messages and 12 participants.
MAX_MESSAGES = 30
MAX_PARTICIPANTS = 12
MAX_DEPTH = 6
MAX_USE_CASES = 15
SEQUENCE_KINDS = ('calls', 'reads_data', 'writes_data', 'selects_implementation',
                  'routes_to', 'invokes_endpoint')


# Text helpers

CLIENT = '__client__'
# Recurring analysis jargon in model-written prose, with plain words that keep the meaning.
# Order matters: specific phrases come before the general ones they contain.
PLAIN_WORDS = [(re.compile(pattern), replacement) for pattern, replacement in (
    (r'Every cited write use is unresolved, both for transaction commit and for the profile-selected repository\.',
     'For every write listed, it is unknown whether the transaction commits and which repository the active Spring '
     'profile uses.'),
    (r'\b(?:is|are) not (?:established|determined) statically\b', 'cannot be confirmed from the code alone'),
    (r'\b(is|are) not established\b', r'\1 not confirmed'),
    (r'\b(is|are) established statically\b', r'\1 confirmed from the code alone'),
    (r'\bcannot be determined statically\b', 'cannot be confirmed from the code alone'),
    (r'\b(is|are|be) established\b', r'\1 confirmed'),
    (r'Static analysis does not establish whether', 'The code alone does not show whether'),
    (r'\bis unresolved\.', 'is unknown.'),
    (r'\bthe (?:analyzed (?:source(?: snapshot)?|snapshot)|snapshot)\b', 'the code that was analyzed'),
    (r'\(profile-selected VisitRepository insert or update\)',
     '(insert or update by the VisitRepository chosen by the active Spring profile)'),
    (r'the profile-selected repository implementation', 'the repository implementation chosen by the active Spring profile'),
    (r'The profile-selected implementation of (\w+)', r'The implementation of \1 chosen by the active Spring profile'),
    (r'\b([Ww])hich profile-selected repository\b', r'\1hich repository (chosen by the active Spring profile)'),
    (r'\b([Tt])he profile-selected repository\b', r'\1he repository chosen by the active Spring profile'),
    (r'\b([Tt])he profile-selected (\w+)', r'\1he \2 chosen by the active Spring profile'),
    (r'\bon the declared default profile\b', 'on the default profile in the configuration'),
    (r'\bby declared default\b', 'by default'),
    (r'\b([Tt])he declared default\b', r'\1he default setting'),
    (r'\bdeclared default\b', 'default setting'),
    (r'\(the merge candidate\)', '(the suggested merge)'),
    (r'These controllers answer the merge candidates, but they are technical signals and are not the basis of the boundary\.',
     'The boundary is not based on which controller declares the endpoints.'),
    (r'the declared petclinic\.security\.enable=false', 'the petclinic.security.enable=false setting in the configuration'),
    (r'\b([Nn]o (?:role check|server implementation|server read)) is evidenced\b', r'\1 is found in the code'),
    (r'\bno evidenced (PUT )?implementation\b', r'no \1implementation in the code'),
    (r'the evidenced implementation', 'the implementation found in the code'),
    (r'\b([Tt])he verifier reports\b', r'\1he automated check reports'),
    (r'\b(is|are) not among the evidence cited here\b', r'\1 not part of the evidence listed here'),
    (r'\bno evidence IDs? for (that test|them) (?:is|are) available to cite here', r'there is no evidence link for \1 here'),
    (r'\b([Tt])his candidate\b', r'\1his rule'),
    (r'the flush order', 'the order in which the changes are written to the database'),
    (r'reportedly declares', 'is reported to set'),
    (r'would leave this annotation unenforced under the default configuration',
     'would mean this annotation is not enforced in the default configuration'),
    (r'The trace is incomplete', 'The call path is incomplete'),
    (r'could not be listed and are left to derivation', 'could not be listed and still need to be worked out'),
    (r'Four further input bindings reachable through the trace of', 'Four more inputs on the call path of'),
    (r'so their server-side link is unresolved', 'so which server code handles them is unknown'),
    (r'has only a contract representation', 'exists only in the API contract'),
    (r'depends on the runtime entity mapping', 'depends on how the entities are mapped when the app runs'),
    (r'\bno-op UPDATE\b', 'UPDATE that changes nothing'),
    (r'\be\.g\. ', 'for example '),
    (r'\bi\.e\. ', 'that is, '),
    (r"is not part of this anchor's trace", "is not part of this entry point's call path"),
    (r'they are separate anchors and traces', 'they start from separate entry points with separate call paths'),
    (r'from one child scope sit in the same domain as the writers from the other child scopes',
     'in one part of the model sit in the same domain as the writers in the other parts'),
)]
TRACE_WORDS = {'bounded': 'cut short at a size or depth limit', 'incomplete': 'incomplete', 'complete': 'complete',
               'resolved': 'every step confirmed', 'unresolved': 'some steps not confirmed',
               'ambiguous': 'some steps may not happen'}


def unwrap(text: str) -> str:
    """Drop brackets that wrap the whole expression: '((a.b()))' -> 'a.b()'."""
    while text.startswith('(') and text.endswith(')'):
        depth = 0
        for position, char in enumerate(text):
            depth += char == '('
            depth -= char == ')'
            if depth == 0 and position < len(text) - 1:
                return text
        text = text[1:-1].strip()
    return text


def http_status(text: str) -> str:
    """The 4xx status an outcome describes, e.g. 'HTTP 404' or 'NOT_FOUND', else ''."""
    found = re.search(r'\b(4\d\d)\b', text)
    if found:
        return found.group(1)
    for words, code in (('NOT_FOUND', '404'), ('Not Found', '404'), ('BAD_REQUEST', '400'), ('Bad Request', '400')):
        if words in text:
            return code
    return ''


def short(identifier: str) -> str:
    """Return the last eight characters of a record ID, stable across renders."""
    return identifier.rsplit(':', 1)[-1][-8:]


def slug(text: str) -> str:
    value = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
    return value or 'unnamed'


def cell(text) -> str:
    """Make a value safe inside a Markdown table cell."""
    if text is None or text == '':
        return '-'
    return str(text).replace('\\', '\\\\').replace('|', '\\|').replace('\n', ' ').strip()


def code(text) -> str:
    if not text:
        return '-'
    text = str(text).replace('\n', ' ').strip()
    fence = '``' if '`' in text else '`'
    return f'{fence}{text}{fence}'


def label(text) -> str:
    """Make text safe inside a quoted Mermaid label."""
    value = str(text if text is not None else '').replace('\n', ' ').replace('\r', ' ')
    # One pass, so an escape's own '#' and ';' are never escaped again.
    return ''.join(MERMAID_ESCAPES.get(char, char) for char in value).strip()


def node(prefix: str, identifier: str) -> str:
    return prefix + '_' + re.sub(r'[^A-Za-z0-9]', '', short(identifier))


def first_sentence(text: str, limit: int = 220) -> str:
    text = (text or '').strip()
    match = re.match(r'(.+?[.!?])(\s|$)', text)
    sentence = match.group(1) if match else text
    if len(sentence) <= limit:
        return sentence
    return sentence[:limit - 1].rsplit(' ', 1)[0].rstrip(' ,;:(') + '…'


def plural(count: int, word: str) -> str:
    return f'{count} {word}' + ('' if count == 1 else 's')


# Model index

class Model:
    """Read-only indexes over a published model, sorted for stable output."""

    def __init__(self, model: dict):
        self.raw = model
        self.symbols = model.get('symbols', {})
        self.edges = model.get('edges', {})
        self.evidence = model.get('evidence', {})
        self.resources = model.get('resources', {})
        self.anchors = model.get('anchors', {})
        self.traces = model.get('traces', {})
        self.claims = model.get('claims', {})
        self.concepts = model.get('concepts', {})
        self.rules = model.get('rules', {})
        self.activities = model.get('activities', {})
        self.ownerships = model.get('ownerships', {})
        self.relationships = model.get('relationships', {})
        self.uses = model.get('information_uses', {})
        self._paths = {(item.get('locator') or {}).get('path') for item in self.evidence.values()} - {None, ''}
        self._short_paths = {}
        self.domains = {domain_id: domain for domain_id, domain in model.get('domains', {}).items()
                        if domain.get('review_state') != 'rejected'
                        and domain.get('support') != 'insufficient'}
        self.domain_order = sorted(self.domains, key=lambda key: (self.domains[key]['name'], key))
        self.domain_pages = self._page_names()
        self.activity_domains = defaultdict(list)
        for domain_id in self.domain_order:
            for membership in self.domains[domain_id]['activity_memberships']:
                self.activity_domains[membership['activity_id']].append(domain_id)
        self.rule_domains = defaultdict(list)
        self.concept_domains = defaultdict(list)
        for domain_id in self.domain_order:
            for rule_id in self.domains[domain_id].get('rules', ()):
                self.rule_domains[rule_id].append(domain_id)
            for concept_id in self.domains[domain_id].get('concepts', ()):
                self.concept_domains[concept_id].append(domain_id)
        for rule_id, rule in self.rules.items():
            if not self.rule_domains[rule_id]:
                self.rule_domains[rule_id] = sorted(
                    {domain_id for activity_id in rule.get('activity_ids', ())
                     for domain_id in self.activity_domains.get(activity_id, ())},
                    key=self.domain_order.index)
        self.claims_about = defaultdict(list)
        for claim_id in sorted(self.claims):
            self.claims_about[self.claims[claim_id]['subject_id']].append(self.claims[claim_id])

    def _page_names(self) -> dict:
        pages, used = {}, Counter()
        for domain_id in self.domain_order:
            name = slug(self.domains[domain_id]['name'])
            used[name] += 1
            pages[domain_id] = name if used[name] == 1 else f'{name}-{short(domain_id)}'
        return pages

    def sorted_records(self, records: dict, ids) -> list:
        present = [records[identifier] for identifier in set(ids) if identifier in records]
        return sorted(present, key=lambda item: (item.get('name', ''), item['id']))

    def name(self, identifier: str) -> str:
        """Return a readable name for any record ID."""
        for records in (self.domains, self.activities, self.concepts, self.rules):
            if identifier in records:
                return records[identifier]['name']
        if identifier in self.anchors:
            return self.entry_point(identifier)
        if identifier in self.symbols:
            return self.symbol_name(identifier)
        if identifier in self.resources:
            return self.resources[identifier].get('name') or identifier
        if identifier in self.ownerships:
            ownership = self.ownerships[identifier]
            return f"{self.name(ownership['concept_id'])} ({ownership['kind']})"
        return f'(missing ref {identifier})' if ':' in identifier else identifier

    def readable(self, text: str) -> str:
        """Replace record IDs the model wrote into prose with names, and its jargon with plain words."""
        for pattern, replacement in PLAIN_WORDS:
            text = pattern.sub(replacement, text)
        def ownership(identifier):
            item = self.ownerships[identifier]
            return (f"{self.name(item.get('domain_id', ''))}'s {item['kind']} claim on "
                    f"{self.name(item['concept_id'])}")

        def trace(identifier):
            return f"the call path from {self.entry_point(self.traces[identifier]['anchor_id'])}"

        def replace(match):
            identifier = match.group('id')
            if identifier in self.ownerships:
                return ownership(identifier)
            if identifier in self.traces:
                return trace(identifier)
            if identifier.startswith('scope:'):
                return 'another part of the model'
            name = self.name(identifier)
            return identifier if name.startswith('(missing ref') else name
        text = re.sub(r'a record of child scope scope:[0-9a-f]+', 'a record from another part of the model', text)
        text = re.sub(r'\btrace (trace:[0-9a-f]+) has no edges',
                      lambda match: (trace(match.group(1)) if match.group(1) in self.traces else 'its call path')
                      + ' has no steps', text)
        # 'ownership ownership:ab12…' names the kind twice; the replacement says it once.
        return re.sub(r'\b(?:(?P<kind>scope|ownership|trace|activity|rule|concept|domain) (?=(?P=kind):))?'
                      r'(?P<id>(?:scope|ownership|trace|activity|rule|concept|domain):[0-9a-f]{12,})\b',
                      replace, text)

    def symbol_name(self, identifier: str) -> str:
        symbol = self.symbols.get(identifier)
        if not symbol:
            return identifier
        name = symbol['qualified_name'].split('::')[-1]
        return re.sub(r':\d+(?=\.|\(|$)', '', name)

    def entry_point(self, anchor_id: str) -> str:
        anchor = self.anchors.get(anchor_id)
        if not anchor:
            return f'(missing ref {anchor_id})'
        operation = anchor.get('operation') or {}
        if anchor.get('kind') == 'http':
            return f"{(operation.get('method') or '').upper()} {operation.get('path') or ''}".strip() \
                or operation.get('name') or anchor_id
        if anchor.get('kind') == 'ui':
            path = operation.get('path') or ''
            name = operation.get('name') or ''
            if operation.get('method') == 'route':
                return f'page {path}'.strip()
            if name == 'unlabeled action':
                name = 'UI action'
            return f'{name} on {path}' if path else name
        return operation.get('name') or anchor_id

    def citations(self, evidence_ids, limit: int = 2, every_kind: bool = False, first_kind=None, avoid=()) -> list:
        """Return up to `limit` distinct `path:lines` citations, source code first.

        With `every_kind`, the first citations cover each kind of evidence (source,
        test, configuration or contract) before any kind repeats.
        """
        found = []
        for evidence_id in evidence_ids or ():
            evidence = self.evidence.get(evidence_id)
            if not evidence:
                continue
            locator = evidence.get('locator') or {}
            path = locator.get('path')
            if not path:
                continue
            start, end = locator.get('start_line'), locator.get('end_line')
            lines = f'{start}' if not end or end == start else f'{start}-{end}'
            rank = SOURCE_PREFERENCE.get(evidence.get('source_kind'), 3)
            if first_kind and evidence.get('source_kind') == first_kind:
                rank = -1
            if avoid and Path(path).stem in avoid:
                rank += 10
            found.append((rank, path, start or 0, lines if start else ''))
        seen, picked, kinds = set(), [], set()
        ordered = sorted(found)
        if every_kind:
            ordered = ([item for item in ordered if item[0] not in kinds and not kinds.add(item[0])]
                       + ordered)
        for _, path, start, lines in ordered:
            if (path, start) not in seen:
                seen.add((path, start))
                picked.append((path, lines))
        # Lines from one file are merged; each file is named by its shortest unique suffix.
        merged = {}
        for path, lines in picked[:limit]:
            merged.setdefault(path, [])
            if lines:
                merged[path].append(lines)
        def spans(lines):
            parsed = sorted((int(a), int(b or a)) for a, _, b in (item.partition('-') for item in lines))
            kept = []
            for start, end in parsed:
                if not any(start >= low and end <= high for low, high in kept):
                    kept.append((start, end))
            return [f'{start}' if start == end else f'{start}-{end}' for start, end in kept]
        return [self.short_path(path) + (':' + ', '.join(spans(lines)) if lines else '') for path, lines in merged.items()]

    def short_path(self, path: str) -> str:
        if path not in self._short_paths:
            parts = path.split('/')
            for size in range(1, len(parts) + 1):
                suffix = '/'.join(parts[-size:])
                if sum(other == suffix or other.endswith('/' + suffix) for other in self._paths) <= 1:
                    break
            self._short_paths[path] = suffix
        return self._short_paths[path]

    def cite(self, evidence_ids, limit: int = 2, every_kind: bool = False, first_kind=None, avoid=()) -> str:
        found = self.citations(evidence_ids, limit, every_kind, first_kind, avoid)
        return ', '.join(code(item) for item in found) if found else '-'

    def access(self, activity: dict):
        """Return (roles, enforced) for a use case.

        Each authorization rule on the use case allows a set of roles; a caller
        needs a role every one of those rules allows. `enforced` is True only when
        some authorization rule is verified on a traced path.
        """
        allowed, enforced = [], False
        for rule_id in sorted(self.rules):
            rule = self.rules[rule_id]
            if activity['id'] not in rule.get('activity_ids', ()):
                continue
            roles = set()
            if rule.get('category') == 'authorization':
                for match in ROLE_PREDICATE.finditer(rule.get('predicate_or_formula') or ''):
                    roles.update(part.strip().split('.')[-1].strip('\'"')
                                 for part in match.group(1).split(',') if part.strip())
                enforced |= rule.get('enforcement_status') == 'verified_on_trace'
            roles.update(ROLE_TOKEN.findall((rule.get('scope') or {}).get('actor') or ''))
            if roles:
                allowed.append(roles)
        if allowed:
            common = set.intersection(*allowed)
            return (sorted(common) if common else [CONFLICTING_ROLES]), enforced
        return sorted(set(ROLE_TOKEN.findall(activity.get('actor') or ''))), False

    def roles(self, activity: dict) -> list:
        return self.access(activity)[0] or [NO_ROLE]

    def role_conditions(self, activity: dict) -> list:
        """Preconditions of the conditional authorization rules on a use case."""
        return sorted({condition for rule in self.rules.values()
                       if activity['id'] in rule.get('activity_ids', ())
                       and rule.get('category') == 'authorization'
                       and rule.get('enforcement_status') == 'conditional'
                       for condition in rule.get('preconditions') or ()})

    def channel(self, activity: dict) -> str:
        kinds = sorted({self.anchors[anchor_id].get('kind') or 'unknown'
                        for anchor_id in activity.get('anchor_ids', ()) if anchor_id in self.anchors})
        return ' and '.join(CHANNELS.get(kind, kind) for kind in kinds) or 'unknown channel'

    def concept_usage(self) -> dict:
        """Map concept id to {domain id: set of access verbs} from the data accesses."""
        usage = defaultdict(lambda: defaultdict(set))
        for use in self.uses.values():
            concept_id = use.get('concept_id')
            for domain_id in self.activity_domains.get(use.get('activity_id'), ()):
                if concept_id:
                    usage[concept_id][domain_id].add(use.get('access') or 'uses')
        return usage

    def unresolved_usage(self) -> set:
        """(concept id, domain id) pairs with a data access that is not fully resolved."""
        return {(use.get('concept_id'), domain_id) for use in self.uses.values()
                if use.get('resolution') != 'resolved'
                for domain_id in self.activity_domains.get(use.get('activity_id'), ())}

    def owners(self, concept_id: str) -> list:
        claims = [ownership for ownership in self.ownerships.values()
                  if ownership['concept_id'] == concept_id and ownership.get('domain_id') in self.domains]
        # A 'shared' claim next to another context's own claim describes a writer, not a co-owner.
        if any(claim.get('kind') != 'shared' for claim in claims):
            claims = [claim for claim in claims if claim.get('kind') != 'shared']
        return sorted({claim['domain_id'] for claim in claims}, key=self.domain_order.index)


# Entities for class diagrams

class Entities:
    """Entity classes behind the concepts, with fields, supertypes and associations."""

    def __init__(self, index: Model):
        self.index = index
        self.by_concept = {}
        self.classes = {}
        has_field, inherits = defaultdict(list), {}
        for edge in index.edges.values():
            if edge.get('resolution') != 'resolved' or not edge.get('to_ref'):
                continue
            source, target = edge['from_ref'].get('id'), edge['to_ref'].get('id')
            if edge['kind'] == 'has_field':
                has_field[source].append(target)
            elif edge['kind'] == 'inherits' and target in index.symbols:
                inherits[source] = target
        self.has_field, self.inherits = has_field, inherits
        for concept_id in sorted(index.concepts):
            symbols = [symbol_id for name in index.concepts[concept_id].get('qualified_type_names', ())
                       if (symbol_id := self._class_symbol(name))]
            self.by_concept[concept_id] = sorted(set(symbols))
            for symbol_id in symbols:
                self._add(symbol_id)

    def _class_symbol(self, qualified_name: str):
        simple = qualified_name.split('.')[-1]
        path = qualified_name.replace('.', '/')
        candidates = []
        for symbol_id, symbol in self.index.symbols.items():
            if symbol.get('kind') not in ('class', 'type'):
                continue
            name = re.sub(r':\d+$', '', symbol['qualified_name'].split('::')[-1])
            if name != simple:
                continue
            exact = re.sub(r'\.\w+$', '', symbol.get('file', '')).endswith(path)
            candidates.append((not exact, symbol.get('file', ''), symbol_id))
        return sorted(candidates)[0][2] if candidates else None

    def _add(self, symbol_id: str):
        if symbol_id in self.classes or symbol_id not in self.index.symbols:
            return
        self.classes[symbol_id] = None
        fields = []
        for field_id in sorted(self.has_field.get(symbol_id, ())):
            field = self.index.symbols.get(field_id)
            if field:
                fields.append(self._field(field))
        self.classes[symbol_id] = {
            'name': self.index.symbol_name(symbol_id).split('.')[-1],
            'fields': sorted(fields, key=lambda item: item['name']),
            'parent': self.inherits.get(symbol_id),
            'table': self._table(symbol_id),
            'unique': self._unique(symbol_id),
        }
        if self.inherits.get(symbol_id):
            self._add(self.inherits[symbol_id])

    def _field(self, field: dict) -> dict:
        excerpt = ' '.join(self.index.evidence[evidence_id].get('excerpt', '')
                           for evidence_id in field.get('evidence_ids', ())
                           if evidence_id in self.index.evidence)
        name = self.index.symbol_name(field['id']).split('.')[-1].split('(')[0]
        declaration = next((match for match in FIELD_DECLARATION.finditer(excerpt)
                            if match.group(2) == name), None)
        annotations = re.findall(r'@(\w+)', excerpt.split(declaration.group(0))[0]
                                 if declaration else excerpt)
        type_name = declaration.group(1) if declaration else None
        association = next((annotation for annotation in annotations
                            if annotation in JPA_ASSOCIATIONS), None)
        target = None
        if type_name:
            generic = re.search(r'<\s*([\w.]+)\s*>', type_name)
            target = (generic.group(1) if generic else type_name).split('.')[-1]
        join_table = re.search(r'@JoinTable\s*\(\s*name\s*=\s*"(\w+)"', excerpt)
        column = re.search(r'@Column\s*\(\s*name\s*=\s*"(\w+)"', excerpt)
        join_column = re.search(r'@JoinColumn\s*\(\s*name\s*=\s*"(\w+)"', excerpt)
        join_columns = re.findall(r'(?:joinColumns|inverseJoinColumns)\s*=\s*@JoinColumn\s*\(\s*name\s*=\s*"(\w+)"',
                                  excerpt)
        return {'name': name, 'type': type_name, 'annotations': annotations,
                'association': association, 'target': target,
                'join_table': join_table.group(1) if join_table else None,
                'join_columns': join_columns,
                'column': column.group(1) if column else None,
                'join_column': join_column.group(1) if join_column else None,
                'cascade_all': re.search(r'cascade\s*=\s*(?:\{\s*)?CascadeType\.ALL', excerpt) is not None,
                'eager': re.search(r'fetch\s*=\s*FetchType\.EAGER', excerpt) is not None
                or (association in ('ManyToOne', 'OneToOne')
                    and re.search(r'fetch\s*=\s*FetchType\.LAZY', excerpt) is None),
                'key': 'Id' in annotations,
                'mapped_by': re.search(r'mappedBy\s*=\s*"(\w+)"', excerpt) is not None}

    def _table(self, symbol_id: str):
        symbol = self.index.symbols[symbol_id]
        excerpt = ' '.join(self.index.evidence[evidence_id].get('excerpt', '')
                           for evidence_id in symbol.get('evidence_ids', ())
                           if evidence_id in self.index.evidence)
        match = re.search(r'@Table\s*\(\s*name\s*=\s*"(\w+)"', excerpt)
        return match.group(1) if match else None

    def _unique(self, symbol_id: str) -> set:
        """Columns named in @Table(uniqueConstraints = ...) on the class."""
        symbol = self.index.symbols[symbol_id]
        excerpt = ' '.join(self.index.evidence[evidence_id].get('excerpt', '')
                           for evidence_id in symbol.get('evidence_ids', ())
                           if evidence_id in self.index.evidence)
        found = set()
        for block in re.findall(r'@UniqueConstraint\s*\(\s*columnNames\s*=\s*\{([^}]*)\}', excerpt):
            found.update(re.findall(r'"(\w+)"', block))
        return found

    def concept_tables(self, concept_id: str) -> list:
        """The tables behind a concept: its class's @Table, else the tables its data accesses name."""
        declared = sorted({self.classes[symbol_id]['table']
                           for symbol_id in self.by_concept.get(concept_id, ())
                           if self.classes.get(symbol_id) and self.classes[symbol_id]['table']})
        if declared:
            return declared
        tables = set()
        for use in self.index.uses.values():
            if use.get('concept_id') == concept_id:
                tables.update(self.index.resources[resource_id]['name']
                              for resource_id in use.get('resource_ids', ())
                              if self.index.resources.get(resource_id, {}).get('kind') == 'table')
        return sorted(tables)

    def diagram(self, concept_ids, flatten_bases: bool = False, external=()) -> str:
        """Return a Mermaid classDiagram for the given concepts, or '' if there is nothing to draw.

        With `flatten_bases`, inherited fields are shown on each entity and the base classes are left out.
        """
        index = self.index
        roots = {symbol_id for concept_id in concept_ids
                 for symbol_id in self.by_concept.get(concept_id, ())}
        # Classes of other contexts drawn as stubs: given ones, and those that point at a class here.
        outside = {symbol_id for concept_id in external for symbol_id in self.by_concept.get(concept_id, ())} - roots
        if flatten_bases:
            names_here = {self.classes[key]['name'] for key in roots if self.classes.get(key)}
            outside |= {key for key, entity in self.classes.items() if entity and entity['table'] and key not in roots
                        and any(field['association'] and field['target'] in names_here for field in entity['fields'])}
        roots_and_outside = roots | outside
        shown, pending = set(), sorted(roots_and_outside)
        while pending:
            symbol_id = pending.pop()
            if symbol_id in shown or not self.classes.get(symbol_id):
                continue
            shown.add(symbol_id)
            if self.classes[symbol_id]['parent'] and not flatten_bases:
                pending.append(self.classes[symbol_id]['parent'])
        # An association target is resolved by simple name only when that name is unique.
        named = defaultdict(list)
        for symbol_id in self.classes:
            if self.classes.get(symbol_id):
                named[self.classes[symbol_id]['name']].append(symbol_id)
        by_name = {name: ids[0] for name, ids in named.items() if len(ids) == 1}
        lines = ['classDiagram', '  direction LR']
        names, used = {}, Counter()
        for symbol_id in sorted(shown, key=lambda key: (self.classes[key]['name'], key)):
            base = re.sub(r'\W', '', self.classes[symbol_id]['name']) or 'Class'
            used[base] += 1
            names[symbol_id] = base if used[base] == 1 else f'{base}_{re.sub(r"[^A-Za-z0-9]", "", short(symbol_id))}'
        # Each class names its own table; a concept's tables describe a class only
        # when it is the concept's sole class.
        table_of = {}
        for concept_id in sorted(concept_ids):
            for symbol_id in self.by_concept.get(concept_id, ()):
                own = self.classes.get(symbol_id, {}) and self.classes[symbol_id]['table']
                if own:
                    table_of[symbol_id] = [own]
                elif len(self.by_concept[concept_id]) == 1:
                    table_of[symbol_id] = self.concept_tables(concept_id)
        for symbol_id in shown:
            if symbol_id not in table_of and self.classes[symbol_id]['table']:
                table_of[symbol_id] = [self.classes[symbol_id]['table']]
        associations, drawn, ends = [], {}, {}
        join_tables = {field['join_table'] for entity in self.classes.values() if entity
                       for field in entity['fields'] if field['join_table']}
        # Both ends of an association become one line; the cascading owner's side
        # wins, so a composition is drawn whichever class sorts first.
        fields_of = (lambda key: self._all_fields(key)) if flatten_bases else (lambda key: self.classes[key]['fields'])
        for symbol_id in sorted(shown, key=lambda key: names[key]):
            for field in fields_of(symbol_id):
                target = by_name.get(field['target'])
                if not (field['association'] and target in shown):
                    continue
                pair = frozenset((symbol_id, target))
                composes = field['cascade_all'] and field['association'] == 'OneToMany'
                ends.setdefault(pair, []).append((symbol_id, field['name']))
                if pair not in drawn or (composes and not drawn[pair][2]):
                    drawn[pair] = (symbol_id, field['name'], composes)
        for symbol_id in sorted(shown, key=lambda key: names[key]):
            entity = self.classes[symbol_id]
            members = []
            for field in fields_of(symbol_id):
                target = by_name.get(field['target'])
                if field['association'] and target:
                    if target in shown and drawn[frozenset((symbol_id, target))][:2] == (symbol_id, field['name']):
                        left, right = JPA_ASSOCIATIONS[field['association']]
                        via = f" via {field['join_table']}" if field['join_table'] else ''
                        # A cascaded one-to-many owns its parts' lifecycle: UML composition.
                        arrow = '*--' if field['cascade_all'] and field['association'] == 'OneToMany' else '-->'
                        back = [name for owner, name in ends.get(frozenset((symbol_id, target)), ()) if owner == target]
                        role = field['name'] + (f" / {back[0]}" if back else '')
                        eager = ' «eager»' if field['eager'] and field['association'] in ('OneToMany', 'ManyToMany') else ''
                        associations.append(f'  {names[symbol_id]} "{left}" {arrow} "{right}" '
                                            f'{names[target]} : {role}{via}{eager}')
                    continue
                type_name = (field['type'] or '').replace('<', '~').replace('>', '~')
                members.append(f'    +{type_name} {field["name"]}'.replace('+ ', '+') + (' «id»' if field['key'] else ''))
            if symbol_id in outside:
                members = []
            role = '<<entity>>' if symbol_id in roots else '<<external>>' if symbol_id in outside else '<<base>>'
            title = entity['name'] + (f" ({', '.join(table_of[symbol_id])})" if table_of.get(symbol_id) else '')
            if len(named.get(entity['name'], ())) > 1:
                title += f" · {self.index.symbols[symbol_id].get('file', '')}"
            lines.append(f'  class {names[symbol_id]}["{label(title)}"] {{')
            lines.append(f'    {role}')
            lines.extend(members)
            lines.append('  }')
        for symbol_id in sorted(shown, key=lambda key: names[key]):
            parent = self.classes[symbol_id]['parent']
            if parent in shown:
                lines.append(f'  {names[parent]} <|-- {names[symbol_id]}')
        lines.extend(sorted(associations))
        for concept_id in sorted(concept_ids):
            concept = index.concepts.get(concept_id)
            if concept and not self.by_concept.get(concept_id):
                identifier = 'C' + re.sub(r'[^A-Za-z0-9]', '', short(concept_id))
                tables = self.concept_tables(concept_id)
                # A join table is already drawn as the association it backs.
                if tables and set(tables) <= join_tables:
                    continue
                title = concept['name'] + (f" ({', '.join(tables)})" if tables else '')
                lines.append(f'  class {identifier}["{label(title)}"] {{')
                lines.append('    <<table>>')
                lines.append('  }')
        return '\n'.join(lines) if len(lines) > 2 else ''

    def _all_fields(self, symbol_id):
        """Fields of a class and its mapped superclasses, nearest first."""
        fields, seen = [], set()
        while symbol_id and symbol_id not in seen and self.classes.get(symbol_id):
            seen.add(symbol_id)
            fields += self.classes[symbol_id]['fields']
            symbol_id = self.classes[symbol_id]['parent']
        return fields

    def entity_classes(self):
        """Classes mapped to a table, by table name."""
        return {entity['table']: symbol_id for symbol_id, entity in sorted(self.classes.items())
                if entity and entity['table']}

    def er_diagram(self) -> str:
        """A Mermaid erDiagram of the tables the entity classes map, or ''."""
        tables = self.entity_classes()
        if not tables:
            return ''
        by_name = {self.classes[symbol_id]['name']: table for table, symbol_id in tables.items()}

        def kind(field):
            return re.sub(r'\W', '', (field['type'] or 'value').split('<')[0]) or 'value'

        keys = {}
        for table, symbol_id in tables.items():
            key = next((field for field in self._all_fields(symbol_id) if field['key']), None)
            if key:
                keys[table] = (kind(key), key['column'] or key['name'])
        lines, relations, join_tables = ['erDiagram'], set(), {}
        for table in sorted(tables):
            primary, attributes, foreign = [], [], []
            for field in self._all_fields(tables[table]):
                target = by_name.get(field['target'])
                if field['association'] == 'ManyToMany' and field['join_table']:
                    if target:
                        join_tables[field['join_table']] = (table, target, field['join_columns'])
                    continue
                if field['association'] in ('ManyToOne', 'OneToOne') and field['join_column']:
                    foreign.append((keys.get(target, ('value',))[0], field['join_column'], 'FK'))
                    if target:
                        relations.add(f'  {target} ||--o{{ {table} : "{field["join_column"]}"')
                    continue
                if field['association']:
                    continue
                column = field['column'] or (field['name'] if field['key'] else None)
                if column:
                    (primary if field['key'] else attributes).append((kind(field), column, 'PK' if field['key'] else ''))
            unique = self.classes[tables[table]].get('unique') or set()
            lines.append(f'  {table} {{')
            for type_name, column, key in primary + attributes + foreign:
                marks = ', '.join(part for part in (key, 'UK' if column in unique and key != 'PK' else '') if part)
                lines.append(f'    {type_name} {column}' + (f' {marks}' if marks else ''))
            lines.append('  }')
        for join_table, (left, right, columns) in sorted(join_tables.items()):
            lines.append(f'  {join_table} {{')
            for column, owner in zip(columns, (left, right)):
                lines.append(f'    {keys.get(owner, ("value",))[0]} {column} FK')
            lines.append('  }')
            relations.add(f'  {left} ||--o{{ {join_table} : "{columns[0] if columns else left}"')
            relations.add(f'  {right} ||--o{{ {join_table} : "{columns[1] if len(columns) > 1 else right}"')
        lines += sorted(relations)
        return '\n'.join(lines)

    def implied(self, table: str, verb: str) -> list:
        """(table, how) pairs JPA also touches when an entity's table is accessed.

        `verb` is read, delete or write. Reads follow eager associations (explicit
        FetchType.EAGER, and to-one associations, which JPA fetches eagerly by
        default). Deletes follow CascadeType.ALL, children first. Any write keeps
        the join table of an owned many-to-many in step.
        """
        tables = self.entity_classes()
        by_name = {self.classes[symbol_id]['name']: name for name, symbol_id in tables.items()}
        result, pending, seen = [], [table], {table}
        while pending:
            symbol_id = tables.get(pending.pop(0))
            for field in self._all_fields(symbol_id) if symbol_id else ():
                target = by_name.get(field['target'])
                if verb == 'read':
                    follow = field['eager'] and field['association']
                    join = follow and field['join_table']
                    how = 'JPA eager fetch'
                else:
                    follow = verb == 'delete' and field['cascade_all'] and field['association'] in ('OneToMany', 'OneToOne')
                    join = field['association'] == 'ManyToMany' and field['join_table']
                    how = 'JPA cascade'
                if join and join not in seen:
                    seen.add(join)
                    result.append((join, how if verb == 'read' else 'JPA join table'))
                if follow and target and target not in seen:
                    seen.add(target)
                    result.append((target, how))
                    pending.append(target)
        # A cascaded delete removes the deepest children first.
        return list(reversed(result)) if verb == 'delete' else result

    def aggregates(self) -> list:
        """Aggregate candidates from cascaded one-to-many associations.

        Returns (root class, member classes, references to other roots) per
        candidate, where a class no cascade owns is a root.
        """
        entities = {symbol_id: entity for symbol_id, entity in self.classes.items()
                    if entity and entity['table']}
        by_name = {entity['name']: symbol_id for symbol_id, entity in entities.items()}
        owns = defaultdict(set)
        refers = defaultdict(set)
        for symbol_id in entities:
            for field in self._all_fields(symbol_id):
                target = by_name.get(field['target'])
                if not target or target == symbol_id:
                    continue
                if field['cascade_all'] and field['association'] == 'OneToMany':
                    owns[symbol_id].add(target)
                elif field['association'] in ('ManyToOne', 'ManyToMany', 'OneToOne'):
                    refers[symbol_id].add(target)
        owned = {target for targets in owns.values() for target in targets}
        result = []
        for root in sorted((symbol_id for symbol_id in entities if symbol_id not in owned),
                           key=lambda key: entities[key]['name']):
            members, pending = [], sorted(owns[root])
            while pending:
                member = pending.pop(0)
                if member not in members:
                    members.append(member)
                    pending += sorted(owns[member])
            inside = {root, *members}
            outside = sorted({target for symbol_id in inside for target in refers[symbol_id]
                              if target not in inside and target not in owned},
                             key=lambda key: entities[key]['name'])
            result.append((entities[root]['name'], [entities[member]['name'] for member in members],
                           [entities[target]['name'] for target in outside],
                           [entities[member]['name'] for member in members if self.has_repository(entities[member]['name'])]))
        return result

    def has_repository(self, name: str) -> bool:
        """True when a repository interface for the entity exists, so it can be written without its root."""
        return any(symbol['qualified_name'].split('::')[-1] == f'{name}Repository'
                   for symbol in self.index.symbols.values() if symbol.get('kind') in ('class', 'type', 'interface'))

    def constraints(self, concept_ids) -> list:
        """Rows of (class, field, annotations) for validation annotations on fields."""
        rows = []
        for concept_id in sorted(concept_ids):
            for symbol_id in self.by_concept.get(concept_id, ()):
                entity = self.classes.get(symbol_id)
                if not entity:
                    continue
                declared, current, seen = [], symbol_id, set()
                while current and current not in seen and self.classes.get(current):
                    seen.add(current)
                    suffix = '' if current == symbol_id else f" (from {self.classes[current]['name']})"
                    declared += [(field, suffix) for field in self.classes[current]['fields']]
                    current = self.classes[current]['parent']
                for field, suffix in declared:
                    checks = [annotation for annotation in field['annotations']
                              if annotation not in JPA_ASSOCIATIONS
                              and annotation not in ('Column', 'JoinColumn', 'JoinTable', 'Id',
                                                     'GeneratedValue', 'Temporal', 'Transient',
                                                     'JsonIgnore', 'Override')]
                    if checks:
                        rows.append((entity['name'], field['name'] + suffix, checks))
        return sorted(set((name, field, tuple(checks)) for name, field, checks in rows))


# Sequence diagrams

class Sequences:
    """Static call paths per entry point, rebuilt in source order."""

    def __init__(self, index: Model, entities: 'Entities' = None):
        self.index = index
        self.entities = entities or Entities(index)
        # Class-level calls each drawn trace makes, for the component diagrams.
        self.links = defaultdict(set)
        # Per interface lifeline: implementations that run on the declared profile, and the others.
        self.choices = defaultdict(lambda: {'runs': set(), 'inactive': set()})
        self.files = {}
        # Each call edge cites only its own expression; the longest one-line excerpt
        # on a line holds the whole statement, which shows how calls nest.
        self.statements = {}
        for item in index.evidence.values():
            locator = item.get('locator') or {}
            line = locator.get('start_line')
            if line and locator.get('end_line') == line:
                key = (locator.get('path'), line)
                if len(item.get('excerpt') or '') > len(self.statements.get(key, '')):
                    self.statements[key] = item['excerpt']
        # The extractor marks every profile-bound implementation as matching, so
        # the declared profiles come from spring.profiles.active.
        profiles = set()
        for edge in index.edges.values():
            for match in ACTIVE_PROFILES.finditer(edge.get('condition') or ''):
                profiles.update(part.strip() for part in match.group(1).split(','))
        self.active_profiles = profiles
        # The statement behind each data write, to tell inserts, updates and deletes apart.
        self.effects = {effect['edge_id']: effect for effect in index.raw.get('effects', {}).values()
                        if effect.get('edge_id')}
        # The HTTP operation each controller method implements.
        self.http_of = {}
        for anchor_id, anchor in index.anchors.items():
            if anchor.get('kind') == 'http':
                for representation in anchor.get('representations') or ():
                    if representation.get('role') == 'implementation' and representation.get('symbol_id'):
                        self.http_of.setdefault(representation['symbol_id'], index.entry_point(anchor_id))
        # Early returns the rules record: (line, condition, status) per method.
        self.guards = defaultdict(list)
        implementation = {anchor_id: representation['symbol_id'] for anchor_id, anchor in index.anchors.items()
                          for representation in anchor.get('representations') or ()
                          if representation.get('role') == 'implementation' and representation.get('symbol_id')}
        for rule in index.rules.values():
            outcome = rule.get('outcome') or ''
            status = http_status(outcome)
            # An outcome naming two statuses cannot say which one a condition returns.
            if not status or len(set(re.findall(r'\b[45]\d\d\b', outcome))) > 1:
                continue
            for site in rule.get('enforcement_sites') or ():
                condition = unwrap((site.get('condition') or '').strip())
                source = implementation.get(site.get('source_id'), site.get('source_id'))
                home = (index.symbols.get(source) or {}).get('file')
                # Only a line in the method's own file can be placed among its calls.
                lines = [index.evidence[item]['locator'].get('start_line') for item in site.get('evidence_ids') or ()
                         if item in index.evidence and index.evidence[item]['locator'].get('start_line')
                         and index.evidence[item]['locator'].get('path') == home]
                if condition and lines and source and not condition.startswith('@'):
                    entry = (min(lines), condition, status)
                    if entry not in self.guards[source]:
                        self.guards[source].append(entry)
        for entries in self.guards.values():
            entries.sort()
        self._tx = {}
        # Cascades and eager fetches are JPA behaviour; a declared non-JPA profile turns them off.
        self.jpa = not profiles or any('jpa' in profile.lower() for profile in profiles)

    def transaction(self, symbol_id: str) -> str:
        """'tx' or 'tx readOnly' when the method is declared @Transactional, else ''."""
        if symbol_id not in self._tx:
            symbol = self.index.symbols.get(symbol_id) or {}
            found = ''
            for evidence_id in symbol.get('evidence_ids') or ():
                excerpt = (self.index.evidence.get(evidence_id) or {}).get('excerpt') or ''
                head = re.split(r'\b(?:public|protected|private)\b|\{', excerpt, maxsplit=1)[0]
                match = re.search(r'@(?:\w+\.)*Transactional\b(\([^)]*readOnly\s*=\s*true[^)]*\))?', head)
                if match:
                    found = 'tx readOnly' if match.group(1) else 'tx'
                    break
            self._tx[symbol_id] = found
        return self._tx[symbol_id]

    def write_kind(self, edge: dict, symbol_id: str) -> str:
        """insert, update or delete from the recorded statement, else from the method name."""
        outcome = (self.effects.get(edge['id']) or {}).get('outcome') or ''
        if re.search(r'\bDELETE\b|\.remove\(|\.delete\(', outcome, re.I):
            return 'delete'
        if re.search(r'\bINSERT\b|\.persist\(|executeAndReturnKey|\binsert\w*\.execute', outcome, re.I):
            return 'insert'
        if re.search(r'\bUPDATE\b|\.merge\(', outcome, re.I):
            return 'update'
        method = self.index.symbol_name(symbol_id).split('(')[0].rsplit('.', 1)[-1].lower()
        return 'delete' if method.startswith(('delete', 'remove')) else 'write'

    @staticmethod
    def _binding(edge):
        """Return (profile, class name, declared active) for an implementation edge."""
        condition = edge.get('condition') or ''
        match = ACTIVATES.search(condition)
        if match:
            return match.group(2), match.group(1), True
        match = PROFILE.search(condition)
        if match:
            return match.group(1), match.group(2), False
        return None, None, False

    def _choose(self, choices):
        """Return the implementation that runs, or None when the model can't tell."""
        declared = [edge for edge in choices if self._binding(edge)[2]]
        if len(declared) == 1:
            return declared[0]
        bound = [edge for edge in choices if self._binding(edge)[0]]
        if bound and self.active_profiles:
            active = [edge for edge in bound if self._binding(edge)[0] in self.active_profiles]
            # A class and its generated proxy can arrive as two targets with one name.
            names = {self._binding(edge)[1] for edge in active}
            if len(names) == 1 and None not in names:
                active = sorted(active, key=lambda edge: edge['to_ref'].get('id') not in self.index.symbols)[:1]
            return active[0] if len(active) == 1 else None
        return choices[0] if len(choices) == 1 else None

    def diagrams(self, activity: dict):
        """Return (drawn, skipped): drawn is (title, caption, mermaid); skipped is (entry, reason)."""
        index = self.index
        traces = [index.traces[trace_id] for trace_id in activity.get('trace_ids', ())
                  if trace_id in index.traces]
        drawn, skipped = [], []
        for trace in sorted(traces, key=lambda item: (
                index.anchors.get(item['anchor_id'], {}).get('kind') != 'http', item['id'])):
            entry = index.entry_point(trace['anchor_id'])
            if len(drawn) == 3:
                skipped.append((entry, 'only the first three call paths of a use case are drawn'))
                continue
            result = self.diagram(trace, activity)
            if isinstance(result, str):
                skipped.append((entry, result))
            else:
                drawn.append(result)
        return drawn, skipped

    def _participant(self, ref):
        if not ref:
            return None
        if ref.get('kind') == 'resource':
            resource = self.index.resources.get(ref['id'], {})
            if resource.get('kind') == 'table':
                return ('table', resource.get('name') or ref['id'])
            return None
        symbol = self.index.symbols.get(ref.get('id'))
        if not symbol:
            return None
        if symbol.get('kind') == 'declarative_operation' and 'registration' not in symbol['qualified_name']:
            return ('contract', 'API contract (no implementation)')
        name = self.index.symbol_name(symbol['id'])
        participant = self._symbol_participant(symbol, name)
        self.files.setdefault(participant[1], symbol.get('file', ''))
        return participant

    @staticmethod
    def _symbol_participant(symbol, name):
        if symbol.get('kind') in ('function', 'declarative_operation') or '.' not in name.split('(')[0]:
            path = Path(symbol.get('file', ''))
            stem = path.stem or name
            if stem.lower() in ('index', 'main', 'util', 'utils', 'helpers') and path.parent.name:
                stem = f'{path.parent.name}/{stem}'
            return ('participant', stem)
        return ('participant', name.split('(')[0].rsplit('.', 1)[0])

    def _method(self, ref) -> str:
        symbol = self.index.symbols.get((ref or {}).get('id'))
        if not symbol:
            return ''
        name = self.index.symbol_name(symbol['id']).split('(')[0]
        return name.rsplit('.', 1)[-1] + '()'

    def _call_order(self, edge) -> tuple:
        """Order calls by call-site line; on one line, the inner (rightmost) call runs first."""
        index = self.index
        caller = index.symbols.get(edge['from_ref'].get('id'), {})
        spans = [index.evidence[evidence_id] for evidence_id in edge.get('evidence_ids', ())
                 if evidence_id in index.evidence
                 and index.evidence[evidence_id].get('locator', {}).get('path') == caller.get('file')]
        if not spans:
            return (edge['kind'] == 'routes_to', 10 ** 9, 0, edge['id'])
        span = min(spans, key=lambda item: item['locator'].get('start_line') or 0)
        excerpt = span.get('excerpt') or ''
        statement = self.statements.get((span['locator'].get('path'), span['locator'].get('start_line')), '')
        if excerpt in statement:
            excerpt = statement
        method = self._method(edge.get('to_ref')).rstrip('()')
        position = excerpt.find(method + '(') if method else -1
        # An argument call runs before the call it is passed to; a chain runs left to right.
        depth = (excerpt[:position].count('(') - excerpt[:position].count(')')) if position >= 0 else 0
        return (edge['kind'] == 'routes_to', span['locator'].get('start_line') or 0, -depth,
                position if position >= 0 else 10 ** 6, edge['id'])

    @staticmethod
    def _guard(condition) -> str:
        """Keep the business part of a condition, cut on a word boundary."""
        parts, operators, depth, start, text = [], [], 0, 0, condition or ''
        position = 0
        while position < len(text):
            char = text[position]
            depth += char == '('
            depth -= char == ')'
            operator = text[position:position + 2]
            if depth == 0 and operator in ('&&', '||'):
                parts.append(text[start:position].strip())
                operators.append('and' if operator == '&&' else 'or')
                start = position = position + 2
                continue
            position += 1
        parts.append(text[start:].strip())
        guard = ''
        for index, part in enumerate(parts):
            if not part or BUILD_CONFIG.search(part):
                continue
            guard += (f' {operators[index - 1]} ' if guard else '') + part
        if len(guard) > 60:
            guard = guard[:60].rsplit(' ', 1)[0].rstrip(' ,(') + '…'
        return guard

    @staticmethod
    def _complement(first: str, second: str) -> bool:
        def bare(text):
            text = text.strip()
            return text[2:-1].strip() if text.startswith('!(') and text.endswith(')') else None
        return bare(second) == first.strip() or bare(first) == second.strip() \
            or second.strip() == '!' + first.strip() or first.strip() == '!' + second.strip()

    def _alternatives(self, steps):
        """Merge an opt block followed by its negation into one alt/else block."""
        def block_end(start):
            depth = 0
            for position in range(start, len(steps)):
                if steps[position][0] in ('opt', 'alt'):
                    depth += 1
                elif steps[position][0] == 'end':
                    depth -= 1
                    if depth == 0:
                        return position
            return None
        result, position = [], 0
        while position < len(steps):
            step = steps[position]
            end = block_end(position) if step[0] == 'opt' else None
            if end is not None and end + 1 < len(steps) and steps[end + 1][0] == 'opt' \
                    and self._complement(step[1], steps[end + 1][1]):
                other_end = block_end(end + 1)
                if other_end is not None:
                    result += [('alt', step[1]), *steps[position + 1:end], ('else', steps[end + 1][1]),
                               *steps[end + 2:other_end], ('end',)]
                    position = other_end + 1
                    continue
            result.append(step)
            position += 1
        return result

    def layer(self, kind: str, name: str) -> str:
        """The architectural layer of a participant, by its kind or class naming convention."""
        if kind == 'table':
            return 'Tables'
        if kind == 'contract':
            return 'API contract'
        if kind == 'endpoint':
            return 'Unmatched client calls'
        if Path(self.files.get(name, '')).suffix in ('.tsx', '.jsx', '.ts', '.js', '.vue', '.html'):
            return 'User interface'
        for suffixes, layer in ((('Controller', 'Resource', 'Endpoint'), 'Controllers'),
                                (('Service', 'ServiceImpl', 'Facade', 'UseCase'), 'Application services'),
                                (('Repository', 'RepositoryImpl', 'Dao', 'DaoImpl'), 'Repositories'),
                                (('Mapper', 'Converter', 'Assembler'), 'Mappers')):
            if name.endswith(suffixes):
                return layer
        if any(entity and entity['table'] and entity['name'] == name for entity in self.entities.classes.values()):
            return 'Entities'
        return 'Other classes'

    def _root(self, anchor: dict):
        for representation in anchor.get('representations') or ():
            if isinstance(representation, dict) and representation.get('role') == 'implementation':
                return representation.get('symbol_id')
        return anchor.get('symbol_id')

    def diagram(self, trace: dict, activity: dict = None):
        """Return (title, caption, mermaid), or the reason the trace is not drawn."""
        index = self.index
        anchor = index.anchors.get(trace['anchor_id'])
        if not anchor:
            return 'its entry point is missing from the model'
        outgoing = defaultdict(list)
        for edge_id in trace.get('edge_ids', ()):
            edge = index.edges.get(edge_id)
            if edge and edge['kind'] in SEQUENCE_KINDS:
                outgoing[edge['from_ref'].get('id')].append(edge)
        for edges in outgoing.values():
            edges.sort(key=self._call_order)
        root = self._root(anchor)
        if root not in outgoing:
            return 'no call path starts at its entry point'
        first = self._participant({'kind': 'symbol', 'id': root})
        if not first:
            return 'its entry point has no code symbol'
        # A page that calls a known endpoint does not also need the helper's unmatched request.
        resolved_http = any(edge['kind'] in ('invokes_endpoint', 'routes_to') and edge.get('resolution') == 'resolved'
                            and (edge.get('to_ref') or {}).get('kind') == 'symbol'
                            for edges in outgoing.values() for edge in edges)
        guards = list(self.guards.get(root, ()))
        participants, steps = [first], []
        facts = defaultdict(lambda: {'runs': set(), 'inactive': set(), 'unbound': set(), 'ambiguous': set(),
                                     'by_profile': set()})
        expanded = set()
        budget = {'messages': 0, 'omitted': 0}

        def join(target):
            if target not in participants:
                participants.append(target)
            return target[1]

        def message(source, target, arrow, text):
            if budget['messages'] >= MAX_MESSAGES:
                budget['omitted'] += 1
                return False
            budget['messages'] += 1
            steps.append(('message', source, target, arrow, text))
            return True

        WRITES_ = ('write', 'insert', 'update', 'delete')
        opened = {'count': 0}

        def drawn(lifeline, table, verb):
            kinds = ('read',) if verb == 'read' else WRITES_
            return any(step[0] == 'message' and step[1] == lifeline and step[4].split(' (')[0].split(' ', 1)[-1] == table
                       and step[4].split(' ', 1)[0] in kinds for step in steps)

        def upgrade(lifeline, table, arrow):
            """An explicit read of a table already drawn as an eager fetch replaces it."""
            for position in range(len(steps) - 1, -1, -1):
                step = steps[position]
                if step[0] == 'message' and step[1] == lifeline and step[4] == f'read {table} (JPA eager fetch)':
                    steps[position] = ('message', lifeline, step[2], arrow, f'read {table}')
                    return True
            return False

        def open_guards(line, last=False):
            """Early returns recorded before this call site become alt blocks.

            A guard after the last call has nothing in its else branch unless the
            success status is known, so it is drawn as opt.
            """
            while guards and guards[0][0] < line:
                _, condition, code = guards.pop(0)
                if last and not (guards or success_status()):
                    steps.extend([('opt', condition), ('message', first[1], CLIENT, '-->>', code), ('end',)])
                    continue
                steps.append(('alt', condition))
                message(first[1], CLIENT, '-->>', code)
                steps.append(('else', 'otherwise'))
                opened['count'] += 1

        def success_status():
            if anchor.get('kind') != 'http' or not activity:
                return ''
            operation = anchor.get('operation') or {}
            entry = index.entry_point(anchor['id'])
            for claim in index.claims_about.get(activity['id'], ()):
                found = RETURNED_STATUS.search(claim.get('text') or '')
                text = claim.get('text') or ''
                if (claim.get('kind') in ('conflict', 'contradiction') and found and found.group(1).startswith('2')
                        and (entry in text or (operation.get('name') and operation['name'] in text))):
                    return f'{found.group(1)} (the contract does not declare it)'
            return ''

        def walk(symbol_id, lifeline, depth, branch=()):
            if depth > MAX_DEPTH or (symbol_id, lifeline, branch) in expanded or budget['omitted']:
                return
            expanded.add((symbol_id, lifeline, branch))
            implementations = {}
            for edge in outgoing.get(symbol_id, ()):
                if edge['kind'] == 'selects_implementation' and edge.get('to_ref'):
                    implementations.setdefault(edge['to_ref'].get('id'), edge)
            chosen = self._choose(list(implementations.values())) if implementations else None
            for target_id, edge in implementations.items():
                profile, name, _ = self._binding(edge)
                label_name = name or (self._participant(edge.get('to_ref')) or (None, ''))[1]
                if edge is chosen:
                    if len(implementations) > 1 and label_name:
                        # Spring Data's proxy shows up as a target with no source symbol.
                        generated = any(other not in index.symbols and (
                            self._binding(implementations[other])[1] or '') == (name or '')
                            for other in implementations) if name else target_id not in index.symbols
                        facts[lifeline]['runs'].add(label_name + (', generated at runtime' if generated else ''))
                    if target_id in index.symbols:
                        walk(target_id, lifeline, depth + 1, branch)
                    continue
                if profile and self.active_profiles and profile not in self.active_profiles:
                    facts[lifeline]['inactive'].add(label_name)
                elif profile and self.active_profiles and chosen is None:
                    facts[lifeline]['ambiguous'].add(label_name)
                elif profile:
                    facts[lifeline]['by_profile'].add(label_name)
                elif len(implementations) > 1:
                    facts[lifeline]['unbound'].add(label_name)
            for edge in outgoing.get(symbol_id, ()):
                if edge['kind'] == 'selects_implementation':
                    continue
                target_ref = edge.get('to_ref')
                target_id = (target_ref or {}).get('id')
                target = self._participant(target_ref)
                if depth == 0:
                    open_guards(self._call_order(edge)[1])
                if not target and edge['kind'] == 'invokes_endpoint':
                    if resolved_http:
                        continue
                    target = ('endpoint', 'no matching server endpoint')
                    message(lifeline, join(target), '-->>', 'request (target not resolved)')
                    continue
                if not target:
                    continue
                arrow = '->>' if edge.get('resolution') == 'resolved' else '-->>'
                guard = self._guard(edge.get('condition'))
                if edge['kind'] in ('reads_data', 'writes_data'):
                    verb = 'read' if edge['kind'] == 'reads_data' else self.write_kind(edge, symbol_id)
                    table = target[1]
                    implied = self.entities.implied(table, 'read' if verb == 'read' else 'delete' if verb == 'delete'
                                                    else 'write') if target[0] == 'table' and self.jpa else []
                    if verb == 'read' and upgrade(lifeline, table, arrow):
                        continue
                    # A cascaded delete removes the children before the row that owns them.
                    if verb == 'delete':
                        for other, how in implied:
                            if not drawn(lifeline, other, verb):
                                message(lifeline, join(('table', other)), '-->>', f'{verb} {other} ({how})')
                    message(lifeline, join(target), arrow, f'{verb} {table}')
                    if verb != 'delete':
                        for other, how in implied:
                            if not drawn(lifeline, other, 'read' if verb == 'read' else 'write'):
                                message(lifeline, join(('table', other)), '-->>', f"{'read' if verb == 'read' else 'write'} {other} ({how})")
                    continue
                if ACCESSOR.search(index.symbol_name(target_id or '') + '('):
                    continue
                if target[1] == lifeline and target[0] != 'contract':
                    walk(target_id, lifeline, depth + 1, branch)
                    continue
                if guard:
                    steps.append(('opt', guard))
                if target[0] == 'contract':
                    message(lifeline, join(target), '-->>', index.symbol_name(target_id).split('::')[-1][:50])
                elif message(lifeline, join(target), arrow,
                             self.http_of[target_id] if edge['kind'] in ('invokes_endpoint', 'routes_to')
                             and target_id in self.http_of
                             else self._method(target_ref)
                             + (f' «{self.transaction(target_id)}»' if self.transaction(target_id) else '')):
                    walk(target_id, target[1], depth + 1, branch + ((guard,) if guard else ()))
                if guard:
                    steps.append(('end',))

        walk(root, first[1], 0)
        open_guards(10 ** 9, last=True)
        status = success_status()
        if status:
            message(first[1], CLIENT, '-->>', status)
        steps.extend([('end',)] * opened['count'])
        # The interface and its implementation often record the same data access.
        tidy = []
        for step in steps:
            if (step[0] == 'message' and tidy and tidy[-1][0] == 'message'
                    and tidy[-1][1:3] == step[1:3] and tidy[-1][4] == step[4]):
                if step[3] == '->>':
                    tidy[-1] = step
                continue
            # The interface records a write; its implementation names the statement.
            previous = tidy[-1] if tidy else None
            if (step[0] == 'message' and previous and previous[0] == 'message' and previous[1:3] == step[1:3]
                    and '(' not in step[4] and '(' not in previous[4]):
                before, after = previous[4].split(' ', 1), step[4].split(' ', 1)
                if (len(before) == len(after) == 2 and before[1] == after[1]
                        and before[0] in WRITES_ and after[0] in WRITES_):
                    verbs = [verb for verb in (before[0], after[0]) if verb != 'write']
                    verb = ' or '.join(dict.fromkeys(verbs)) or 'write'
                    arrow = '->>' if '->>' in (previous[3], step[3]) else '-->>'
                    tidy[-1] = ('message', step[1], step[2], arrow, f'{verb} {after[1]}')
                    continue
            if step[0] == 'end' and tidy and tidy[-1][0] == 'opt':
                tidy.pop()
                continue
            tidy.append(step)
        tidy = self._alternatives(tidy)
        messages = [step for step in tidy if step[0] == 'message']
        if not messages:
            return 'its call path has no step outside the entry point'
        kinds = dict((name, kind) for kind, name in participants)
        for _, source, target, _, _ in messages:
            if CLIENT not in (source, target):
                self.links[trace['id']].add(((kinds.get(source), source), (kinds.get(target), target)))
        actor = ACTORS.get(anchor.get('kind'), 'Caller')
        drawn_names = {name for _, name in participants}
        notes, shown_as = {}, {}
        for lifeline in [name for _, name in participants if name in facts]:
            fact = facts[lifeline]
            # The source class and its generated proxy can arrive as two targets with one name.
            running = {name.split(', generated at runtime')[0] for name in fact['runs']}
            runs = sorted(name + (', generated at runtime' if name + ', generated at runtime' in fact['runs'] else '')
                          for name in running)
            inactive = fact['inactive'] - running
            ambiguous = fact['ambiguous'] - running
            by_profile = fact['by_profile'] - running
            unbound = fact['unbound'] - drawn_names - running
            if runs or inactive:
                self.choices[lifeline]['runs'].update(runs)
                self.choices[lifeline]['inactive'].update(inactive)
            parts = []
            if runs and len(runs) <= 2 and not (ambiguous or by_profile or unbound):
                # The implementations that run are named on the lifeline; the others are listed once per page.
                shown_as[lifeline] = f"{lifeline} → " + ' + '.join(
                    item.replace(', generated at runtime', ' (generated)') for item in runs)
            elif runs:
                parts.append('Runs ' + ' + '.join(item.replace(', generated at runtime', ' (generated)') for item in runs))
            if ambiguous:
                parts.append('several match the configured Spring profile, not drawn: ' + ', '.join(sorted(ambiguous)))
            if by_profile:
                parts.append('picked at startup by the Spring profile, not drawn: ' + ', '.join(sorted(by_profile)))
            if unbound:
                parts.append('other implementations, not drawn: ' + ', '.join(sorted(unbound)))
            if parts and lifeline not in shown_as and inactive:
                parts.append('not used with the configured Spring profile: ' + ', '.join(sorted(inactive)))
            if parts:
                notes[lifeline] = '. '.join(part[:1].upper() + part[1:] for part in parts) + '.'
        lines = ['sequenceDiagram', '  autonumber', f'  actor Client as {label(actor)}']
        ids = {}
        for position, (kind, name) in enumerate(participants[:MAX_PARTICIPANTS], 1):
            ids[name] = f'P{position}'
            shown = f'{name} table' if kind == 'table' else shown_as.get(name, name)
            lines.append(f'  participant P{position} as {label(shown)}')
        ids[CLIENT] = 'Client'
        lines.append(f'  Client->>{ids[first[1]]}: {label(index.entry_point(anchor["id"]))}')
        if self.transaction(root):
            lines.append(f'  Note over {ids[first[1]]}: '
                         + label(f"{self._method({'kind': 'symbol', 'id': root})} is @Transactional"
                                 + (' (readOnly)' if self.transaction(root) == 'tx readOnly' else '')))
        # branch: None outside an alt; else (steps in the branch, steps drawn)
        depth, branch = 0, None
        for step in tidy:
            if step[0] in ('else', 'end') and branch and not branch[1]:
                text = 'steps on this branch not drawn' if branch[0] else 'no calls found on this branch'
                lines.append('  ' * (depth + 1) + f'Note over {ids[first[1]]}: {text}')
            if step[0] in ('alt', 'else'):
                branch = [0, 0]
            elif step[0] == 'end':
                branch = None
            elif step[0] == 'message' and branch:
                branch[0] += 1
                branch[1] += step[1] in ids and step[2] in ids
            if step[0] in ('opt', 'alt'):
                lines.append('  ' * (depth + 1) + f'{step[0]} {label(step[1])}')
                depth += 1
            elif step[0] == 'else':
                lines.append('  ' * depth + f'else {label(step[1])}')
            elif step[0] == 'end':
                depth = max(0, depth - 1)
                lines.append('  ' * (depth + 1) + 'end')
            else:
                _, source, target, arrow, text = step
                if source not in ids or target not in ids:
                    budget['omitted'] += 1
                    continue
                lines.append('  ' * (depth + 1) + f'{ids[source]}{arrow}{ids[target]}: {label(text)}')
        while depth:
            depth -= 1
            lines.append('  ' * (depth + 1) + 'end')
        for lifeline, text in notes.items():
            if lifeline in ids:
                lines.append(f'  Note over {ids[lifeline]}: {label(text)}')
        contract = 'API contract (no implementation)'
        if contract in ids:
            lines.append(f'  Note over {ids[contract]}: '
                         + label('Only in the API contract: no server code found for it'))
        if budget['omitted']:
            lines.append(f"  Note over {ids[first[1]]}: "
                         + label(f"at least {plural(budget['omitted'], 'more step')} not drawn (trace {short(trace['id'])})"))
        state = ' · '.join(TRACE_WORDS.get(part, part) for part in (trace.get('completion'), trace.get('resolution')) if part)
        caption = f'Call path: {state}.' if state else ''
        return (index.entry_point(anchor['id']), caption, '\n'.join(lines))


# Pages

def badge(value: str, names: dict) -> str:
    return names.get(value, value or '-')


def rule_status(rule: dict, brief: bool = False) -> str:
    """Enforcement in words, saying where a declared rule is declared."""
    names = ENFORCEMENT_SHORT if brief else ENFORCEMENT
    status = rule.get('enforcement_status')
    if status != 'declared_only':
        return badge(status, names)
    basis = set(rule.get('basis') or ())
    if 'source_observed' in basis:
        return names['declared_only']
    if 'contract_declared' in basis and 'test_expected' in basis:
        return 'in contract + tests' if brief else 'written in the API contract and expected by tests'
    if 'contract_declared' in basis:
        return 'in contract only' if brief else 'written in the API contract only'
    if 'test_expected' in basis:
        return 'in tests only' if brief else 'expected by tests only'
    if 'documented' in basis:
        return 'in docs only' if brief else 'described in docs only'
    return names['declared_only']


def table(header, rows) -> list:
    """A Markdown table whose delimiter row always matches its header."""
    lines = ['| ' + ' | '.join(name for name, _ in header) + ' |',
             '|' + '|'.join('---:' if right else '---' for _, right in header) + '|']
    lines += ['| ' + ' | '.join(str(value) for value in row) + ' |' for row in rows]
    return lines


def model_banner(index: Model, link_gaps: bool = True, compact: bool = False) -> list:
    model = index.raw
    coverage = model.get('coverage') or {}
    traces = list(index.traces.values())
    uses = list(index.uses.values())
    open_traces = sum(trace.get('resolution') != 'resolved' for trace in traces)
    open_uses = sum(use.get('resolution') != 'resolved' for use in uses)
    pending = [item for item in model.get('unassigned', ()) if item.get('status') == 'pending']
    hidden = len(model.get('domains', {})) - len(index.domains)
    lines = [
        f"> **Model status: {model.get('status', 'unknown')}.** Generated from build "
        f"`{model.get('build_id', '-')}` on {str(model.get('generated_at', '-'))[:19].replace('T', ' ')} UTC.",
        f"> Entry points: {coverage.get('anchors_processed', '-')} of {coverage.get('anchors_total', '-')} modelled "
        f"({coverage.get('anchors_excluded', 0)} excluded, {coverage.get('anchors_pending', 0)} pending). "
        f"Call paths fully confirmed: {len(traces) - open_traces} of {len(traces)}. "
        f"Database reads and writes fully confirmed: {len(uses) - open_uses} of {len(uses)}."
        + (f" {plural(hidden, 'context')} not shown (not enough evidence, or rejected by a reviewer)."
           if hidden else ''),
    ]
    if compact:
        when = str(model.get('generated_at', '-'))[:16].replace('T', ' ')
        return [f"> **Model status: {model.get('status', 'unknown')}** · build `{str(model.get('build_id', '-'))[:8]}` · {when} UTC",
                '>',
                f"> Entry points: {coverage.get('anchors_processed', '-')} of {coverage.get('anchors_total', '-')} modelled "
                f"({coverage.get('anchors_excluded', 0)} excluded, {coverage.get('anchors_pending', 0)} pending) · "
                f"call paths fully confirmed: {len(traces) - open_traces} of {len(traces)} · "
                f"database reads and writes fully confirmed: {len(uses) - open_uses} of {len(uses)} · [Gaps](gaps.md)"
                + (f" · {plural(hidden, 'context')} not shown (not enough evidence, or rejected by a reviewer)"
                   if hidden else '')]
    if model.get('status') != 'complete':
        reasons = []
        if pending:
            reasons.append(plural(len(pending), 'entry point') + ' not modelled')
        if open_traces:
            reasons.append('some call paths stop at framework or generated code')
        if any(item.get('support') != 'supported' for item in index.activities.values()):
            reasons.append('some use cases only partly backed by the code we followed')
        if reasons:
            lines.append('> Partial means: ' + '; '.join(reasons) + '.'
                         + (' See [Gaps](gaps.md).' if link_gaps else ''))
    # A bare '>' keeps each line its own paragraph inside the quote.
    return [part for line in lines for part in (line, '>')][:-1]


def summary(index: Model) -> list:
    """The findings a reader should know before the diagrams."""
    findings = []
    order = index.domain_order.index
    for (source, target), concepts in sorted(foreign_writes(index).items(),
                                             key=lambda item: (order(item[0][0]), order(item[0][1]))):
        verbs = sorted({verb for verbs in concepts.values() for verb in verbs})
        findings.append(f"{index.domains[source]['name']} {' and '.join(verbs)} {', '.join(sorted(concepts))}, "
                        f"which {index.domains[target]['name']} owns (boundary leak).")
    pending = [item for item in index.raw.get('unassigned', ()) if item.get('status') == 'pending']
    if pending:
        findings.append(f"{', '.join(index.name(item['subject_id']) for item in pending)} "
                        f"{'is' if len(pending) == 1 else 'are'} not modelled; see [Gaps](gaps.md).")
    statuses = Counter(rule.get('enforcement_status') for rule in index.rules.values())
    verified = statuses.pop('verified_on_trace', 0)
    breakdown = ', '.join(f"{count} {PLAIN_STATUS.get(status, status)}"
                          for status, count in
                          sorted(statuses.items(), key=lambda item: (-item[1], str(item[0]))))
    findings.append(f"{'None' if not verified else verified} of the {plural(len(index.rules), 'rule')} "
                    f"{'is' if verified <= 1 else 'are'} confirmed to run on a call path we followed"
                    + (f': {breakdown}.' if breakdown else '.') + ' See [Rules](rules.md).')
    roles = [activity for activity in index.activities.values() if index.access(activity)[0]]
    if roles and not any(index.access(activity)[1] for activity in roles):
        conditions = sorted({condition for activity in roles for condition in index.role_conditions(activity)},
                            key=lambda text: (-len(text), text))
        switched_off = security_off(conditions)
        if switched_off and on_method_security(conditions):
            findings.append(f'Role checks (@PreAuthorize) are switched off by the default setting ({switched_off}); '
                            'they apply only when Spring method security is enabled. See [Roles](glossary.md#roles).')
        else:
            text = f' They apply only when: {conditions[0].rstrip(".")}.' if conditions else ''
            findings.append('Role checks are written in the code but not confirmed to be enforced.' + text
                            + ' See [Roles](glossary.md#roles).')
    conflicts = sum(claim.get('kind') in ('conflict', 'contradiction') for claim in index.claims.values())
    if conflicts:
        findings.append(f"{plural(conflicts, 'disagreement')} between the code and its API contract, tests or "
                        'configuration (some overlap). See [Gaps](gaps.md).')
    return ['## Key findings', '', *[f'- {item}' for item in findings]]


def relationships_table(index: Model) -> list:
    """Context relationships with the DDD pattern each one suggests."""
    order = index.domain_order.index
    rows = []
    groups = defaultdict(list)
    for relationship in index.relationships.values():
        source, target = relationship.get('from_domain_id'), relationship.get('to_domain_id')
        if source in index.domains and target in index.domains and source != target:
            groups[(source, target)].append(relationship)
    for (source, target), items in sorted(groups.items(), key=lambda item: (order(item[0][0]), order(item[0][1]))):
        traces = {trace_id for item in items for trace_id in item.get('trace_ids') or ()}
        untraced = sum(not item.get('trace_ids') for item in items)
        readers = len({item.get('from_activity_id') for item in items})
        writers = len({item.get('to_activity_id') for item in items})
        rows.append((index.domains[source]['name'], index.domains[target]['name'],
                     'Customer/supplier (From reads To)',
                     f'{plural(readers, "use case")} read{"s" if readers == 1 else ""} data written by {writers}; '
                     f'{plural(len(traces), "call path")} followed'
                     + (f', {plural(untraced, "link")} with no call path found' if untraced else '')
                     + (' · also reverse direction' if (target, source) in groups else '')))
    for (source, target), concepts in sorted(foreign_writes(index).items(),
                                             key=lambda item: (order(item[0][0]), order(item[0][1]))):
        rows.append((index.domains[source]['name'], index.domains[target]['name'],
                     'Boundary leak (From writes data To owns)',
                     ', '.join(f"{'/'.join(sorted(verbs))} {name}" for name, verbs in sorted(concepts.items()))))
    for concept_id in sorted(index.concepts):
        owners = index.owners(concept_id)
        for position, first in enumerate(owners):
            for second in owners[position + 1:]:
                rows.append((index.domains[first]['name'], index.domains[second]['name'],
                             'Shared kernel candidate (both claim ownership)', index.name(concept_id)))
    if not rows:
        return []
    return ['## Context relationships', '',
            'DDD pattern suggested by each link (inferred from data use; not a design decision).', '',
            *table([('From', False), ('To', False), ('Relationship', False), ('Evidence', False)], rows), '']


def readme(index: Model, entities: Entities, coverage=()) -> str:
    domains = [index.domains[domain_id] for domain_id in index.domain_order]
    lines = ['# Domain model', '', *model_banner(index, compact=True), '',
             '[Rules](rules.md) · [Glossary](glossary.md) · [Gaps](gaps.md)'
             '<span class="files-only"> · [index.html](index.html) (all pages with diagrams; needs a CDN)</span>', '']
    missing = [item for item, expected, found in coverage if expected != found]
    if missing:
        lines += [f"> **Incomplete export:** {', '.join(missing)} not fully present; see [Gaps](gaps.md).", '']
    lines += ['## At a glance', '',
              *table([('Bounded contexts', True), ('Use cases', True), ('Entities', True),
                      ('Business rules', True), ('Context links', True)],
                     [(len(domains), len(index.activities), len(index.concepts), len(index.rules),
                       len(index.relationships))]),
              '', *summary(index), '', '## Context map', '',
              '**Legend:** solid → reads data from · dashed → reads, but for some links no call path was found · '
              'thick ⇒ writes data another context owns · dotted ↔ both claim ownership.', '',
              '```mermaid', context_map(index), '```', '', *relationships_table(index), '## Bounded contexts', '']
    supports = {domain.get('support') for domain in domains}
    states = {domain.get('review_state') for domain in domains}
    columns = [('Context', False), ('What it does', False), ('Use cases', True), ('Entities', True), ('Rules', True)]
    rows = [[f"[{cell(domain['name'])}](contexts/{index.domain_pages[domain['id']]}.md)",
             cell(first_sentence(domain['summary'])), len(domain['activity_memberships']),
             len(domain.get('concepts', ())), len(domain.get('rules', ()))] for domain in domains]
    if len(supports) > 1:
        columns.append(('Support', False))
        for row, domain in zip(rows, domains):
            row.append(badge(domain.get('support'), SUPPORT))
    lines += table(columns, rows)
    lines += ['']
    if len(supports) == 1:
        lines.append(f"All contexts: {badge(next(iter(supports)), SUPPORT)}"
                     + (f"; review state {next(iter(states))}" if len(states) == 1 and None not in states else '') + '.')
    lines.append('Shared entities and rules count once per context.')
    diagram = entities.diagram(sorted(index.concepts))
    if diagram:
        lines += ['', '## Entity model', '',
                  "Classes shown as `Class (table)`. ◆ = cascaded one-to-many; the parent owns its parts' lifecycle.",
                  '', '```mermaid', diagram, '```']
    aggregates = entities.aggregates()
    if aggregates:
        lines += ['', '## Aggregates', '',
                  'Candidates from JPA cascades: cascaded children sit inside the root; other associations are '
                  'references.', '']
        lines += table([('Aggregate root', False), ('Inside the aggregate', False),
                        ('References other aggregates', False), ('Members with their own repository', False)],
                       [(code(root), ', '.join(code(name) for name in members) or '-',
                         ', '.join(code(name) for name in references) or '-',
                         ', '.join(code(name) for name in direct) or '-')
                        for root, members, references, direct in aggregates])
        if any(direct for _, _, _, direct in aggregates):
            lines += ['', 'A member with its own repository can be saved or deleted without going through its root, '
                          'so the aggregate boundary is not enforced in code.']
    er = entities.er_diagram()
    if er:
        lines += ['', '## Data model', '',
                  'Tables as mapped by JPA. SQL schema scripts can differ by database; see [Rules](rules.md).',
                  '', '```mermaid', er, '```']
    lines += ['', '<details><summary>What the labels mean</summary>', '']
    lines += table([('Label', False), ('Meaning', False)], [
        ('backed by code / partly backed by code', 'How much of a context or use case we could follow through the code. '
                                                   '"Partly" means some call paths stop at framework or generated code.'),
        ('strong / some / little evidence', 'How well the cited code, contract or tests support a rule. It does not '
                                            'mean the rule is confirmed to run.'),
        ('in code, not confirmed', 'The check is written in the code, but we could not show that it runs.'),
        ('in contract + tests / in contract only / in tests only',
         'The rule comes from the API contract or from tests, not from the application code.'),
        ('only under some settings', 'The rule applies only with a certain setting or profile.'),
        ('enforcement unknown', 'We could not tell where, or whether, the rule is enforced.'),
        ('code path not fully followed', 'We could not follow the use case all the way to the database.'),
        ('role (in code)', 'The role is named in the code (for example with @PreAuthorize), but that does not prove it is '
                           'checked when the app runs.'),
    ])
    lines += ['', '</details>', '', '_Generated by `speed discover domains --export ddd`; do not edit._']
    return '\n'.join(lines) + '\n'


def completeness(coverage) -> list:
    """The export's self-check, collapsed at the end of the gaps page."""
    if not coverage:
        return []
    complete = sum(expected == found for _, expected, found in coverage)
    header = [('Item', False), ('In the model', True), ('Found in the documents', True)]
    rows = [(item, expected, found) for item, expected, found in coverage]
    if complete < len(coverage):
        header.append(('Status', False))
        rows = [row + ('complete' if row[1] == row[2] else 'MISSING',) for row in rows]
    return ['', f'<details><summary>Export completeness: {complete} of {len(coverage)} record types fully present'
                '</summary>', '', *table(header, rows), '', '</details>']


def context_map(index: Model) -> str:
    lines = ['flowchart LR']
    for domain_id in index.domain_order:
        domain = index.domains[domain_id]
        lines.append(f'  {node("D", domain_id)}["{label(domain["name"])}<br/>'
                     f'{plural(len(domain["activity_memberships"]), "use case")} · '
                     f'{plural(len(domain.get("rules", ())), "rule")}"]')
    groups = defaultdict(list)
    for relationship in index.relationships.values():
        source, target = relationship.get('from_domain_id'), relationship.get('to_domain_id')
        if source in index.domains and target in index.domains and source != target:
            groups[(source, target, relationship['kind'])].append(relationship)
    order = index.domain_order.index
    for (source, target, kind), items in sorted(groups.items(), key=lambda item: (
            order(item[0][0]), order(item[0][1]), item[0][2])):
        dashed = any(not item.get('trace_ids') for item in items)
        readers = len({item.get('from_activity_id') for item in items})
        writers = len({item.get('to_activity_id') for item in items})
        text = label(f'{plural(readers, "use case")} read{"s" if readers == 1 else ""} data from {writers}' if kind == 'uses_information_from'
                     else f'{kind.replace("_", " ")} ({len(items)})')
        arrow = f'-. "{text}" .->' if dashed else f'-- "{text}" -->'
        lines.append(f'  {node("D", source)} {arrow} {node("D", target)}')
    for (source, target), concepts in sorted(foreign_writes(index).items(),
                                             key=lambda item: (order(item[0][0]), order(item[0][1]))):
        text = ', '.join(f"{'/'.join(sorted(verbs))} {name}" for name, verbs in sorted(concepts.items()))
        lines.append(f'  {node("D", source)} == "{label(text)}" ==> {node("D", target)}')
    shared = defaultdict(list)
    for concept_id in sorted(index.concepts):
        owners = index.owners(concept_id)
        for position, first in enumerate(owners):
            for second in owners[position + 1:]:
                shared[(first, second)].append(index.name(concept_id))
    for (first, second), names in sorted(shared.items(), key=lambda item: (order(item[0][0]), order(item[0][1]))):
        lines.append(f'  {node("D", first)} <-. "{label("both own " + ", ".join(sorted(names)))}" .-> '
                     f'{node("D", second)}')
    return '\n'.join(lines)


def foreign_writes(index: Model) -> dict:
    """{(writer, owner): {concept name: verbs}} for writes to data another context owns."""
    result = defaultdict(lambda: defaultdict(set))
    for concept_id, by_domain in index.concept_usage().items():
        owners = index.owners(concept_id)
        for domain_id, verbs in by_domain.items():
            writes = set(verbs) & set(WRITES)
            if writes and owners and domain_id not in owners:
                for owner in owners:
                    result[(domain_id, owner)][index.name(concept_id)] |= writes
    return result


def use_case_diagrams(index: Model, domain: dict) -> list:
    activities = index.sorted_records(index.activities,
                                      [item['activity_id'] for item in domain['activity_memberships']])
    chunks = [activities[start:start + MAX_USE_CASES]
              for start in range(0, len(activities), MAX_USE_CASES)]
    diagrams = []
    for part, chunk in enumerate(chunks, 1):
        lines = ['flowchart LR']
        access = {activity['id']: index.access(activity) for activity in chunk}
        roles = sorted({role for activity in chunk for role in index.roles(activity)})
        for role in roles:
            declared = all(not access[activity['id']][1] for activity in chunk
                           if role in index.roles(activity)) and role != NO_ROLE
            shown = f'{role} (in code)' if declared else role
            lines.append(f'  R_{slug(role).replace("-", "_")}["{label(shown)}"]:::actor')
        title = domain['name'] + (f' (part {part} of {len(chunks)})' if len(chunks) > 1 else '')
        lines.append(f'  subgraph {node("S", domain["id"])}{part}["{label(title)}"]')
        for activity in chunk:
            entry = ', '.join(sorted(index.entry_point(anchor_id) for anchor_id in activity['anchor_ids']))
            style = ':::unresolved' if activity.get('implementation_status') != 'implemented' else ''
            lines.append(f'    {node("U", activity["id"])}(["{label(activity["name"])}<br/>'
                         f'{label(entry)}"]){style}')
        lines.append('  end')
        for activity in chunk:
            arrow = '-->' if access[activity['id']][1] else '-.->'
            for role in index.roles(activity):
                lines.append(f'  R_{slug(role).replace("-", "_")} {arrow} {node("U", activity["id"])}')
        lines.append('  classDef actor fill:#eef,stroke:#446,color:#1a1a2e')
        lines.append('  classDef unresolved stroke-dasharray: 5 5')
        diagrams.append('\n'.join(lines))
    return diagrams


LAYERS = ('User interface', 'API contract', 'Unmatched client calls', 'Controllers', 'Application services', 'Repositories',
          'Mappers', 'Entities', 'Other classes', 'Tables')


def component_diagram(sequences: 'Sequences', trace_ids) -> tuple:
    """(Mermaid flowchart, {layer: names}) of the class-level calls on the given traces."""
    links = set().union(*(sequences.links.get(trace_id, set()) for trace_id in trace_ids)) if trace_ids else set()
    nodes = sorted({node for link in links for node in link}, key=lambda item: (item[1], str(item[0])))
    if not nodes:
        return '', {}
    layers = defaultdict(list)
    for kind, name in nodes:
        layers[sequences.layer(kind, name)].append(name)
    ids = {node: f'N{position}' for position, node in enumerate(nodes, 1)}
    lines = ['flowchart LR']
    for layer in LAYERS:
        members = [node for node in nodes if sequences.layer(*node) == layer]
        if not members:
            continue
        lines.append(f'  subgraph {slug(layer).replace("-", "_")}["{label(layer)}"]')
        lines.append('    direction TB')
        for kind, name in members:
            shown = f'{name} table' if kind == 'table' else name
            shape = f'[("{label(shown)}")]' if kind == 'table' else f'["{label(shown)}"]'
            lines.append(f'    {ids[(kind, name)]}{shape}')
        lines.append('  end')
    for source, target in sorted(links, key=lambda link: (link[0][1], link[1][1])):
        lines.append(f'  {ids[source]} --> {ids[target]}')
    return '\n'.join(lines), {layer: sorted(set(layers[layer])) for layer in LAYERS if layers.get(layer)}


def rule_line(rule: dict) -> str:
    return f"[{rule['name']}](../rules.md#rule-{short(rule['id'])}) · {rule_status(rule, brief=True)}"


NOT_DRAWN = {
    'its call path has no step outside the entry point': 'Page only, no server call traced',
    'no call path starts at its entry point': 'No call path starts here',
}
HTTP_ENTRY = re.compile(r'^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) ')
METHOD_SECURITY = re.compile(r'method security|security\.enable', re.I)


def security_off(conditions) -> str:
    """The 'x.enable=false' setting a precondition says is declared, else ''."""
    for condition in conditions:
        found = re.search(r'([\w.]*security[\w.]*\s*=\s*false)', condition or '', re.I)
        if found:
            return found.group(1).replace(' ', '')
    return ''


def security_rest(condition: str) -> str:
    """The part of a method-security condition after "Spring method security is enabled"."""
    return re.sub(r'^\s*(Spring\s+)?method security is enabled[.;,]?\s*', '', condition or '', flags=re.I).rstrip('.')


def on_method_security(conditions) -> bool:
    """True when every given precondition is about Spring method security."""
    conditions = list(conditions)
    return bool(conditions) and all(METHOD_SECURITY.search(condition) for condition in conditions)


def context_page(index: Model, entities: Entities, sequences: Sequences, domain_id: str) -> str:
    domain = index.domains[domain_id]
    support = domain.get('support')
    activities = index.sorted_records(index.activities,
                                      [item['activity_id'] for item in domain['activity_memberships']])
    lines = [f"# {domain['name']}", '',
             f"_Bounded context · {badge(support, SUPPORT)}_", '',
             '[Back to the domain model](../README.md)', '',
             domain.get('summary') or '', '',
             '## Why this boundary', '', domain.get('boundary_rationale') or '-', '']
    if domain.get('alternatives'):
        lines += ['### Boundaries considered and not chosen', '']
        for item in domain['alternatives']:
            subjects = [index.name(subject) for subject in item.get('subject_ids', ())]
            if len(subjects) > 3:
                lines += [f"- **{subjects[0]} and {len(subjects) - 1} other use cases**: {item.get('explanation', '')}",
                          f"  <details><summary>All {len(subjects)} use cases</summary>{cell(', '.join(subjects))}</details>"]
            else:
                lines.append(f"- **{', '.join(subjects) or 'Alternative'}**: {item.get('explanation', '')}")
        lines.append('')
    if domain.get('exclusions'):
        lines += ['### Deliberately left out', '']
        for item in domain['exclusions']:
            subjects = ', '.join(index.name(subject) for subject in item.get('subject_ids', ()))
            lines.append(f"- **{subjects}**: {item.get('explanation', '')}")
        lines.append('')
    if domain.get('unresolved_questions'):
        lines += [f"See [Gaps](../gaps.md#open-questions) for {plural(len(domain['unresolved_questions']), 'open question')}.", '']

    lines += ['## Use cases', '']
    for diagram in use_case_diagrams(index, domain):
        lines += ['```mermaid', diagram, '```', '']
    qualifiers = {}
    for activity in activities:
        roles, enforced = index.access(activity)
        if roles:
            qualifiers[activity['id']] = '' if enforced else (' (in code, only under some settings)' if index.role_conditions(activity)
                                                              else ' (in code, not confirmed)')
    common = set(qualifiers.values())
    uniform = len(common) == 1 and common != {''}
    conditions = [condition for activity in activities for condition in index.role_conditions(activity)]
    security = on_method_security(conditions)
    switched_off = security_off(conditions)
    role_note = (f'written in the code with @PreAuthorize, but switched off by the default setting ({switched_off})'
                 if uniform and switched_off
                 else 'written in code, applies only when Spring method security is on, not confirmed to be enforced'
                 if uniform and common == {' (in code, only under some settings)'} and security
                 else 'written in code, applies only under some settings, not confirmed to be enforced'
                 if uniform and common == {' (in code, only under some settings)'}
                 else 'written in code, not confirmed to be enforced')
    dashed = any(activity.get('implementation_status') != 'implemented' for activity in activities)
    lines += [('Dashed box: code path not fully followed. ' if dashed else '') + 'Dashed arrow'
              + (' and Roles column' if uniform else '') + f': role {role_note}.', '']
    rows, details = [], []
    # Files of implementations the declared profile does not run are cited last.
    inactive = {name for choice in sequences.choices.values() for name in choice['inactive'] - choice['runs']}
    for activity in activities:
        roles, _ = index.access(activity)
        role_text = (', '.join(roles) + ('' if uniform else qualifiers.get(activity['id'], ''))) if roles else NO_ROLE
        entry = '<br>'.join(cell(index.entry_point(anchor_id)) for anchor_id in sorted(
            activity['anchor_ids'], key=index.entry_point))
        status = badge(activity.get('implementation_status'), IMPLEMENTATION)
        if activity.get('support') != support:
            status += f", {badge(activity.get('support'), SUPPORT)}"
        description = activity.get('description') or ''
        brief = first_sentence(description, 160)
        rest = description.strip()
        while brief and HTTP_ENTRY.match(brief) and len(brief) < 70 and rest[len(brief):].strip():
            rest = rest[len(brief):].strip()
            brief = first_sentence(rest, 160)
        rows.append((f"**{cell(activity['name'])}**" + (f"<br>{cell(brief)}" if brief else ''), entry,
                     cell(role_text), status, index.cite(activity.get('evidence_ids'), avoid=inactive)))
        if description and description.strip() != brief:
            details.append(f"- **{activity['name']}**: {description}")
    lines += table([('Use case', False), ('Entry points', False), ('Roles', False), ('Implementation', False),
                    ('Evidence', False)], rows)
    if activities and all(activity.get('support') == support for activity in activities):
        lines += ['', f'All use cases here: {badge(support, SUPPORT)}.']
    if details:
        lines += ['', '<details><summary>Use case details</summary>', '', *details, '', '</details>']
    callers = sorted({activity.get('actor') for activity in activities if activity.get('actor')})
    if callers:
        lines += ['', '<details><summary>Callers</summary>', '']
        lines += [f'- {caller}' for caller in callers]
        lines += ['', '</details>']

    concept_ids = sorted(set(domain.get('concepts', ())))
    usage = index.concept_usage()
    # Entities this context's use cases touch without the model placing them here.
    touched = sorted({concept_id for concept_id, domains in usage.items()
                      if domain_id in domains and concept_id in index.concepts} - set(concept_ids))
    lines += ['', '## Entities', '']
    if concept_ids or touched:
        owned = defaultdict(list)
        for ownership_id in domain.get('ownership_ids', ()):
            ownership = index.ownerships.get(ownership_id)
            if ownership:
                owned[ownership['concept_id']].append(ownership)
        unresolved = index.unresolved_usage()
        rows = []
        for concept in index.sorted_records(index.concepts, concept_ids + touched):
            types = ', '.join(code(name.split('.')[-1]) for name in concept.get('qualified_type_names', ())) \
                or 'none (table only)'
            ownership = '; '.join(item['kind'] + (f" ({badge(item.get('support'), SUPPORT)})"
                                                  if item.get('support') != support else '')
                                  for item in owned.get(concept['id'], ()))
            if not ownership:
                verbs = usage.get(concept['id'], {}).get(domain_id) or set()
                ownership = 'reads only' if verbs == {'reads'} else \
                    f'used, not owned ({verbs_text(verbs)})' if verbs else 'used, not owned'
            others = sorted((set(usage.get(concept['id'], {})) | set(index.concept_domains[concept['id']]))
                            - {domain_id}, key=index.domain_order.index)
            used_by = ', '.join(
                index.domains[other]['name']
                + (f" ({verbs_text(usage[concept['id']][other])}"
                   + ('; not fully resolved' if (concept['id'], other) in unresolved else '') + ')'
                   if usage.get(concept['id'], {}).get(other) else '')
                for other in others) or '-'
            rows.append((f"[{cell(concept['name'])}](../glossary.md#term-{short(concept['id'])})", types,
                         cell(', '.join(entities.concept_tables(concept['id']))), cell(ownership),
                         cell(used_by)))
        lines += table([('Entity', False), ('Code type', False), ('Table', False),
                        ('Ownership here', False), ('Also used by', False)], rows)
        claims = [item for items in owned.values() for item in items]
        if claims and all(item.get('support') == support for item in claims):
            lines += ['', f'Ownership claims here: {badge(support, SUPPORT)}.']
        diagram = entities.diagram(concept_ids, flatten_bases=True, external=touched)
        if diagram:
            lines += ['', '```mermaid', diagram, '```']
        constraints = entities.constraints(concept_ids)
        if constraints:
            lines += ['', 'Field constraints:', '']
            lines += table([('Class', False), ('Field', False), ('Constraints', False)],
                           [(name, field, ', '.join(code('@' + item) for item in checks))
                            for name, field, checks in constraints])
        reasons = [item for ownership_id in domain.get('ownership_ids', ())
                   if (item := index.ownerships.get(ownership_id))]
        if reasons:
            lines += ['', '<details><summary>Why this context owns its data</summary>', '']
            for item in sorted(reasons, key=lambda item: index.name(item['concept_id'])):
                questions = len(item.get('unresolved_questions', ()))
                lines.append(f"- **{index.name(item['concept_id'])}** ({item['kind']}): {item.get('rationale', '')}"
                             + (f" ({plural(questions, 'open question')} in [Gaps](../gaps.md#open-questions))"
                                if questions else ''))
            lines += ['', '</details>']
    else:
        lines.append('No entities are attributed to this context.')

    data = data_access(index, activities)
    if data:
        used = [access for access in ACCESS_ORDER if any(row[access] for row in data.values())]
        lines += ['', '## Data it reads and writes', '',
                  "Database reads and writes found for this context's use cases, across every storage setup "
                  '(the call sequences below show only the configured Spring profile). Confirmed = we found the exact '
                  'database statement; may not happen = the step is possible but not certain.', '']

        def total(row):
            return row['resolved'] + row['unresolved'] + row['ambiguous']
        lines += table([('Table', False), *[(access.capitalize(), True) for access in used], ('Confirmed', True)],
                       [(cell(name), *[data[name][access] or '-' for access in used],
                         f"{data[name]['resolved']} of {total(data[name])}"
                         + (f" ({data[name]['ambiguous']} may not happen)" if data[name]['ambiguous'] else ''))
                        for name in sorted(data)])
        lines += ['', '<details><summary>Reads and writes by how sure we are</summary>', '']
        lines += table([('Table', False), *[(access.capitalize(), True) for access in used],
                        ('Confirmed', True), ('Not confirmed', True), ('May not happen', True)],
                       [(cell(name), *[(f"{data[name][access]} ({data[name][access + ':ambiguous']} may not happen)"
                                         if data[name].get(access + ':ambiguous') else data[name][access] or '-')
                                        for access in used],
                         data[name]['resolved'] or '-', data[name]['unresolved'] or '-',
                         data[name]['ambiguous'] or '-') for name in sorted(data)])
        lines += ['', '</details>']

    sequence_sections, not_drawn, drawn_traces = [], [], []
    captions = Counter(caption for activity in activities for _, caption, _ in sequences.diagrams(activity)[0])
    usual = captions.most_common(1)[0][0] if captions else ''
    for activity in activities:
        diagrams, skipped = sequences.diagrams(activity)
        has_page = any(not HTTP_ENTRY.match(title) for title, _, _ in diagrams)
        for title, caption, diagram in diagrams:
            heading = f"{activity['name']}: {title}"
            body = ['```mermaid', diagram, '```', '']
            steps = sum('->>' in line and 'Client->>' not in line for line in diagram.splitlines())
            if (has_page and HTTP_ENTRY.match(title)) or steps <= 2:
                reason = 'API-only path' if has_page and HTTP_ENTRY.match(title) else 'Short path'
                sequence_sections += [f'<details><summary>{reason}: {cell(heading)}</summary>', '',
                                      *([f'_{caption}_', ''] if caption != usual else []), *body, '</details>', '']
            else:
                sequence_sections += [f"### {heading}", '', *([f'_{caption}_', ''] if caption != usual else []), *body]
        drawn_traces += [trace_id for trace_id in activity.get('trace_ids', ())
                         if sequences.links.get(trace_id)]
        not_drawn += [(activity['name'], entry, reason) for entry, reason in skipped]
    diagram, _ = component_diagram(sequences, drawn_traces)
    if diagram:
        lines += ['', '## Architecture', '',
                  "Classes and tables on the call paths we followed for this context. Arrow = at least one call found.", '',
                  '```mermaid', diagram, '```']

    links = context_links(index, domain_id)
    if links:
        lines += ['', '## Links to other contexts', '', *links]

    profiles = ', '.join(sorted(sequences.active_profiles))
    lines += ['', '## Call sequences', '',
              'These call paths were worked out by reading the source code, not recorded from a running app. Calls '
              'are shown in the order they appear in the code; a branch is drawn only when its condition is known '
              '(opt/alt). Dotted arrow = a call or database step we could not fully confirm.'
              + (f' The database code shown is the version the configured Spring profile uses ({profiles}, from '
                 'spring.profiles.active); a different setting at startup can change this.' if profiles else '')
              + (f' Every call path below is {usual[len("Call path: "):].rstrip(".")} unless its caption says otherwise.'
                 if usual else ''), '']
    names = {name for trace_id in drawn_traces for link in sequences.links.get(trace_id, ()) for _, name in link}
    choices = {name: sequences.choices[name] for name in sorted(names) if name in sequences.choices}
    if choices:
        lines += ['<details><summary>Which code runs with the configured Spring profile</summary>', '']
        lines += table([('Interface', False), ('Runs', False), ('Other implementations', False)],
                       [(code(name), '; '.join(item.replace(', generated at runtime', ' (generated)')
                                               for item in sorted(choice['runs'])) or '-',
                         ', '.join(sorted(choice['inactive'] - choice['runs'])) or '-')
                        for name, choice in choices.items()])
        lines += ['', '</details>', '']
    lines += sequence_sections
    if not sequence_sections:
        lines.append('No traced call path in this context has more than one step.')
    if not_drawn:
        grouped = defaultdict(list)
        for name, entry, reason in not_drawn:
            grouped[NOT_DRAWN.get(reason, reason[:1].upper() + reason[1:])].append(f'{name} ({entry})')
        lines += ['', f'<details><summary>Call paths not drawn ({len(not_drawn)})</summary>', '']
        for reason, items in grouped.items():
            lines.append(f"- **{reason}:** {'; '.join(items)}")
        lines += ['', '</details>']

    rules = index.sorted_records(index.rules, domain.get('rules', ()))
    lines += ['', '## Business rules', '']
    if rules:
        by_category = defaultdict(list)
        for rule in rules:
            by_category[rule.get('category') or 'unclassified'].append(rule)
        for category in sorted(by_category, key=category_key):
            group = by_category[category]
            title = category_label(category)
            if category == 'authorization' and all(rule.get('enforcement_status') == 'conditional' for rule in group):
                security = on_method_security(condition for rule in group for condition in rule.get('preconditions') or ())
                switched_off = security_off(condition for rule in group for condition in rule.get('preconditions') or ())
                lines += [f"**{title} ({len(group)}):** all apply only "
                          + (f'when Spring method security is on, which the default setting ({switched_off}) switches off.'
                             if security and switched_off
                             else 'when Spring method security is on.' if security else 'under some settings.'),
                          '', '<details><summary>The rules</summary>', '']
                lines += [f'- {rule_line(rule)}' for rule in group]
                lines += ['', '</details>', '']
            else:
                lines += [f"**{title}**", '']
                lines += [f'- {rule_line(rule)}' for rule in group]
                lines.append('')
    else:
        lines.append('No rules are attributed to this context.')
    return '\n'.join(lines).rstrip() + '\n'


CATEGORY_LABELS = {'cross_record_constraint': 'Cross-record constraint', 'unclassified': 'Other'}


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category.replace('_', ' ').capitalize())


def category_key(category: str):
    return (CATEGORY_ORDER.index(category) if category in CATEGORY_ORDER else len(CATEGORY_ORDER), category)


def data_access(index: Model, activities) -> dict:
    rows = defaultdict(lambda: {**{access: 0 for access in ACCESS_ORDER},
                                'resolved': 0, 'unresolved': 0, 'ambiguous': 0})
    for activity in activities:
        for use_id in activity.get('information_use_ids', ()):
            use = index.uses.get(use_id)
            if not use:
                continue
            for resource_id in use.get('resource_ids', ()):
                resource = index.resources.get(resource_id, {})
                if resource.get('kind') != 'table':
                    continue
                row = rows[resource.get('name') or resource_id]
                if use.get('access') in row:
                    row[use['access']] += 1
                    if use.get('resolution') == 'ambiguous':
                        row[use['access'] + ':ambiguous'] = row.get(use['access'] + ':ambiguous', 0) + 1
                resolution = use.get('resolution')
                row[resolution if resolution in ('resolved', 'ambiguous') else 'unresolved'] += 1
    return dict(rows)


def context_links(index: Model, domain_id: str) -> list:
    rows = []
    for relationship in sorted(index.relationships.values(), key=lambda item: item['id']):
        source, target = relationship.get('from_domain_id'), relationship.get('to_domain_id')
        if source == target or source not in index.domains or target not in index.domains:
            continue
        if domain_id not in (source, target):
            continue
        other = target if source == domain_id else source
        direction = 'reads data from' if source == domain_id else 'is read by'
        here = relationship.get('from_activity_id') if source == domain_id else relationship.get('to_activity_id')
        there = relationship.get('to_activity_id') if source == domain_id else relationship.get('from_activity_id')
        rows.append((index.name(here or ''), direction, index.name(there or ''),
                     cell(', '.join(shared_data(index, relationship)) or '-'),
                     f"[{index.domains[other]['name']}]({index.domain_pages[other]}.md)",
                     'yes' if relationship.get('trace_ids') else 'no'))
    # Writes into data another context owns are links too, though the model keeps them as data accesses.
    for use in sorted(index.uses.values(), key=lambda item: item['id']):
        concept_id = use.get('concept_id')
        if use.get('access') not in WRITES or not concept_id:
            continue
        owners = index.owners(concept_id)
        traced = 'yes' if use.get('resolution') == 'resolved' else 'no'
        for writer in index.activity_domains.get(use.get('activity_id'), ()):
            if not owners or writer in owners:
                continue
            for owner in owners:
                if domain_id not in (writer, owner):
                    continue
                other = owner if writer == domain_id else writer
                here = index.name(use['activity_id']) if writer == domain_id else '-'
                there = '-' if writer == domain_id else index.name(use['activity_id'])
                # creates / updates / deletes -> created / updated / deleted
                direction = (f"{use['access']} data owned by" if writer == domain_id
                             else f"has data {use['access'][:-1]}d by")
                rows.append((here, direction, there, cell(index.name(concept_id)),
                             f"[{index.domains[other]['name']}]({index.domain_pages[other]}.md)", traced))
    if not rows:
        return []
    rows = sorted(set(rows))
    total = len(index.domains[domain_id]['activity_memberships'])
    groups = defaultdict(lambda: (set(), set(), set()))
    for here, direction, there, data, context, traced in rows:
        group = groups[(direction, data, context)]
        group[0].add(here)
        group[1].add(there)
        group[2].add(traced)

    def names(found):
        found = sorted(found - {'-'})
        return '-' if not found else f'All {total} use cases' if len(found) == total and total > 2 else ', '.join(found)
    grouped = [(names(heres), direction, names(theres), data, context,
                'yes' if traced == {'yes'} else 'no' if traced == {'no'} else 'partly')
               for (direction, data, context), (heres, theres, traced) in sorted(groups.items())]
    header = [('Use cases here', False), ('Link', False), ('Use cases there', False), ('Data', False),
              ('Context', False), ('Traced', False)]
    return [*table(header, grouped), '', f'<details><summary>All links ({len(rows)})</summary>', '',
            *table([('Use case here', False), ('Link', False), ('Use case there', False), ('Data', False),
                    ('Context', False), ('Traced', False)], rows), '', '</details>']


def shared_data(index: Model, relationship: dict) -> list:
    """Entities or tables the reading use case reads and the other use case writes."""
    def touched(activity_id, accesses):
        found = set()
        for use_id in index.activities.get(activity_id, {}).get('information_use_ids', ()):
            use = index.uses.get(use_id) or {}
            if use.get('access') in accesses:
                found |= {('concept', use['concept_id'])} if use.get('concept_id') else set()
                found |= {('resource', resource_id) for resource_id in use.get('resource_ids', ())}
        return found
    common = (touched(relationship.get('from_activity_id'), ('reads',))
              & touched(relationship.get('to_activity_id'), WRITES))
    concepts = sorted(index.name(identifier) for kind, identifier in common if kind == 'concept')
    return concepts or sorted(index.name(identifier) for kind, identifier in common if kind == 'resource')


def rules_page(index: Model) -> str:
    rules = sorted(index.rules.values(), key=lambda rule: (category_key(rule.get('category') or ''),
                                                          rule['name'], rule['id']))
    lines = ['# Business rules catalog', '', '[Back to the domain model](README.md)', '']
    if not rules:
        return '\n'.join(lines + ['No rules were extracted.']) + '\n'
    statuses = sorted({rule_status(rule, brief=True) for rule in rules})
    counts = Counter((rule.get('category') or 'unclassified', rule_status(rule, brief=True)) for rule in rules)
    categories = sorted({rule.get('category') or 'unclassified' for rule in rules}, key=category_key)
    verified = sum(rule.get('enforcement_status') == 'verified_on_trace' for rule in rules)
    lines += [f'{plural(len(rules), "rule")} from code, API contract and tests. '
              + ('None is confirmed to run on a call path we followed; "in code, not confirmed" means the check exists '
                 'in the code but we could not show that it runs.'
                 if not verified else f'{verified} confirmed to run on a call path we followed.'), '']

    title = category_label
    lines += table([('Category', False), *[(status[:1].upper() + status[1:], True) for status in statuses], ('Total', True)],
                   [(f'[{title(category)}](#{slug(title(category))})',
                     *[counts[(category, status)] or '-' for status in statuses],
                     sum(counts[(category, status)] for status in statuses)) for category in categories])
    lines.append('')
    same_check = defaultdict(list)
    for rule in rules:
        if rule.get('category') != 'authorization' and rule.get('predicate_or_formula'):
            same_check[rule['predicate_or_formula'].strip()].append(rule)
    current, shared_note = None, False
    for rule in rules:
        category = rule.get('category') or 'unclassified'
        if category != current:
            current = category
            lines += [f"## {title(current)}", '']
            group = [item for item in rules if (item.get('category') or 'unclassified') == current]
            conditions = [condition for item in group for condition in item.get('preconditions') or ()]
            shared_note = (current == 'authorization' and on_method_security(conditions)
                           and all(item.get('preconditions') for item in group))
            if shared_note:
                switched_off = security_off(conditions)
                lines += [f"All {len(group)} role checks are @PreAuthorize annotations that apply only when Spring method "
                          "security is on" + (f"; the default setting ({switched_off}) switches it off" if switched_off else '')
                          + '.', '']
        domains = ', '.join(f"[{index.domains[domain_id]['name']}](contexts/{index.domain_pages[domain_id]}.md)"
                            for domain_id in index.rule_domains.get(rule['id'], ())) or '-'
        lines += [f'<a id="rule-{short(rule["id"])}"></a>', f"### {rule['name']}", '',
                  f"{rule_status(rule, brief=True)} · {badge(rule.get('support'), EVIDENCE)}", '',
                  f'- **Context:** {domains}']
        if rule.get('preconditions') and not shared_note:
            lines.append(f"- **Applies when:** {'; '.join(rule['preconditions'])}")
        kind = 'Formula' if rule.get('evaluation_kind') == 'formula' else 'Checks'
        if rule.get('predicate_or_formula'):
            lines.append(f"- **{kind}:** {code(rule.get('predicate_or_formula'))}")
        elif rule.get('description'):
            lines.append(f"- **Rule:** {first_sentence(rule['description'])}")
        lines.append(f"- **Outcome:** {rule.get('outcome') or '-'}")
        others = [item for item in same_check.get((rule.get('predicate_or_formula') or '').strip(), ())
                  if item['id'] != rule['id']]
        if others:
            lines.append('- **Same check as:** ' + ', '.join(f"[{item['name']}](#rule-{short(item['id'])})"
                                                             for item in others))
        questions = rule.get('unresolved_questions', ())
        lines += ['', f"<details><summary>Where and why"
                      + (f" · {plural(len(questions), 'open question')}" if questions else '') + '</summary>', '']
        if rule.get('description'):
            lines += [rule['description'], '']
        if rule.get('preconditions') and shared_note:
            lines.append(f"- **Applies when:** {'; '.join(rule['preconditions'])}")
        activities = index.sorted_records(index.activities, rule.get('activity_ids', ()))
        if activities:
            lines.append('- **Use cases:** ' + ', '.join(activity['name'] for activity in activities))
        sites, cited = [], set()
        for site in rule.get('enforcement_sites', ()):
            found = index.citations(site.get('evidence_ids'), 1)
            cited.update(found)
            sites.append(f"{code(index.name(site.get('source_id', '')))} at {', '.join(code(item) for item in found) or '-'}"
                         + (f" when {code(site['condition'])}" if site.get('condition') else ''))
        lines.append('- **Enforced at:** ' + ('; '.join(sites) if sites else 'not found in the code we followed'))
        scope = rule.get('scope') or {}
        predicate = rule.get('predicate_or_formula') or ''
        scoped = [f'{key} {value}' for key, value in sorted(scope.items())
                  if value and key != 'entrypoint_ids' and str(value) not in predicate]
        if scoped:
            lines.append('- **Scope:** ' + ', '.join(scoped))
        lines.append('- **Basis:** ' + (', '.join(item.replace('_', ' ') for item in rule.get('basis', ())) or '-'))
        basis = set(rule.get('basis') or ())
        first = 'configuration' if 'contract_declared' in basis and 'source_observed' not in basis else None
        evidence = [item for item in index.citations(rule.get('evidence_ids'), 3, every_kind=True, first_kind=first)
                    if item not in cited]
        if evidence:
            lines.append(f"- **Evidence:** {', '.join(code(item) for item in evidence)}")
        if rule.get('conflicts'):
            lines.append('- **Conflicts with:** ' + ', '.join(index.name(item) for item in rule['conflicts']))
        for question in questions:
            lines.append(f'- **Open question:** {question}')
        lines += ['', '</details>', '']
    return '\n'.join(lines).rstrip() + '\n'


def verbs_text(verbs) -> str:
    verbs = set(verbs)
    return 'CRUD' if {'creates', 'reads', 'updates', 'deletes'} <= verbs and len(verbs) == 4 \
        else ', '.join(sorted(verbs))


def glossary_page(index: Model, entities: Entities) -> str:
    names = [name for concept in index.concepts.values() for name in concept.get('qualified_type_names', ())]
    packages = {name.rsplit('.', 1)[0] for name in names if '.' in name}
    package = next(iter(packages)) if len(packages) == 1 else None
    lines = ['# Glossary', '', '[Back to the domain model](README.md)', '',
             'Business terms with the class and table behind each.'
             + (f' All classes are in `{package}`.' if package else ''), '', '## Entities', '']
    usage = index.concept_usage()
    for concept in index.sorted_records(index.concepts, index.concepts):
        types = ', '.join(code(name.rsplit('.', 1)[-1] if package and name.startswith(package + '.') else name)
                          for name in concept.get('qualified_type_names', ())) or 'none (table only)'
        concept_tables = entities.concept_tables(concept['id'])
        tables = ', '.join(code(name) for name in concept_tables) or '-'
        owners = [f"{index.domains[ownership['domain_id']]['name']} ({ownership['kind']})"
                  for ownership in sorted(index.ownerships.values(), key=lambda item: item['id'])
                  if ownership['concept_id'] == concept['id'] and ownership.get('domain_id') in index.domains]
        contexts = sorted(set(index.concept_domains[concept['id']]) | set(usage.get(concept['id'], {})),
                          key=index.domain_order.index)
        used = ', '.join(index.domains[domain_id]['name']
                         + (f" ({verbs_text(usage[concept['id']][domain_id])})"
                            if usage.get(concept['id'], {}).get(domain_id) else '')
                         for domain_id in contexts)
        definition = next((claim['text'] for claim in index.claims_about.get(concept['id'], ())), None)
        # "Pet is persisted in the pets table" only repeats the Table line below.
        if definition and concept.get('qualified_type_names') and any(table in definition for table in concept_tables):
            definition = None
        lines += [f'<a id="term-{short(concept["id"])}"></a>', f"### {concept['name']}", '']
        if definition:
            lines += [definition, '']
        lines += [f'- **Code type:** {types}', f'- **Table:** {tables}',
                  f"- **Owned by:** {', '.join(owners) or 'no owning context'}"
                  + (' · shared-kernel candidate ([context map](README.md#context-map))' if len(owners) > 1 else ''),
                  f"- **Used in:** {used or '-'}", '']
    lines += ['## Roles', '']
    roles = defaultdict(lambda: [0, False, set()])
    for activity in index.activities.values():
        names, enforced = index.access(activity)
        for role in names:
            roles[role][0] += 1
            roles[role][1] |= enforced
            roles[role][2].update(index.role_conditions(activity))
    conditions = sorted({condition for _, _, found in roles.values() for condition in found},
                        key=lambda text: (-len(text), text))
    if roles and not any(enforced for _, enforced, _ in roles.values()):
        switched_off = security_off(conditions)
        lines += [(f'Roles are written in the code with @PreAuthorize, but they are switched off by the default '
                   f'setting ({switched_off}); they apply only when Spring method security is on.'
                   if switched_off and on_method_security(conditions)
                   else 'Roles are declared and apply only when Spring method security is enabled. No traced path proves enforcement.'
                   if on_method_security(conditions)
                   else 'Roles are declared' + (f'; they apply only when: {conditions[0].rstrip(".")}' if conditions else '')
                   + '. No traced path proves enforcement.'), '']
    rows = [(role + (' (enforced)' if enforced else ''), count) for role, (count, enforced, _) in sorted(roles.items())]
    unspecified = sum(not index.access(activity)[0] for activity in index.activities.values())
    if unspecified:
        rows.append((NO_ROLE, unspecified))
    if rows:
        lines += table([('Role', False), ('Use cases', True)], rows)
        lines += ['', 'A use case can declare several roles.']
    if conditions:
        lines += ['', '<details><summary>Conditions as declared</summary>', '']
        lines += [f"- **{role}**: {max(sorted(found), key=len)}" for role, (_, _, found) in sorted(roles.items()) if found]
        lines += ['', '</details>']
    return '\n'.join(lines).rstrip() + '\n'


RETURNED_STATUS = re.compile(r'returns?\s+(?:HTTP\s+)?(?:status\s+)?(\d{3})')
ANALYSIS_LIMITS = (
    (re.compile(r'(active|declared|selected|chosen|Spring) profiles?\b|profile-selected|by profile', re.I),
     'Which repository implementation runs depends on the Spring profile'),
    (re.compile(r'@PreAuthorize|method security|security\.enable', re.I), 'Role checks depend on method security being on'),
    (re.compile(r'\bcommit(s|ted)?\b', re.I), 'Whether a write is committed is not proven'),
    (re.compile(r'MapStruct|generated (repository|implementation|code|mapper|query)', re.I),
     'Generated code (MapStruct, Spring Data) is not traced'),
)
# A question that names a status code, the contract or a constraint is about behaviour, whatever else it mentions.
BEHAVIOUR = re.compile(r'\b(4\d\d|20\d)\b|contract|foreign key|flush|JDBC path|correctly owned', re.I)


def gaps_page(index: Model) -> str:
    model = index.raw
    lines = ['# Gaps', '', '[Back to the domain model](README.md)', '',
             'What the analysis could not confirm from the code.', '',
             *model_banner(index, link_gaps=False), '']
    hidden = [domain for domain_id, domain in sorted(model.get('domains', {}).items())
              if domain_id not in index.domains]
    if hidden:
        lines += ['## Contexts not shown', '']
        lines += table([('Context', False), ('Support', False), ('Review state', False), ('Use cases', True),
                        ('Rules', True)],
                       [(cell(domain['name']), badge(domain.get('support'), SUPPORT), domain.get('review_state', '-'),
                         len(domain.get('activity_memberships', ())), len(domain.get('rules', ())))
                        for domain in hidden])
        lines.append('')
    homeless = index.sorted_records(index.activities, [activity_id for activity_id in index.activities
                                                       if not index.activity_domains.get(activity_id)])
    if homeless:
        lines += ['## Use cases outside every context shown', '']
        lines += table([('Use case', False), ('Entry points', False)],
                       [(cell(activity['name']), cell(', '.join(index.entry_point(anchor_id)
                                                               for anchor_id in activity.get('anchor_ids', ()))))
                        for activity in homeless])
        lines.append('')
    unassigned = sorted(model.get('unassigned', ()), key=lambda item: index.name(item['subject_id']))
    pending = [item for item in unassigned if item.get('status') == 'pending']
    excluded = [item for item in unassigned if item.get('status') != 'pending']
    if unassigned:
        lines += ['## Entry points not modelled', '']
        if pending:
            lines += table([('Entry point', False), ('Reason', False)],
                           [(cell(index.name(item['subject_id'])),
                             cell(index.readable(item.get('reason') or '').replace(
                                 f"the call path from {index.name(item['subject_id'])}", 'its call path')))
                            for item in pending])
        else:
            lines.append('Every business entry point is modelled.')
        if excluded:
            lines += ['', f'<details><summary>Excluded as non-business ({len(excluded)})</summary>', '']
            lines += table([('Entry point', False), ('Reason', False)],
                           [(cell(index.name(item['subject_id'])), cell(item.get('reason'))) for item in excluded])
            lines += ['', '</details>']
        lines.append('')
    conflicts = sorted((claim for claim in index.claims.values()
                        if claim.get('kind') in ('conflict', 'contradiction')),
                       key=lambda claim: (index.name(claim['subject_id']), claim['id']))
    if conflicts:
        lines += ['## Contract and implementation disagreements', '']
        patterns, other = defaultdict(set), []
        for claim in conflicts:
            status = RETURNED_STATUS.search(claim['text'])
            if status and 'contract' in claim['text']:
                patterns[status.group(1)].add(index.name(claim['subject_id']))
            else:
                other.append(claim)
        rows = [(f'Code returns {status}; the contract does not declare it', len(names), cell(', '.join(sorted(names))))
                for status, names in sorted(patterns.items())]
        rows += [(cell(claim['text']), 1, cell(index.name(claim['subject_id']))) for claim in other]
        lines += table([('Pattern', False), ('Use cases', True), ('Which', False)], rows)
        lines += ['', f'<details><summary>All disagreements ({len(conflicts)})</summary>', '']
        lines += table([('About', False), ('Disagreement', False), ('Evidence', False)],
                       [(cell(index.name(claim['subject_id'])), cell(claim['text']),
                         index.cite(claim.get('evidence_ids'), every_kind=True)) for claim in conflicts])
        lines += ['', '</details>', '']
    questions = []
    for domain_id in index.domain_order:
        domain = index.domains[domain_id]
        questions += [(domain['name'], question) for question in domain.get('unresolved_questions', ())]
    for ownership in sorted(index.ownerships.values(), key=lambda item: item['id']):
        if ownership.get('domain_id') in index.domains:
            subject = f"{index.name(ownership['concept_id'])} data ({index.domains[ownership['domain_id']]['name']})"
            questions += [(subject, question) for question in ownership.get('unresolved_questions', ())]
    for activity in index.sorted_records(index.activities, index.activities):
        questions += [(activity['name'], question) for question in activity.get('unresolved_questions', ())]
    if questions:
        lines += ['## Open questions', '']
        limits, behaviour = Counter(), []
        for subject, question in questions:
            limit = None if BEHAVIOUR.search(question) else next(
                (name for pattern, name in ANALYSIS_LIMITS if pattern.search(question)), None)
            if limit:
                limits[limit] += 1
            else:
                behaviour.append((subject, question))
        if behaviour:
            lines += [f'### Behaviour questions ({len(behaviour)})', '']
            lines += table([('About', False), ('Question', False)],
                           [(cell(subject), cell(question)) for subject, question in behaviour])
            lines.append('')
        if limits:
            lines += ['### Analysis limits', '']
            lines += table([('Limit', False), ('Questions', True)],
                           [(name, limits[name]) for _, name in ANALYSIS_LIMITS if limits[name]])
            lines.append('')
        rule_questions = sum(len(rule.get('unresolved_questions', ())) for rule in index.rules.values())
        lines += ([f'Questions about individual rules ({rule_questions}) are on the [Rules](rules.md) page.', '']
                  if rule_questions else [])
        lines += [f'<details><summary>All questions about contexts, data and use cases ({len(questions)})</summary>', '']
        lines += table([('About', False), ('Question', False)],
                       [(cell(subject), cell(question)) for subject, question in questions])
        lines += ['', '</details>', '']
    open_uses = defaultdict(list)
    for use in index.uses.values():
        if use.get('resolution') != 'resolved':
            for resource_id in use.get('resource_ids', ()):
                open_uses[(index.name(resource_id), use.get('access') or '-', use.get('resolution'))].append(use)
    if open_uses:
        unresolved = sum(use.get('resolution') != 'resolved' for use in index.uses.values())
        lines += ['## Database reads and writes not fully confirmed', '',
                  f'{unresolved} of {len(index.uses)} database reads and writes are not fully confirmed: we know the '
                  'table, but not the exact statement, whether it completes, which code runs it, or whether it '
                  'happens at all.', '', '<details><summary>By table</summary>', '']
        rows = []
        for (table_name, access, resolution), uses in sorted(open_uses.items()):
            reasons = sorted({first_sentence(re.sub(r'^(The operation facts of this use are unresolved:|Unresolved:)\s*',
                                                    '', use.get('reason') or ''), 140)
                              for use in uses if use.get('reason')})
            text = '<br>'.join(cell(reason) for reason in reasons[:3])
            if len(reasons) > 3:
                text += f'<br>and {len(reasons) - 3} more reasons'
            rows.append((cell(table_name), access, {'ambiguous': 'may not happen'}.get(resolution, 'not confirmed'),
                         len(uses), text or '-'))
        lines += table([('Table', False), ('Access', False), ('How sure', False), ('Count', True),
                        ('Reasons', False)], rows)
        lines += ['', '</details>', '']
    warnings = Counter(item.get('code') for item in model.get('warnings', ()))
    if warnings:
        lines += ['<details><summary>Analyzer warnings</summary>', '']
        lines += table([('Code', False), ('Count', True)],
                       [(code(name), count) for name, count in sorted(warnings.items(),
                                                                      key=lambda item: (-item[1], item[0]))])
        lines += ['', '</details>']
    return '\n'.join(lines).rstrip() + '\n'


# Entry points

def coverage(index: Model, files: dict) -> list:
    """(item, in the model, found in the documents) for every kind of record."""
    pages = {domain_id: files.get(f'contexts/{index.domain_pages[domain_id]}.md', '')
             for domain_id in index.domain_order}
    everything = '\n'.join(files.values())
    rows = [('Bounded contexts', len(index.domains), sum(bool(text) for text in pages.values()))]
    use_cases = found = 0
    for activity_id, activity in index.activities.items():
        domains = index.activity_domains.get(activity_id, ())
        use_cases += 1
        targets = [pages[domain_id] for domain_id in domains] or [files.get('gaps.md', '')]
        found += all(f"**{cell(activity['name'])}**" in text or cell(activity['name']) in text for text in targets)
    rows.append(('Use cases', use_cases, found))
    rows.append(('Entry points', len(index.anchors),
                 sum(index.entry_point(anchor_id) in everything for anchor_id in index.anchors)))
    rows.append(('Business rules', len(index.rules),
                 sum(files.get('rules.md', '').count(f'<a id="rule-{short(rule_id)}">') == 1
                     for rule_id in index.rules)))
    rows.append(('Entities', len(index.concepts),
                 sum(f'<a id="term-{short(concept_id)}">' in files.get('glossary.md', '')
                     for concept_id in index.concepts)))
    shown_ownerships = [item for item in index.ownerships.values() if item.get('domain_id') in index.domains]
    rows.append(('Ownership claims', len(shown_ownerships),
                 sum(f"**{index.name(item['concept_id'])}** ({item['kind']})" in pages[item['domain_id']]
                     for item in shown_ownerships)))
    shown_links = [item for item in index.relationships.values()
                   if item.get('from_domain_id') in index.domains and item.get('to_domain_id') in index.domains
                   and item.get('from_domain_id') != item.get('to_domain_id')]
    rows.append(('Links between contexts', len(shown_links),
                 sum(cell(index.name(item.get('from_activity_id') or '')) in pages[item['from_domain_id']]
                     and cell(index.name(item.get('to_activity_id') or '')) in pages[item['from_domain_id']]
                     for item in shown_links)))
    conflicts = [claim for claim in index.claims.values() if claim.get('kind') in ('conflict', 'contradiction')]
    rows.append(('Contract and code disagreements', len(conflicts),
                 sum(cell(index.readable(claim['text'])) in files.get('gaps.md', '') for claim in conflicts)))
    questions = [question for records in (index.domains.values(), index.activities.values(),
                                          [item for item in index.ownerships.values()
                                           if item.get('domain_id') in index.domains], index.rules.values())
                 for record in records for question in record.get('unresolved_questions', ())]
    questions = [index.readable(question) for question in questions]
    rows.append(('Open questions', len(questions), sum(cell(question) in everything or question in everything
                                                       for question in questions)))
    traces = [trace_id for activity_id in index.activities if index.activity_domains.get(activity_id)
              for trace_id in index.activities[activity_id].get('trace_ids', ()) if trace_id in index.traces]
    accounted = 0
    for trace_id in traces:
        entry = index.entry_point(index.traces[trace_id]['anchor_id'])
        accounted += any(entry in text for text in pages.values())
    rows.append(('Call paths drawn or listed as not drawn', len(traces), accounted))
    return rows


def viewer(files: dict) -> str:
    """One HTML page with every document and its diagrams drawn in the browser."""
    order = ['README.md', *sorted(name for name in files if name.startswith('contexts/')),
             'rules.md', 'glossary.md', 'gaps.md']
    documents = json.dumps({name: files[name] for name in order if name in files}).replace('</', '<\\/')
    return VIEWER.replace('__DOCUMENTS__', documents)


VIEWER = r"""<!doctype html>
<html lang="en" data-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Domain Model Explorer</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#f6f7fb;--surface:#ffffff;--surface-solid:#ffffff;--surface-2:#f8f9fd;--header:rgba(255,255,255,.86);
  --border:#e4e7f0;--border-strong:#d3d9e6;
  --text:#0f172a;--muted:#566079;--faint:#929db2;
  --accent:#4f46e5;--accent-2:#0891b2;--grad:linear-gradient(100deg,#06b6d4,#6366f1 50%,#c026d3);
  --title:linear-gradient(100deg,#0f172a,#4338ca 55%,#a21caf);
  --ok:#047857;--ok-bg:#e7f8f1;--bad:#b91c1c;--bad-bg:#fdecec;--warn-bg:#fff7e6;
  --glow-1:rgba(99,102,241,.10);--glow-2:rgba(6,182,212,.10);
  --page-image:radial-gradient(1100px 420px at 18% -12%,rgba(99,102,241,.09),transparent 70%),radial-gradient(900px 380px at 100% -12%,rgba(6,182,212,.08),transparent 70%);
  --canvas:radial-gradient(#e2e6f1 1px,transparent 1.2px) 0 0/18px 18px,#ffffff;
  --row-hover:#f5f6ff;--code-bg:#eef0f7;--active:linear-gradient(90deg,rgba(99,102,241,.12),rgba(6,182,212,.05));--active-solid:#eef0ff;
  --shadow:0 1px 2px rgba(16,24,40,.04),0 14px 34px -18px rgba(79,70,229,.22);
  color-scheme:light;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#060a13;--surface:rgba(14,21,38,.72);--surface-solid:#0c1322;--surface-2:rgba(22,32,56,.66);--header:rgba(6,10,19,.72);
  --border:rgba(148,163,184,.12);--border-strong:rgba(148,163,184,.22);
  --text:#e6edf7;--muted:#93a3bc;--faint:#64748b;
  --accent:#22d3ee;--accent-2:#a78bfa;--grad:linear-gradient(100deg,#22d3ee,#818cf8 55%,#e879f9);
  --title:linear-gradient(100deg,#f0f9ff,#c7d2fe 55%,#f5d0fe);
  --ok:#34d399;--ok-bg:rgba(52,211,153,.12);--bad:#f87171;--bad-bg:rgba(248,113,113,.12);--warn-bg:rgba(251,191,36,.08);
  --glow-1:rgba(34,211,238,.13);--glow-2:rgba(167,139,250,.14);--grid:rgba(148,163,184,.045);
  --row-hover:rgba(129,140,248,.07);--code-bg:rgba(148,163,184,.12);--active:rgba(129,140,248,.14);
  --shadow:0 1px 0 rgba(255,255,255,.03) inset,0 20px 40px -24px rgba(0,0,0,.8);
  --page-image:radial-gradient(900px 520px at 12% -8%,rgba(34,211,238,.13),transparent 70%),radial-gradient(800px 520px at 100% 0%,rgba(167,139,250,.14),transparent 70%);
  --canvas:radial-gradient(rgba(148,163,184,.10) 1px,transparent 1.2px) 0 0/18px 18px,rgba(10,16,30,.6);--active-solid:rgba(129,140,248,.14);
  color-scheme:dark;
}}
:root[data-theme="dark"]{
  --bg:#060a13;--surface:rgba(14,21,38,.72);--surface-solid:#0c1322;--surface-2:rgba(22,32,56,.66);--header:rgba(6,10,19,.72);
  --border:rgba(148,163,184,.12);--border-strong:rgba(148,163,184,.22);
  --text:#e6edf7;--muted:#93a3bc;--faint:#64748b;
  --accent:#22d3ee;--accent-2:#a78bfa;--grad:linear-gradient(100deg,#22d3ee,#818cf8 55%,#e879f9);
  --title:linear-gradient(100deg,#f0f9ff,#c7d2fe 55%,#f5d0fe);
  --ok:#34d399;--ok-bg:rgba(52,211,153,.12);--bad:#f87171;--bad-bg:rgba(248,113,113,.12);--warn-bg:rgba(251,191,36,.08);
  --glow-1:rgba(34,211,238,.13);--glow-2:rgba(167,139,250,.14);--grid:rgba(148,163,184,.045);
  --row-hover:rgba(129,140,248,.07);--code-bg:rgba(148,163,184,.12);--active:rgba(129,140,248,.14);
  --shadow:0 1px 0 rgba(255,255,255,.03) inset,0 20px 40px -24px rgba(0,0,0,.8);
  --page-image:radial-gradient(900px 520px at 12% -8%,rgba(34,211,238,.13),transparent 70%),radial-gradient(800px 520px at 100% 0%,rgba(167,139,250,.14),transparent 70%);
  --canvas:radial-gradient(rgba(148,163,184,.10) 1px,transparent 1.2px) 0 0/18px 18px,rgba(10,16,30,.6);--active-solid:rgba(129,140,248,.14);
  color-scheme:dark;
}
*{box-sizing:border-box}
html{scroll-padding-top:84px}
body{margin:0;font:15px/1.7 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--text);background-color:var(--bg);background-image:var(--page-image);background-repeat:no-repeat;background-size:100% 560px;-webkit-font-smoothing:antialiased}
#progress{position:fixed;top:0;left:0;height:2px;width:0;background:var(--grad);z-index:60;box-shadow:0 0 12px var(--accent)}
.app{display:grid;grid-template-columns:276px minmax(0,1fr) 244px;grid-template-rows:64px 1fr;min-height:100vh}
header{grid-column:1/-1;position:sticky;top:0;z-index:40;display:flex;align-items:center;gap:14px;padding:0 20px;background:var(--header);
  backdrop-filter:blur(16px) saturate(1.5);-webkit-backdrop-filter:blur(16px) saturate(1.5);border-bottom:1px solid var(--border)}
.brand{display:flex;align-items:center;gap:11px;min-width:0;text-decoration:none;color:var(--text)}
.brand svg{flex:none;filter:drop-shadow(0 0 10px rgba(99,102,241,.45))}
.brand b{display:block;font-weight:700;letter-spacing:-.01em;font-size:15px;line-height:1.2}
.brand small{display:block;color:var(--muted);font-size:11.5px;line-height:1.2;letter-spacing:.02em}
.chips{display:flex;gap:6px;margin-left:6px}
.chip{font:500 11.5px/1 "JetBrains Mono",ui-monospace,monospace;padding:6px 9px;border-radius:999px;border:1px solid var(--border-strong);color:var(--muted);white-space:nowrap}
.chip.status{color:var(--accent);border-color:color-mix(in srgb,var(--accent) 45%,transparent);background:color-mix(in srgb,var(--accent) 8%,transparent)}
.spacer{flex:1}
.search{position:relative;width:min(380px,40vw)}
.search input{width:100%;height:38px;padding:0 64px 0 38px;border-radius:12px;border:1px solid var(--border-strong);background:var(--surface);color:var(--text);font:inherit;font-size:14px;outline:none;transition:border-color .2s,box-shadow .2s}
.search input:focus{border-color:var(--accent);box-shadow:0 0 0 4px color-mix(in srgb,var(--accent) 18%,transparent)}
.search .icon{position:absolute;left:12px;top:11px;color:var(--faint)}
.search kbd{position:absolute;right:10px;top:9px;font:500 11px/1 "JetBrains Mono",monospace;padding:4px 6px;border-radius:6px;border:1px solid var(--border-strong);color:var(--faint)}
.results{position:absolute;top:46px;right:0;width:min(560px,92vw);max-height:70vh;overflow:auto;border-radius:14px;border:1px solid var(--border-strong);background:var(--surface-solid);box-shadow:0 30px 60px -20px rgba(0,0,0,.5);padding:6px;display:none}
.results.open{display:block}
.results button{display:block;width:100%;text-align:left;padding:9px 11px;border:0;border-radius:9px;background:none;color:var(--text);font:inherit;font-size:13.5px;cursor:pointer}
.results button.on,.results button:hover{background:var(--active-solid)}
.results .where{display:block;font-size:11.5px;color:var(--faint);margin-bottom:2px}
.results mark{background:color-mix(in srgb,var(--accent) 28%,transparent);color:inherit;border-radius:3px;padding:0 2px}
.results .none{padding:14px;color:var(--muted);font-size:13.5px}
.iconbtn{display:inline-flex;align-items:center;justify-content:center;width:38px;height:38px;border-radius:11px;border:1px solid var(--border-strong);background:var(--surface);color:var(--muted);cursor:pointer;transition:color .2s,border-color .2s,transform .15s}
.iconbtn:hover{color:var(--accent);border-color:var(--accent)}
.iconbtn:active{transform:scale(.96)}
.menu{display:none}
nav#nav{position:sticky;top:64px;height:calc(100vh - 64px);overflow:auto;padding:22px 14px 30px;border-right:1px solid var(--border)}
.group{margin:0 0 22px}
.group h4{margin:0 10px 8px;font:600 10.5px/1 "JetBrains Mono",monospace;letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}
nav a{position:relative;display:flex;align-items:center;gap:10px;padding:8px 10px;margin:2px 0;border-radius:10px;color:var(--muted);text-decoration:none;font-size:14px;font-weight:500;line-height:1.35;transition:background .2s,color .2s}
nav a svg{flex:none;opacity:.8}
nav a:hover{color:var(--text);background:var(--active)}
nav a.on{color:var(--text);background:var(--active)}
nav a.on::before{content:"";position:absolute;left:-14px;top:8px;bottom:8px;width:3px;border-radius:0 3px 3px 0;background:var(--grad);box-shadow:0 0 12px var(--accent)}
nav a.on svg{color:var(--accent);opacity:1}
main{min-width:0;padding:40px 52px 90px}
.doc{max-width:1060px;margin:0 auto;animation:enter .35s ease both}
@keyframes enter{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.eyebrow{display:inline-flex;align-items:center;gap:8px;font:600 11px/1 "JetBrains Mono",monospace;letter-spacing:.16em;text-transform:uppercase;color:var(--accent);margin-bottom:12px}
.eyebrow::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--accent);box-shadow:0 0 10px var(--accent)}
.doc h1{margin:0 0 10px;font-size:clamp(28px,3.4vw,40px);line-height:1.12;font-weight:800;letter-spacing:-.035em;background:var(--title);-webkit-background-clip:text;background-clip:text;color:transparent}
.doc h2{position:relative;margin:2.6em 0 .7em;padding-left:16px;font-size:22px;line-height:1.3;font-weight:700;letter-spacing:-.02em}
.doc h2::before{content:"";position:absolute;left:0;top:.2em;bottom:.2em;width:4px;border-radius:4px;background:var(--grad)}
.doc h3{margin:2em 0 .6em;font-size:17px;font-weight:650;letter-spacing:-.01em}
.doc h4{margin:1.6em 0 .5em;font-size:15px}
.doc h2 .anchor,.doc h3 .anchor{opacity:0;margin-left:8px;color:var(--faint);text-decoration:none;font-weight:500;transition:opacity .2s}
.doc h2:hover .anchor,.doc h3:hover .anchor{opacity:1}
.doc p,.doc li{color:var(--text)}
.doc em{color:var(--muted)}
.doc a{color:var(--accent);text-decoration:none;border-bottom:1px solid color-mix(in srgb,var(--accent) 35%,transparent)}
.doc a:hover{border-bottom-color:var(--accent)}
.doc code{font:500 .86em "JetBrains Mono",ui-monospace,monospace;background:var(--code-bg);padding:2px 6px;border-radius:6px;word-break:break-word}.doc td code{white-space:nowrap;word-break:normal}
.doc pre.code{background:var(--surface-solid);border:1px solid var(--border);border-radius:12px;padding:14px 16px;overflow:auto}
.doc pre.code code{background:none;padding:0}
.doc ul,.doc ol{padding-left:1.3em}
.doc li{margin:.25em 0}
.doc li::marker{color:var(--accent)}
.doc hr{border:0;height:1px;background:var(--border);margin:2em 0}
.doc blockquote{margin:18px 0;padding:14px 18px 14px 20px;border:1px solid var(--border);border-radius:14px;background:var(--surface);box-shadow:var(--shadow);position:relative;color:var(--muted)}
.doc blockquote::before{content:"";position:absolute;left:0;top:12px;bottom:12px;width:3px;border-radius:3px;background:var(--grad)}
.doc blockquote p{margin:.3em 0;color:var(--muted)}
.doc blockquote strong{color:var(--text)}
.doc details{margin:14px 0;border:1px solid var(--border);border-radius:12px;background:var(--surface);padding:10px 16px}
.doc details summary{cursor:pointer;font-weight:600;color:var(--muted);font-size:14px}.doc details[open] summary{color:var(--text);margin-bottom:8px}.doc li details{display:inline-block;margin:4px 0;padding:4px 10px}
.table-wrap{margin:16px 0 22px;overflow:auto;border:1px solid var(--border);border-radius:14px;background:var(--surface);box-shadow:var(--shadow);backdrop-filter:blur(8px)}
.doc table{width:100%;border-collapse:separate;border-spacing:0;font-size:13.8px;line-height:1.55}
.doc th{position:sticky;top:0;z-index:1;text-align:left;padding:11px 14px;background:var(--surface-solid);color:var(--muted);font:600 11px/1.3 "JetBrains Mono",monospace;letter-spacing:.08em;text-transform:uppercase;border-bottom:1px solid var(--border-strong);white-space:nowrap}
.doc td{padding:11px 14px;border-bottom:1px solid var(--border);vertical-align:top}
.doc tr:last-child td{border-bottom:0}
.doc tbody tr{transition:background .15s}
.doc tbody tr:hover{background:var(--row-hover)}
.pill{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;font:600 11.5px/1.4 "JetBrains Mono",monospace;white-space:nowrap}
.pill.ok{color:var(--ok);background:var(--ok-bg)}
.pill.bad{color:var(--bad);background:var(--bad-bg)}
.pill.muted{color:var(--muted);background:var(--code-bg)}
.pill.ok::before,.pill.bad::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor;box-shadow:0 0 8px currentColor}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin:18px 0 10px}
.stat{position:relative;padding:18px 18px 16px;border-radius:16px;border:1px solid var(--border);background:var(--surface);box-shadow:var(--shadow);overflow:hidden}
.stat::before{content:"";position:absolute;inset:0 0 auto 0;height:2px;background:var(--grad);opacity:.9}
.stat::after{content:"";position:absolute;right:-34px;top:-34px;width:120px;height:120px;border-radius:50%;background:radial-gradient(var(--glow-1),transparent 70%)}
.stat .value{font-size:34px;font-weight:800;letter-spacing:-.04em;line-height:1.1;background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}
.stat .label{margin-top:4px;font:600 10.5px/1.3 "JetBrains Mono",monospace;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
figure.diagram{position:relative;margin:22px 0 26px;border:1px solid var(--border);border-radius:16px;background:var(--surface);box-shadow:var(--shadow);overflow:hidden;backdrop-filter:blur(8px)}
.diagram-bar{display:flex;align-items:center;gap:10px;padding:8px 8px 8px 12px;border-bottom:1px solid var(--border);background:var(--surface-2)}
.diagram-bar .kind{font:600 10px/1 "JetBrains Mono",monospace;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);white-space:nowrap;padding:6px 9px;border-radius:999px;background:var(--active-solid);border:1px solid color-mix(in srgb,var(--accent) 22%,transparent)}
.diagram-bar .title{font-size:13px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.tools{margin-left:auto;display:flex;align-items:center;gap:2px;flex:none}
.tools button{display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:8px;border:0;background:none;color:var(--muted);cursor:pointer;transition:background .15s,color .15s}
.tools button:hover{background:var(--active-solid);color:var(--accent)}
.tools .zoom{font:500 11px "JetBrains Mono",monospace;color:var(--faint);min-width:42px;text-align:center}
.diagram-body{overflow:auto;padding:24px;max-height:80vh;cursor:grab;background:var(--canvas)}
.diagram-body.dragging{cursor:grabbing;user-select:none}
.diagram-body svg{display:block;margin:0 auto;height:auto}
.diagram-body.loading{min-height:170px;background:linear-gradient(100deg,transparent 30%,var(--active-solid) 50%,transparent 70%) 0 0/200% 100%;animation:shimmer 1.4s linear infinite}
@keyframes shimmer{to{background-position:-200% 0}}
.diagram-error{color:var(--bad);font-size:13.5px}
figure.diagram:fullscreen{display:flex;flex-direction:column;border-radius:0;background:var(--bg)}
figure.diagram:fullscreen .diagram-body{flex:1;max-height:none}
aside#toc{position:sticky;top:64px;height:calc(100vh - 64px);overflow:auto;padding:40px 18px 30px 8px}
aside#toc h4{margin:0 0 12px 12px;font:600 10.5px/1 "JetBrains Mono",monospace;letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}
aside#toc a{display:block;padding:5px 12px;border-left:2px solid var(--border);color:var(--muted);text-decoration:none;font-size:12.8px;line-height:1.4;transition:color .15s,border-color .15s}
aside#toc a.sub{padding-left:24px;font-size:12.2px;color:var(--faint)}
aside#toc a:hover{color:var(--text)}
aside#toc a.on{color:var(--accent);border-left-color:var(--accent)}
footer{max-width:1060px;margin:60px auto 0;padding-top:20px;border-top:1px solid var(--border);color:var(--faint);font-size:12.5px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
.files-only{display:none}.offline{max-width:720px;margin:60px auto;padding:20px;border:1px solid var(--border);border-radius:14px;background:var(--surface)}
::-webkit-scrollbar{width:10px;height:10px}::-webkit-scrollbar-thumb{background:var(--border-strong);border-radius:10px;border:2px solid transparent;background-clip:padding-box}
@media (max-width:1300px){.app{grid-template-columns:262px minmax(0,1fr)}aside#toc{display:none}}
@media (max-width:900px){.app{grid-template-columns:minmax(0,1fr)}.menu{display:inline-flex}.chips,.brand small{display:none}
  nav#nav{position:fixed;left:0;top:64px;z-index:35;width:min(300px,86vw);background:var(--surface-solid);transform:translateX(-102%);transition:transform .25s ease;box-shadow:20px 0 40px -20px rgba(0,0,0,.5)}
  body.nav-open nav#nav{transform:none}main{padding:24px 16px 70px}.spacer{display:none}.search{width:auto;flex:1}.search kbd{display:none}.search input{padding-right:12px}header{padding:0 12px;gap:10px}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head>
<body><div id="progress"></div>
<div class="app">
<header>
  <button class="iconbtn menu" id="menu" aria-label="Open navigation"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg></button>
  <a class="brand" href="#README.md">
    <svg width="34" height="34" viewBox="0 0 40 40" aria-hidden="true"><defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#22d3ee"/><stop offset=".55" stop-color="#818cf8"/><stop offset="1" stop-color="#e879f9"/></linearGradient></defs>
      <path d="M20 2.5l15.2 8.75v17.5L20 37.5 4.8 28.75v-17.5z" fill="none" stroke="url(#lg)" stroke-width="2.2"/>
      <circle cx="20" cy="13" r="3.2" fill="url(#lg)"/><circle cx="12.5" cy="25" r="3.2" fill="url(#lg)"/><circle cx="27.5" cy="25" r="3.2" fill="url(#lg)"/>
      <path d="M20 16.2l-6 6M20 16.2l6 6M15.7 25h8.6" stroke="url(#lg)" stroke-width="1.6" stroke-linecap="round"/></svg>
    <span><b id="brand-title">Domain Model</b><small>DDD · UML · Business rules</small></span>
  </a>
  <div class="chips" id="chips"></div>
  <div class="spacer"></div>
  <div class="search">
    <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
    <input id="q" type="search" placeholder="Search use cases, rules, entities…" autocomplete="off" aria-label="Search the documents">
    <kbd>⌘K</kbd>
    <div class="results" id="results" role="listbox"></div>
  </div>
  <button class="iconbtn" id="theme" aria-label="Switch light or dark theme"></button>
</header>
<nav id="nav" aria-label="Documents"></nav>
<main><article class="doc" id="doc"></article><footer id="footer"></footer></main>
<aside id="toc" aria-label="On this page"></aside>
</div>
<script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"></script>
<script>
const DOCUMENTS = __DOCUMENTS__;
(function () {
const $ = selector => document.querySelector(selector);
const nav = $('#nav'), doc = $('#doc'), toc = $('#toc'), root = document.documentElement;
const escape = text => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const titleOf = name => ((DOCUMENTS[name] || '').match(/^# (.+)$/m) || [, name])[1];
const slugify = text => String(text).toLowerCase().replace(/<[^>]+>/g, '').replace(/&[#a-z0-9]+;/g, '')
  .replace(/[`*_[\]()]/g, '').replace(/[^\w\s-]/g, '').trim().replace(/\s+/g, '-').slice(0, 80) || 'section';
const store = {
  get(key) { try { return localStorage.getItem(key); } catch (error) { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch (error) { /* storage unavailable */ } },
};
const ICON = {
  overview: '<path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/>',
  context: '<path d="M12 2.8l8 4.6v9.2l-8 4.6-8-4.6V7.4z"/><path d="M12 12l8-4.6M12 12v9.2M12 12L4 7.4"/>',
  rules: '<path d="M10 6h10M10 12h10M10 18h10M4 6l1.2 1.2L7.5 5M4 12l1.2 1.2L7.5 11M4 18l1.2 1.2L7.5 17"/>',
  glossary: '<path d="M5 4.5A1.5 1.5 0 016.5 3H19v15H6.5A1.5 1.5 0 005 19.5zM5 19.5A1.5 1.5 0 006.5 21H19"/>',
  gaps: '<path d="M12 3.5l9 16H3z"/><path d="M12 10v4.5M12 17.2v.1"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 019.5 4 8 8 0 1020 14.5z"/>',
  minus: '<path d="M5 12h14"/>', plus: '<path d="M12 5v14M5 12h14"/>',
  fit: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  full: '<path d="M9 4H4v5M15 4h5v5M9 20H4v-5M15 20h5v-5"/><path d="M4 4l6 6M20 4l-6 6M4 20l6-6M20 20l-6-6"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
};
const svg = (name, size) => `<svg width="${size || 16}" height="${size || 16}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[name]}</svg>`;
const kindOf = name => name === 'README.md' ? 'overview' : name.startsWith('contexts/') ? 'context'
  : name.startsWith('rules') ? 'rules' : name.startsWith('glossary') ? 'glossary' : 'gaps';
const GROUPS = [['Overview', name => name === 'README.md'], ['Bounded contexts', name => name.startsWith('contexts/')],
  ['Reference', name => name !== 'README.md' && !name.startsWith('contexts/')]];
const EYEBROW = {overview: 'Domain model', context: 'Bounded context', rules: 'Reference', glossary: 'Reference', gaps: 'Reference'};

if (typeof marked === 'undefined' || typeof mermaid === 'undefined') {
  doc.innerHTML = '<div class="offline"><h2>The viewer needs an internet connection</h2><p>It loads its Markdown and diagram libraries from jsDelivr. '
    + 'The same documents are in the Markdown files next to this page.</p></div>';
  return;
}

// Header chips from the overview's model banner.
const readme = DOCUMENTS['README.md'] || '';
const build = (readme.match(/build `([0-9a-f]{8})/) || [])[1];
const status = (readme.match(/Model status: (\w+)/) || [])[1];
$('#chips').innerHTML = (status ? `<span class="chip status">model ${escape(status)}</span>` : '')
  + (build ? `<span class="chip">build ${escape(build)}</span>` : '');

for (const [group, belongs] of GROUPS) {
  const names = Object.keys(DOCUMENTS).filter(belongs);
  if (!names.length) continue;
  nav.insertAdjacentHTML('beforeend', `<div class="group"><h4>${group}</h4>${names.map(name =>
    `<a href="#${escape(name)}" data-name="${escape(name)}">${svg(kindOf(name))}<span>${escape(titleOf(name))}</span></a>`).join('')}</div>`);
}

function theme() { return root.dataset.theme === 'dark' ? 'dark' : 'light'; }
root.dataset.theme = store.get('domain-model-theme') === 'dark' ? 'dark' : 'light';
function paintToggle() { $('#theme').innerHTML = svg(theme() === 'dark' ? 'sun' : 'moon', 18); }
paintToggle();

const FONT = 'Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif';
const PALETTE = {
  dark: {darkMode: true, background: '#0c1322', fontFamily: FONT, fontSize: '14px',
    primaryColor: '#111b31', primaryTextColor: '#e6edf7', primaryBorderColor: '#4f8cff',
    secondaryColor: '#1a1538', secondaryTextColor: '#e6edf7', secondaryBorderColor: '#8b7cf6',
    tertiaryColor: '#0e1729', tertiaryTextColor: '#cbd5e1', tertiaryBorderColor: '#2b3a55',
    mainBkg: '#111b31', nodeBorder: '#4f8cff', nodeTextColor: '#e6edf7', textColor: '#e6edf7', titleColor: '#e6edf7',
    lineColor: '#67c8f0', edgeLabelBackground: '#0c1322', clusterBkg: '#0d1a2e', clusterBorder: '#24507a',
    actorBkg: '#111b31', actorBorder: '#4f8cff', actorTextColor: '#e6edf7', actorLineColor: '#2b3a55',
    signalColor: '#67c8f0', signalTextColor: '#dbe7f5', labelBoxBkgColor: '#1a1538', labelBoxBorderColor: '#8b7cf6',
    labelTextColor: '#ede9fe', loopTextColor: '#c4b5fd', noteBkgColor: '#1d1938', noteBorderColor: '#8b7cf6',
    noteTextColor: '#ede9fe', activationBkgColor: '#1b2742', activationBorderColor: '#4f8cff', sequenceNumberColor: '#06101f',
    attributeBackgroundColorOdd: '#0e1729', attributeBackgroundColorEven: '#111b31', classText: '#e6edf7'},
  light: {darkMode: false, background: '#ffffff', fontFamily: FONT, fontSize: '14px',
    primaryColor: '#ffffff', primaryTextColor: '#1e1b4b', primaryBorderColor: '#6366f1',
    secondaryColor: '#f5f3ff', secondaryTextColor: '#1e1b4b', secondaryBorderColor: '#a78bfa',
    tertiaryColor: '#f8faff', tertiaryTextColor: '#334155', tertiaryBorderColor: '#c7d2fe',
    mainBkg: '#ffffff', nodeBorder: '#6366f1', nodeTextColor: '#1e1b4b', textColor: '#1e293b', titleColor: '#1e1b4b',
    lineColor: '#6d7fb0', edgeLabelBackground: '#ffffff', clusterBkg: '#f7f8ff', clusterBorder: '#c7d2fe',
    actorBkg: '#ffffff', actorBorder: '#6366f1', actorTextColor: '#1e1b4b', actorLineColor: '#c7d2fe',
    signalColor: '#4f46e5', signalTextColor: '#1e293b', labelBoxBkgColor: '#eef2ff', labelBoxBorderColor: '#818cf8',
    labelTextColor: '#3730a3', loopTextColor: '#4338ca', noteBkgColor: '#effcf9', noteBorderColor: '#2dd4bf',
    noteTextColor: '#115e59', activationBkgColor: '#eef2ff', activationBorderColor: '#6366f1', sequenceNumberColor: '#ffffff',
    attributeBackgroundColorOdd: '#ffffff', attributeBackgroundColorEven: '#f7f8ff', classText: '#1e1b4b'},
};
const ACTOR = {dark: 'classDef actor fill:#1a1538,stroke:#a78bfa,color:#ede9fe', light: 'classDef actor fill:#f5f3ff,stroke:#8b5cf6,color:#4c1d95'};
// Rounded, softly lit shapes; the colours come from the palette above.
const SHAPES = {
  light: {shadow: 'rgba(79,70,229,.16)', cluster: '#6366f1', flow: ['#06b6d4', '#6366f1', '#c026d3']},
  dark: {shadow: 'rgba(0,0,0,.55)', cluster: '#7dd3fc', flow: ['#22d3ee', '#818cf8', '#e879f9']},
};
function themeCSS() {
  const look = SHAPES[theme()];
  return `.node rect,.node polygon,.node path,.cluster rect,rect.actor,.note,rect.note,.labelBox,g.classGroup rect,.er.entityBox{rx:10px;ry:10px}
  .node rect,.node polygon,.node circle,.node path,rect.actor,.note,rect.note,g.classGroup rect,.er.entityBox{filter:drop-shadow(0 6px 12px ${look.shadow})}
  .node rect,.node polygon,.node path,rect.actor{stroke-width:1.6px}
  .cluster rect{stroke-dasharray:5 4;stroke-width:1.2px}
  .cluster .nodeLabel,.cluster-label span,.cluster-label p{font-weight:700;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:${look.cluster}}
  .edgeLabel p,.edgeLabel span{font-size:12.5px}
  text.actor>tspan{font-weight:600}
  .messageText{font-weight:500}
  .edgePath .path,.flowchart-link{stroke-width:1.7px}
  .thick,.flowchart-link.thick{stroke-width:3.2px}`;
}
// One left-to-right gradient for every line in a diagram.
function shine(graphic) {
  const box = graphic.viewBox && graphic.viewBox.baseVal;
  if (!box || !box.width) return;
  const [start, middle, end] = SHAPES[theme()].flow, id = graphic.id + '-flow';
  let defs = graphic.querySelector('defs');
  if (!defs) defs = graphic.insertBefore(document.createElementNS('http://www.w3.org/2000/svg', 'defs'), graphic.firstChild);
  defs.insertAdjacentHTML('beforeend', `<linearGradient id="${id}" gradientUnits="userSpaceOnUse" x1="${box.x}" y1="0" x2="${box.x + box.width}" y2="0">`
    + `<stop offset="0" stop-color="${start}"/><stop offset=".5" stop-color="${middle}"/><stop offset="1" stop-color="${end}"/></linearGradient>`);
  graphic.querySelectorAll('.flowchart-link, path.relation, .messageLine0, .messageLine1, .relationshipLine, .er.relationshipLine, .edgePaths path')
    .forEach(line => { line.style.stroke = `url(#${id})`; });
}
function configure() {
  mermaid.initialize({startOnLoad: false, securityLevel: 'strict', maxTextSize: 200000, theme: 'base',
    themeVariables: PALETTE[theme()], fontFamily: FONT, themeCSS: themeCSS(),
    flowchart: {curve: 'basis', padding: 14, nodeSpacing: 46, rankSpacing: 56},
    sequence: {mirrorActors: false, actorFontWeight: 600, noteFontSize: 13, messageFontSize: 13.5, boxMargin: 10, diagramMarginX: 20},
    er: {fontSize: 13}, class: {}});
}
const KINDS = {sequenceDiagram: 'Sequence', classDiagram: 'Class diagram', erDiagram: 'ER diagram', flowchart: 'Flow', graph: 'Flow'};

// Search over headings and text of every document.
const INDEX = [];
for (const [name, text] of Object.entries(DOCUMENTS)) {
  let heading = '', fenced = false;
  for (const line of text.split('\n')) {
    if (line.startsWith('```')) { fenced = !fenced; continue; }
    if (fenced || !line.trim()) continue;
    const match = line.match(/^(#{1,4}) (.+)/);
    if (match) { heading = match[2]; INDEX.push({name, heading: match[1].length > 1 ? heading : '', text: heading, title: true}); continue; }
    const plain = line.replace(/<[^>]+>/g, ' ').replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/\*\*|`|^>\s*/g, '')
      .replace(/\|/g, ' · ').replace(/^[\s·-]+|[\s·]+$/g, '').replace(/\s+/g, ' ');
    if (plain && !/^[-:· ]+$/.test(plain)) INDEX.push({name, heading, text: plain});
  }
}
const input = $('#q'), results = $('#results');
let hits = [], selected = 0;
function highlight(text, query) {
  const at = text.toLowerCase().indexOf(query);
  const start = Math.max(0, at - 50), slice = text.slice(start, at + query.length + 90);
  const local = slice.toLowerCase().indexOf(query);
  return (start ? '…' : '') + escape(slice.slice(0, local)) + '<mark>' + escape(slice.slice(local, local + query.length)) + '</mark>'
    + escape(slice.slice(local + query.length)) + (at + query.length + 90 < text.length ? '…' : '');
}
function search() {
  const query = input.value.trim().toLowerCase();
  if (query.length < 2) { results.classList.remove('open'); return; }
  hits = INDEX.filter(item => item.text.toLowerCase().includes(query))
    .sort((a, b) => (b.title - a.title)).slice(0, 40);
  selected = 0;
  results.innerHTML = hits.length ? hits.map((hit, position) =>
    `<button role="option" data-position="${position}" class="${position ? '' : 'on'}"><span class="where">${escape(titleOf(hit.name))}${hit.heading ? ' › ' + escape(hit.heading) : ''}</span>${highlight(hit.text, query)}</button>`).join('')
    : '<div class="none">Nothing matches that search.</div>';
  results.classList.add('open');
}
function go(hit) {
  results.classList.remove('open'); input.blur();
  location.hash = hit.name + (hit.heading ? '#' + slugify(hit.heading) : '');
}
input.addEventListener('input', search);
input.addEventListener('focus', search);
input.addEventListener('keydown', event => {
  const buttons = results.querySelectorAll('button');
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    if (!buttons.length) return;
    buttons[selected].classList.remove('on');
    selected = (selected + (event.key === 'ArrowDown' ? 1 : buttons.length - 1)) % buttons.length;
    buttons[selected].classList.add('on'); buttons[selected].scrollIntoView({block: 'nearest'});
  } else if (event.key === 'Enter' && hits[selected]) { go(hits[selected]); }
  else if (event.key === 'Escape') { results.classList.remove('open'); input.blur(); }
});
results.addEventListener('mousedown', event => {
  const button = event.target.closest('button');
  if (button) { event.preventDefault(); go(hits[Number(button.dataset.position)]); }
});
document.addEventListener('click', event => { if (!event.target.closest('.search')) results.classList.remove('open'); });
document.addEventListener('keydown', event => {
  if ((event.key === 'k' && (event.metaKey || event.ctrlKey)) || (event.key === '/' && document.activeElement !== input)) {
    event.preventDefault(); input.focus(); input.select();
  }
});

// Diagram cards.
function setScale(figure, scale) {
  const graphic = figure.querySelector('.diagram-body svg');
  if (!graphic || !figure.baseWidth) return;
  figure.scale = Math.min(4, Math.max(0.2, scale));
  graphic.style.maxWidth = 'none';
  graphic.style.width = Math.round(figure.baseWidth * figure.scale) + 'px';
  figure.querySelector('.zoom').textContent = Math.round(figure.scale * 100) + '%';
}
function fit(figure) {
  const body = figure.querySelector('.diagram-body');
  const room = body.clientWidth - 40;
  setScale(figure, Math.min(1, Math.max(room / figure.baseWidth, document.fullscreenElement === figure ? 0.2 : 0.62)));
}
function card(figure, title) {
  const source = figure.source;
  const kind = KINDS[source.trim().split(/\s/)[0]] || 'Diagram';
  figure.innerHTML = `<div class="diagram-bar"><span class="kind">${kind}</span><span class="title">${escape(title)}</span>
    <div class="tools"><button data-act="out" aria-label="Zoom out" title="Zoom out">${svg('minus')}</button><span class="zoom">100%</span>
    <button data-act="in" aria-label="Zoom in" title="Zoom in">${svg('plus')}</button><button data-act="fit" aria-label="Fit to width" title="Fit to width">${svg('fit')}</button>
    <button data-act="full" aria-label="Full screen" title="Full screen">${svg('full')}</button><button data-act="save" aria-label="Download SVG" title="Download SVG">${svg('download')}</button></div></div>
    <div class="diagram-body loading"></div>`;
  if (!document.fullscreenEnabled) figure.querySelector('[data-act="full"]').remove();
  figure.querySelector('.tools').addEventListener('click', event => {
    const action = (event.target.closest('button') || {}).dataset?.act;
    if (action === 'in') setScale(figure, figure.scale * 1.25);
    if (action === 'out') setScale(figure, figure.scale / 1.25);
    if (action === 'fit') fit(figure);
    if (action === 'full') {
      const done = document.fullscreenElement ? document.exitFullscreen() : figure.requestFullscreen?.();
      if (done && done.catch) done.catch(() => {});
    }
    if (action === 'save') {
      const graphic = figure.querySelector('.diagram-body svg');
      if (!graphic) return;
      const blob = new Blob([new XMLSerializer().serializeToString(graphic)], {type: 'image/svg+xml'});
      const link = Object.assign(document.createElement('a'), {href: URL.createObjectURL(blob), download: slugify(title || kind) + '.svg'});
      link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    }
  });
  const body = figure.querySelector('.diagram-body');
  let drag = null;
  body.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    drag = {x: event.clientX, y: event.clientY, left: body.scrollLeft, top: body.scrollTop};
    body.classList.add('dragging'); body.setPointerCapture(event.pointerId);
  });
  body.addEventListener('pointermove', event => {
    if (!drag) return;
    body.scrollLeft = drag.left - (event.clientX - drag.x); body.scrollTop = drag.top - (event.clientY - drag.y);
  });
  const stop = () => { drag = null; body.classList.remove('dragging'); };
  body.addEventListener('pointerup', stop); body.addEventListener('pointercancel', stop);
  body.addEventListener('wheel', event => {
    if (!(event.ctrlKey || event.metaKey)) return;
    event.preventDefault(); setScale(figure, figure.scale * (event.deltaY < 0 ? 1.1 : 1 / 1.1));
  }, {passive: false});
}
// Diagrams inside a closed <details> are drawn at zero width; fit them when it opens.
document.addEventListener('toggle', event => {
  if (event.target.open) event.target.querySelectorAll('figure.diagram').forEach(figure => figure.baseWidth && fit(figure));
}, true);
document.addEventListener('fullscreenchange', () => {
  document.querySelectorAll('figure.diagram').forEach(figure => figure.baseWidth && fit(figure));
});

// Page rendering.
let drawn = 0, showing = 0, current = null, observer = null;
function nearestHeading(element) {
  for (let node = element.previousElementSibling; node; node = node.previousElementSibling) {
    if (/^H[1-4]$/.test(node.tagName)) return node.textContent.replace(/#$/, '').trim();
  }
  return '';
}
function decorate(name) {
  // Tables scroll inside rounded cards; status cells become pills.
  doc.querySelectorAll('table').forEach(table => {
    const wrap = document.createElement('div'); wrap.className = 'table-wrap';
    table.replaceWith(wrap); wrap.appendChild(table);
  });
  doc.querySelectorAll('td').forEach(cell => {
    const text = cell.textContent.trim();
    if (text === 'complete') cell.innerHTML = '<span class="pill ok">complete</span>';
    else if (text === 'MISSING') cell.innerHTML = '<span class="pill bad">missing</span>';
    else if (text === 'yes') cell.innerHTML = '<span class="pill ok">yes</span>';
    else if (text === 'no') cell.innerHTML = '<span class="pill muted">no</span>';
  });
  // The overview's "At a glance" table becomes stat cards.
  doc.querySelectorAll('h2').forEach(heading => {
    const wrap = heading.nextElementSibling;
    if (heading.textContent.replace(/#$/, '').trim() !== 'At a glance' || !wrap || !wrap.classList.contains('table-wrap')) return;
    const labels = [...wrap.querySelectorAll('th')].map(cell => cell.textContent.trim());
    const values = [...wrap.querySelectorAll('tbody tr:first-child td')].map(cell => cell.textContent.trim());
    const stats = document.createElement('div'); stats.className = 'stats';
    stats.innerHTML = labels.map((label, position) =>
      `<div class="stat"><div class="value">${escape(values[position] || '')}</div><div class="label">${escape(label)}</div></div>`).join('');
    wrap.replaceWith(stats);
  });
  const title = doc.querySelector('h1');
  if (title) title.insertAdjacentHTML('beforebegin', `<div class="eyebrow">${EYEBROW[kindOf(name)]}</div>`);
  // Internal links route through the hash; heading anchors already do.
  const base = name.includes('/') ? name.split('/').slice(0, -1).join('/') + '/' : '';
  doc.querySelectorAll('a[href]').forEach(link => {
    const href = link.getAttribute('href');
    if (link.classList.contains('anchor') || /^[a-z]+:/i.test(href)) return;
    if (href.startsWith('#')) { link.href = '#' + name + href; return; }
    const [path, fragment] = href.split('#'), parts = [];
    if (!path.endsWith('.md')) return;
    for (const part of (base + path).split('/')) { if (part === '..') parts.pop(); else if (part && part !== '.') parts.push(part); }
    link.href = '#' + parts.join('/') + (fragment ? '#' + fragment : '');
  });
}
function contents(name) {
  const headings = [...doc.querySelectorAll('h2[id], h3[id]')];
  toc.innerHTML = headings.length ? '<h4>On this page</h4>' + headings.map(heading =>
    `<a href="#${escape(name)}#${heading.id}" data-id="${heading.id}" class="${heading.tagName === 'H3' ? 'sub' : ''}">${escape(heading.textContent.replace(/#$/, '').trim())}</a>`).join('') : '';
  if (observer) observer.disconnect();
  observer = new IntersectionObserver(entries => {
    const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
    if (!visible) return;
    toc.querySelectorAll('a').forEach(link => link.classList.toggle('on', link.dataset.id === visible.target.id));
    const active = toc.querySelector('a.on');
    if (active) active.scrollIntoView({block: 'nearest'});
  }, {rootMargin: '-72px 0px -70% 0px'});
  headings.forEach(heading => observer.observe(heading));
}
function scrollTo(anchor) {
  const target = anchor && document.getElementById(anchor);
  if (target) target.scrollIntoView(); else window.scrollTo(0, 0);
}
async function show(force) {
  let [name, anchor] = decodeURIComponent(location.hash.slice(1) || 'README.md').split('#');
  if (!DOCUMENTS[name]) name = 'README.md';
  document.body.classList.remove('nav-open');
  if (name === current && !force) { scrollTo(anchor); return; }
  const run = ++showing;
  current = name;
  const used = new Set(), sources = [];
  const renderer = new marked.Renderer();
  renderer.heading = (text, level, raw) => {
    if (level === 1) return `<h1>${text}</h1>`;
    let id = slugify(raw);
    while (used.has(id)) id += '-';
    used.add(id);
    return `<h${level} id="${id}">${text}<a class="anchor" href="#${escape(name)}#${id}" aria-label="Link to this section">#</a></h${level}>`;
  };
  renderer.code = (code, language) => language === 'mermaid'
    ? `<figure class="diagram" data-source="${sources.push(code) - 1}"></figure>`
    : `<pre class="code"><code>${escape(code)}</code></pre>`;
  const html = marked.parse(DOCUMENTS[name], {renderer});
  doc.innerHTML = typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(html) : html;
  doc.style.animation = 'none'; void doc.offsetWidth; doc.style.animation = '';
  decorate(name);
  nav.querySelectorAll('a').forEach(link => link.classList.toggle('on', link.dataset.name === name));
  document.title = `${titleOf(name)} · Domain Model`;
  $('#footer').innerHTML = `<span>Generated by <code>speed discover domains --export ddd</code></span><span>${Object.keys(DOCUMENTS).length} documents</span>`;
  contents(name);
  const figures = [...doc.querySelectorAll('figure.diagram')];
  figures.forEach(figure => { figure.source = sources[Number(figure.dataset.source)]; card(figure, nearestHeading(figure)); });
  scrollTo(anchor);
  if (document.fonts && document.fonts.ready) await document.fonts.ready;
  configure();
  for (const figure of figures) {
    if (run !== showing) return;
    const body = figure.querySelector('.diagram-body');
    const source = figure.source.replace(/classDef actor [^\n]*/, ACTOR[theme()]);
    try {
      body.innerHTML = (await mermaid.render('diagram' + (++drawn), source)).svg;
      const graphic = body.querySelector('svg');
      shine(graphic);
      figure.baseWidth = graphic.viewBox && graphic.viewBox.baseVal && graphic.viewBox.baseVal.width || graphic.getBoundingClientRect().width;
      fit(figure);
    } catch (error) {
      body.innerHTML = '<div class="diagram-error">This diagram could not be drawn. Its source:</div><pre class="code"><code>' + escape(figure.source) + '</code></pre>';
    }
    body.classList.remove('loading');
  }
  if (run === showing) scrollTo(anchor);
}
$('#theme').addEventListener('click', () => {
  root.dataset.theme = theme() === 'dark' ? 'light' : 'dark';
  store.set('domain-model-theme', root.dataset.theme);
  paintToggle(); show(true);
});
$('#menu').addEventListener('click', () => document.body.classList.toggle('nav-open'));
window.addEventListener('scroll', () => {
  const height = document.documentElement.scrollHeight - innerHeight;
  $('#progress').style.width = (height > 0 ? scrollY / height * 100 : 0) + '%';
}, {passive: true});
window.addEventListener('hashchange', () => show(false));
show(true);
})();
</script></body></html>
"""


def export_ddd(model: dict) -> dict:
    """Return the DDD documents for a published model as {relative path: text}."""
    index = Model(model)
    entities = Entities(index)
    sequences = Sequences(index, entities)
    # Every diagram is built once up front, so each page's implementations table sees the whole model.
    for activity in index.activities.values():
        sequences.diagrams(activity)
    files = {'rules.md': rules_page(index), 'glossary.md': glossary_page(index, entities),
             'gaps.md': gaps_page(index)}
    for domain_id in index.domain_order:
        files[f'contexts/{index.domain_pages[domain_id]}.md'] = context_page(
            index, entities, sequences, domain_id)
    files = {name: index.readable(text) for name, text in files.items()}
    checked = coverage(index, files)
    files['README.md'] = index.readable(readme(index, entities, checked))
    files['gaps.md'] = files['gaps.md'].rstrip('\n') + '\n' + '\n'.join(completeness(checked)) + '\n'
    files['index.html'] = viewer(files)
    return files


def _write_text(base: Path, relative: str, text: str) -> None:
    """Write one file inside `base`, refusing to follow a symlink out of it."""
    path = base / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.parent.resolve().is_relative_to(base):
        raise DomainError('UNSAFE_PATH', 'Export path leaves the export directory', str(path))
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix='.export-')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            stream.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write_export(root: Path, model: dict, out=None) -> dict:
    """Write the documents under `out` (default .speed/context/business-domain-ddd).

    The export owns the files its manifest lists. It refuses to overwrite any
    other existing file, and removes owned files it no longer renders.
    """
    root = Path(root)
    target = Path(out) if out else root / EXPORT_DIRECTORY
    target = target if target.is_absolute() else Path.cwd() / target
    if target.is_symlink():
        raise DomainError('UNSAFE_PATH', 'Export directory is a symlink', str(target))
    files = export_ddd(model)
    try:
        target.mkdir(parents=True, exist_ok=True)
        base = target.resolve()
        manifest_path = base / MANIFEST
        owned, ours = set(), True
        if manifest_path.exists():
            try:
                previous = json.loads(manifest_path.read_text())
                ours = isinstance(previous, dict) and previous.get('format') == 'ddd'
                owned = set(previous.get('files', {})) if ours else set()
            except (ValueError, OSError):
                ours = False
        conflicts = sorted(relative for relative in [*files, MANIFEST]
                           if (base / relative).exists() and relative not in owned
                           and not (relative == MANIFEST and ours))
        if conflicts:
            raise DomainError(
                'EXPORT_CONFLICT',
                'The export directory has files the export did not write: ' + ', '.join(conflicts[:5])
                + ('…' if len(conflicts) > 5 else '') + '. Choose an empty directory with --out.',
                str(base))
        # Claim every file before writing any, so an interrupted run never leaves
        # files the next run would refuse to overwrite.
        claimed = {relative: None for relative in sorted(owned | set(files))}
        _write_text(base, MANIFEST, json.dumps({'build_id': model.get('build_id'), 'format': 'ddd',
                                                 'files': claimed}, indent=1, sort_keys=True) + '\n')
        digests = {}
        for relative, text in sorted(files.items()):
            _write_text(base, relative, text)
            digests[relative] = hashlib.sha256(text.encode()).hexdigest()
        for relative in sorted(owned - set(files)):
            stale = base / relative
            if stale.is_file() and not stale.is_symlink() and stale.resolve().is_relative_to(base):
                stale.unlink()
        manifest = {'build_id': model.get('build_id'), 'format': 'ddd', 'files': digests}
        _write_text(base, MANIFEST, json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    except OSError as exc:
        raise DomainError('EXPORT_WRITE_FAILED', f'Cannot write the export: {exc}', str(target)) from exc
    try:
        shown = str(base.relative_to(root.resolve()))
    except ValueError:
        shown = str(base)
    index = Model(model)
    return {'directory': shown, 'files': sorted(files), 'build_id': model.get('build_id'),
            'viewer': (base / 'index.html').as_uri(),
            'counts': {'contexts': len(index.domain_order), 'use_cases': len(index.activities),
                       'entities': len(index.concepts), 'rules': len(index.rules),
                       'links': len(index.relationships)}}
