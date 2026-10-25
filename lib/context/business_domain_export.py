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

SUPPORT = {'supported': 'supported', 'partial': 'partially supported',
           'insufficient': 'insufficient evidence'}
ENFORCEMENT = {
    'verified_on_trace': 'verified on a traced path',
    'declared_only': 'declared in code, not proven on a traced path',
    'conditional': 'depends on preconditions',
    'unresolved': 'enforcement unresolved',
}
EVIDENCE = {'supported': 'well evidenced', 'partial': 'partly evidenced',
            'insufficient': 'weakly evidenced'}
IMPLEMENTATION = {
    'implemented': 'implemented',
    'documented_only': 'documented only',
    'implementation_unresolved': 'implementation not fully traced',
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
ACCESSOR = re.compile(r'\.(?:get|set|is)[A-Z]\w*\(')
NO_ROLE = 'no role declared'
CONFLICTING_ROLES = 'no single declared role allows every step'
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
MAX_PARTICIPANTS = 10
MAX_DEPTH = 6
MAX_USE_CASES = 15
SEQUENCE_KINDS = ('calls', 'reads_data', 'writes_data', 'selects_implementation',
                  'routes_to', 'invokes_endpoint')


# Text helpers

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
    return sentence if len(sentence) <= limit else sentence[:limit - 1].rstrip() + '…'


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
            return f'{name} on {path}' if path else name
        return operation.get('name') or anchor_id

    def citations(self, evidence_ids, limit: int = 2, every_kind: bool = False, first_kind=None) -> list:
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
            found.append((rank, path, start or 0, f'{path}:{lines}' if start else path))
        seen, result, kinds = set(), [], set()
        ordered = sorted(found)
        if every_kind:
            ordered = ([item for item in ordered if item[0] not in kinds and not kinds.add(item[0])]
                       + ordered)
        for _, path, start, text in ordered:
            if (path, start) not in seen:
                seen.add((path, start))
                result.append(text)
        return result[:limit]

    def cite(self, evidence_ids, limit: int = 2, every_kind: bool = False, first_kind=None) -> str:
        found = self.citations(evidence_ids, limit, every_kind, first_kind)
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

    def owners(self, concept_id: str) -> list:
        return sorted({ownership['domain_id'] for ownership in self.ownerships.values()
                       if ownership['concept_id'] == concept_id and ownership.get('domain_id') in self.domains},
                      key=self.domain_order.index)


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
        return {'name': name, 'type': type_name, 'annotations': annotations,
                'association': association, 'target': target,
                'join_table': join_table.group(1) if join_table else None,
                'mapped_by': re.search(r'mappedBy\s*=\s*"(\w+)"', excerpt) is not None}

    def _table(self, symbol_id: str):
        symbol = self.index.symbols[symbol_id]
        excerpt = ' '.join(self.index.evidence[evidence_id].get('excerpt', '')
                           for evidence_id in symbol.get('evidence_ids', ())
                           if evidence_id in self.index.evidence)
        match = re.search(r'@Table\s*\(\s*name\s*=\s*"(\w+)"', excerpt)
        return match.group(1) if match else None

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

    def diagram(self, concept_ids) -> str:
        """Return a Mermaid classDiagram for the given concepts, or '' if there is nothing to draw."""
        index = self.index
        roots = {symbol_id for concept_id in concept_ids
                 for symbol_id in self.by_concept.get(concept_id, ())}
        shown, pending = set(), sorted(roots)
        while pending:
            symbol_id = pending.pop()
            if symbol_id in shown or not self.classes.get(symbol_id):
                continue
            shown.add(symbol_id)
            if self.classes[symbol_id]['parent']:
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
        associations, drawn = [], set()
        join_tables = {field['join_table'] for entity in self.classes.values() if entity
                       for field in entity['fields'] if field['join_table']}
        for symbol_id in sorted(shown, key=lambda key: names[key]):
            entity = self.classes[symbol_id]
            members = []
            for field in entity['fields']:
                target = by_name.get(field['target'])
                if field['association'] and target:
                    if target in shown and frozenset((symbol_id, target)) not in drawn:
                        drawn.add(frozenset((symbol_id, target)))
                        left, right = JPA_ASSOCIATIONS[field['association']]
                        via = f" via {field['join_table']}" if field['join_table'] else ''
                        associations.append(f'  {names[symbol_id]} "{left}" --> "{right}" '
                                            f'{names[target]} : {field["name"]}{via}')
                    continue
                type_name = (field['type'] or '').replace('<', '~').replace('>', '~')
                members.append(f'    +{type_name} {field["name"]}'.replace('+ ', '+'))
            role = '<<entity>>' if symbol_id in roots else '<<base>>'
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

    def constraints(self, concept_ids) -> list:
        """Rows of (class, field, annotations) for validation annotations on fields."""
        rows = []
        for concept_id in sorted(concept_ids):
            for symbol_id in self.by_concept.get(concept_id, ()):
                entity = self.classes.get(symbol_id)
                for field in (entity or {}).get('fields', ()):
                    checks = [annotation for annotation in field['annotations']
                              if annotation not in JPA_ASSOCIATIONS
                              and annotation not in ('Column', 'JoinColumn', 'JoinTable', 'Id',
                                                     'GeneratedValue', 'Temporal', 'Transient',
                                                     'JsonIgnore', 'Override')]
                    if checks:
                        rows.append((entity['name'], field['name'], checks))
        return sorted(set((name, field, tuple(checks)) for name, field, checks in rows))


# Sequence diagrams

class Sequences:
    """Static call paths per entry point, rebuilt in source order."""

    def __init__(self, index: Model):
        self.index = index
        # The extractor marks every profile-bound implementation as matching, so
        # the declared profiles come from spring.profiles.active.
        profiles = set()
        for edge in index.edges.values():
            for match in ACTIVE_PROFILES.finditer(edge.get('condition') or ''):
                profiles.update(part.strip() for part in match.group(1).split(','))
        self.active_profiles = profiles

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
            result = self.diagram(trace)
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

    def _root(self, anchor: dict):
        for representation in anchor.get('representations') or ():
            if isinstance(representation, dict) and representation.get('role') == 'implementation':
                return representation.get('symbol_id')
        return anchor.get('symbol_id')

    def diagram(self, trace: dict):
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
                        generated = target_id not in index.symbols
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
                if not target and edge['kind'] == 'invokes_endpoint':
                    target = ('endpoint', 'unresolved endpoint')
                    message(lifeline, join(target), '-->>', 'request (target not resolved)')
                    continue
                if not target:
                    continue
                arrow = '->>' if edge.get('resolution') == 'resolved' else '-->>'
                guard = self._guard(edge.get('condition'))
                if edge['kind'] in ('reads_data', 'writes_data'):
                    verb = 'read' if edge['kind'] == 'reads_data' else 'write'
                    message(lifeline, join(target), arrow, f'{verb} {target[1]}')
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
                elif message(lifeline, join(target), arrow, self._method(target_ref)):
                    walk(target_id, target[1], depth + 1, branch + ((guard,) if guard else ()))
                if guard:
                    steps.append(('end',))

        walk(root, first[1], 0)
        # The interface and its implementation often record the same data access.
        tidy = []
        for step in steps:
            if (step[0] == 'message' and tidy and tidy[-1][0] == 'message'
                    and tidy[-1][1:3] == step[1:3] and tidy[-1][4] == step[4]):
                if step[3] == '->>':
                    tidy[-1] = step
                continue
            if step[0] == 'end' and tidy and tidy[-1][0] == 'opt':
                tidy.pop()
                continue
            tidy.append(step)
        messages = [step for step in tidy if step[0] == 'message']
        if not messages:
            return 'its call path has no step outside the entry point'
        actor = ACTORS.get(anchor.get('kind'), 'Caller')
        lines = ['sequenceDiagram', '  autonumber', f'  actor Client as {label(actor)}']
        ids = {}
        for position, (kind, name) in enumerate(participants[:MAX_PARTICIPANTS], 1):
            ids[name] = f'P{position}'
            shown = f'{name} table' if kind == 'table' else name
            lines.append(f'  participant P{position} as {label(shown)}')
        lines.append(f'  Client->>{ids[first[1]]}: {label(index.entry_point(anchor["id"]))}')
        depth = 0
        for step in tidy:
            if step[0] == 'opt':
                lines.append('  ' * (depth + 1) + f'opt {label(step[1])}')
                depth += 1
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
        drawn_names = {name for _, name in participants}
        for lifeline in [name for _, name in participants if name in facts]:
            fact = facts[lifeline]
            parts = []
            if fact['runs']:
                parts.append('runs ' + ', '.join(sorted(fact['runs'])))
            if fact['inactive']:
                parts.append('not on the declared profile: ' + ', '.join(sorted(fact['inactive'])))
            if fact['ambiguous']:
                parts.append('several match the declared profile, not drawn: ' + ', '.join(sorted(fact['ambiguous'])))
            if fact['by_profile']:
                parts.append('chosen at runtime by profile, not drawn: ' + ', '.join(sorted(fact['by_profile'])))
            unbound = fact['unbound'] - drawn_names
            if unbound:
                parts.append('other implementations, not drawn: ' + ', '.join(sorted(unbound)))
            if parts and lifeline in ids:
                lines.append(f'  Note over {ids[lifeline]}: {label("; ".join(parts))}')
        contract = 'API contract (no implementation)'
        if contract in ids:
            lines.append(f'  Note over {ids[contract]}: '
                         + label('declared in the API contract; no server implementation is evidenced'))
        if budget['omitted']:
            lines.append(f"  Note over {ids[first[1]]}: "
                         + label(f"at least {plural(budget['omitted'], 'more step')} not drawn (trace {short(trace['id'])})"))
        profiled = any(fact['runs'] or fact['inactive'] for fact in facts.values())
        state = ' · '.join(part for part in (trace.get('completion'), trace.get('resolution')) if part)
        caption = ('Static call path in source order, not observed runtime'
                   + (f'; trace {state}' if state else '') + '.'
                   + (f" Profile-bound implementations follow the declared profile "
                      f"({', '.join(sorted(self.active_profiles))}, from spring.profiles.active); "
                      f"a runtime override can change it." if profiled and self.active_profiles else '')
                   + (' Dotted arrows are calls or data access the extractor could not fully resolve.'
                      if any(step[3] == '-->>' for step in messages) else ''))
        return (index.entry_point(anchor['id']), caption, '\n'.join(lines))


# Pages

def badge(value: str, names: dict) -> str:
    return names.get(value, value or '-')


def rule_status(rule: dict) -> str:
    """Enforcement in words, saying where a declared rule is declared."""
    status = rule.get('enforcement_status')
    if status != 'declared_only':
        return badge(status, ENFORCEMENT)
    basis = set(rule.get('basis') or ())
    if 'source_observed' in basis:
        return ENFORCEMENT['declared_only']
    if 'contract_declared' in basis and 'test_expected' in basis:
        return 'declared in the API contract and expected by tests'
    if 'contract_declared' in basis:
        return 'declared in the API contract only'
    if 'test_expected' in basis:
        return 'expected by tests only'
    if 'documented' in basis:
        return 'documented only'
    return ENFORCEMENT['declared_only']


def table(header, rows) -> list:
    """A Markdown table whose delimiter row always matches its header."""
    lines = ['| ' + ' | '.join(name for name, _ in header) + ' |',
             '|' + '|'.join('---:' if right else '---' for _, right in header) + '|']
    lines += ['| ' + ' | '.join(str(value) for value in row) + ' |' for row in rows]
    return lines


def model_banner(index: Model, link_gaps: bool = True) -> list:
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
        f"> Entry points: {coverage.get('anchors_processed', '-')} modelled, "
        f"{coverage.get('anchors_excluded', 0)} excluded, {coverage.get('anchors_pending', 0)} pending "
        f"of {coverage.get('anchors_total', '-')}. "
        f"Call paths fully resolved: {len(traces) - open_traces} of {len(traces)}. "
        f"Data accesses fully resolved: {len(uses) - open_uses} of {len(uses)}."
        + (f" {plural(hidden, 'context')} with insufficient evidence or rejected in review not shown."
           if hidden else ''),
    ]
    if model.get('status') != 'complete':
        reasons = []
        if pending:
            reasons.append(plural(len(pending), 'entry point') + ' not modelled')
        if open_traces:
            reasons.append('call paths that end at framework or generated code')
        if any(item.get('support') != 'supported' for item in index.activities.values()):
            reasons.append('use cases only partly backed by traced evidence')
        if reasons:
            lines.append('> Partial means: ' + '; '.join(reasons) + '.'
                         + (' See [Gaps](gaps.md).' if link_gaps else ''))
    return lines


def readme(index: Model, entities: Entities) -> str:
    domains = [index.domains[domain_id] for domain_id in index.domain_order]
    lines = ['# Domain model', '',
             '_Generated by `speed discover domains --export ddd`. Regenerate it instead of editing it._',
             '', *model_banner(index), '', '## At a glance', '',
             *table([('Bounded contexts', True), ('Use cases', True), ('Entities', True),
                     ('Business rules', True), ('Context links', True)],
                    [(len(domains), len(index.activities), len(index.concepts), len(index.rules),
                      len(index.relationships))]),
             '', '## Context map', '',
             'Thin arrows point from a context to a context whose data it reads; dashed ones include '
             'links with no traced call path. Thick arrows mark a context that writes data another '
             'context owns, and two-way dotted arrows join contexts that both claim ownership of an entity.', '',
             '```mermaid', context_map(index), '```', '', '## Bounded contexts', '']
    lines += table([('Context', False), ('What it does', False), ('Use cases', True), ('Entities', True),
                    ('Rules', True), ('Support', False)],
                   [(f"[{cell(domain['name'])}](contexts/{index.domain_pages[domain['id']]}.md)",
                     cell(first_sentence(domain['summary'])), len(domain['activity_memberships']),
                     len(domain.get('concepts', ())), len(domain.get('rules', ())),
                     badge(domain.get('support'), SUPPORT)) for domain in domains])
    diagram = entities.diagram(sorted(index.concepts))
    if diagram:
        lines += ['', '## Entity model', '',
                  'Entity classes behind the concepts, with their fields, supertypes and JPA '
                  'associations, read from the source declarations the model cites. Each title '
                  'names the class and its table.', '', '```mermaid', diagram, '```']
    lines += ['', '## Documents', '',
              '- [Business rules catalog](rules.md): every rule with its condition, outcome and where it is enforced',
              '- [Glossary](glossary.md): the ubiquitous language, with the code type and table behind each term',
              '- [Gaps](gaps.md): what the model could not prove, entry points it did not model, and contract conflicts',
              '', '## How to read the badges', '']
    lines += table([('Badge', False), ('Meaning', False)], [
        ('supported / partially supported',
         'How fully traced code backs a context or use case. Partial means some of its call paths '
         'end at framework or generated code.'),
        ('well / partly / weakly evidenced',
         "How fully the cited evidence backs a rule's description. It says nothing about whether the rule runs."),
        ('declared in code, not proven on a traced path',
         'The check is in the source, but no traced call path proves it runs.'),
        ('declared in the API contract only / expected by tests only',
         'The rule comes from the API contract or from tests, not from implementation code.'),
        ('depends on preconditions',
         'The rule applies only under a condition, such as an enabled profile or setting.'),
        ('implementation not fully traced',
         'The model marks the use case unresolved: its path to storage is not proven end to end.'),
        ('role (declared)',
         'The code declares the role, for example with @PreAuthorize, but no traced path proves it is enforced.'),
    ])
    return '\n'.join(lines) + '\n'


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
        text = label(f'{kind.replace("_", " ")} ({len(items)})')
        arrow = f'-. "{text}" .->' if dashed else f'-- "{text}" -->'
        lines.append(f'  {node("D", source)} {arrow} {node("D", target)}')
    for (source, target), concepts in sorted(foreign_writes(index).items(),
                                             key=lambda item: (order(item[0][0]), order(item[0][1]))):
        text = '; '.join(f"{'/'.join(sorted(verbs))} {name}" for name, verbs in sorted(concepts.items()))
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
            shown = f'{role} (declared)' if declared else role
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
        lines.append('  classDef actor fill:#eef,stroke:#446')
        lines.append('  classDef unresolved stroke-dasharray: 5 5')
        diagrams.append('\n'.join(lines))
    return diagrams


def rule_line(rule: dict) -> str:
    return (f"[{rule['name']}](../rules.md#rule-{short(rule['id'])}) · "
            f"{rule.get('category', '-').replace('_', ' ')} · {rule_status(rule)}")


def context_page(index: Model, entities: Entities, sequences: Sequences, domain_id: str) -> str:
    domain = index.domains[domain_id]
    activities = index.sorted_records(index.activities,
                                      [item['activity_id'] for item in domain['activity_memberships']])
    lines = [f"# {domain['name']}", '',
             f"_Bounded context · {badge(domain.get('support'), SUPPORT)} · review state "
             f"{domain.get('review_state', '-')}_", '',
             '[Back to the domain model](../README.md)', '',
             domain.get('summary') or '', '',
             '## Why this boundary', '', domain.get('boundary_rationale') or '-', '']
    if domain.get('alternatives'):
        lines += ['### Boundaries considered and not chosen', '']
        for item in domain['alternatives']:
            subjects = ', '.join(index.name(subject) for subject in item.get('subject_ids', ()))
            lines.append(f"- **{subjects or 'Alternative'}**: {item.get('explanation', '')}")
        lines.append('')
    if domain.get('exclusions'):
        lines += ['### Deliberately left out', '']
        for item in domain['exclusions']:
            subjects = ', '.join(index.name(subject) for subject in item.get('subject_ids', ()))
            lines.append(f"- **{subjects}**: {item.get('explanation', '')}")
        lines.append('')
    if domain.get('unresolved_questions'):
        lines += ['> **Open questions**', '>']
        lines += [f'> - {question}' for question in domain['unresolved_questions']]
        lines.append('')

    lines += ['## Use cases', '']
    for diagram in use_case_diagrams(index, domain):
        lines += ['```mermaid', diagram, '```', '']
    lines += ['Dashed use cases are ones the model marks unresolved. Solid ones are marked implemented, '
              'but their call path may still end at framework or generated code; each sequence caption '
              'says how far it was traced. Dashed role arrows mean the role is declared, not proven '
              'enforced.', '']
    rows = []
    for activity in activities:
        roles, enforced = index.access(activity)
        qualifier = '' if enforced else (' (declared, conditional)' if index.role_conditions(activity)
                                         else ' (declared)')
        role_text = ', '.join(roles) + qualifier if roles else NO_ROLE
        entry = '<br>'.join(cell(index.entry_point(anchor_id)) for anchor_id in sorted(
            activity['anchor_ids'], key=index.entry_point))
        rows.append((f"**{cell(activity['name'])}**<br>{cell(activity.get('description'))}", entry,
                     f"{cell(role_text)} via {index.channel(activity)}",
                     f"{badge(activity.get('implementation_status'), IMPLEMENTATION)}, "
                     f"{badge(activity.get('support'), SUPPORT)}", index.cite(activity.get('evidence_ids'))))
    lines += table([('Use case', False), ('Entry points', False), ('Roles', False), ('Status', False),
                    ('Evidence', False)], rows)
    callers = sorted({activity.get('actor') for activity in activities if activity.get('actor')})
    if callers:
        lines += ['', '<details><summary>Callers as the model describes them</summary>', '']
        lines += [f'- {caller}' for caller in callers]
        lines += ['', '</details>']

    concept_ids = sorted(set(domain.get('concepts', ())))
    usage = index.concept_usage()
    lines += ['', '## Entities', '']
    if concept_ids:
        owned = defaultdict(list)
        for ownership_id in domain.get('ownership_ids', ()):
            ownership = index.ownerships.get(ownership_id)
            if ownership:
                owned[ownership['concept_id']].append(ownership)
        rows = []
        for concept in index.sorted_records(index.concepts, concept_ids):
            types = ', '.join(code(name.split('.')[-1]) for name in concept.get('qualified_type_names', ())) \
                or 'no code type (table)'
            ownership = '; '.join(f"{item['kind']} ({badge(item.get('support'), SUPPORT)})"
                                  for item in owned.get(concept['id'], ())) or 'used, not owned'
            others = sorted((set(usage.get(concept['id'], {})) | set(index.concept_domains[concept['id']]))
                            - {domain_id}, key=index.domain_order.index)
            used_by = ', '.join(
                index.domains[other]['name']
                + (f" ({', '.join(sorted(usage[concept['id']][other]))})" if usage.get(concept['id'], {}).get(other) else '')
                for other in others) or '-'
            rows.append((f"[{cell(concept['name'])}](../glossary.md#term-{short(concept['id'])})", types,
                         cell(', '.join(entities.concept_tables(concept['id']))), cell(ownership),
                         cell(used_by)))
        lines += table([('Entity', False), ('Code type', False), ('Table', False),
                        ('Ownership here', False), ('Also used by', False)], rows)
        diagram = entities.diagram(concept_ids)
        if diagram:
            lines += ['', '```mermaid', diagram, '```']
        constraints = entities.constraints(concept_ids)
        if constraints:
            lines += ['', 'Field constraints declared in the entity classes:', '']
            lines += table([('Class', False), ('Field', False), ('Constraints', False)],
                           [(name, field, ', '.join(code('@' + item) for item in checks))
                            for name, field, checks in constraints])
        reasons = [item for ownership_id in domain.get('ownership_ids', ())
                   if (item := index.ownerships.get(ownership_id))]
        if reasons:
            lines += ['', '<details><summary>Why this context owns its data</summary>', '']
            for item in sorted(reasons, key=lambda item: index.name(item['concept_id'])):
                lines.append(f"- **{index.name(item['concept_id'])}** ({item['kind']}): {item.get('rationale', '')}")
                lines += [f'  - Open question: {question}' for question in item.get('unresolved_questions', ())]
            lines += ['', '</details>']
    else:
        lines.append('No entities are attributed to this context.')

    data = data_access(index, activities)
    if data:
        used = [access for access in ACCESS_ORDER if any(row[access] for row in data.values())]
        lines += ['', '## Data it reads and writes', '',
                  'Counts of data accesses by its use cases. Resolved accesses are traced to their statement. '
                  'For unresolved ones the model could not establish the statement, its completion or which '
                  'implementation performs it; ambiguous ones may not happen at all.', '']
        lines += table([('Table', False), *[(access.capitalize(), True) for access in used],
                        ('Resolved', True), ('Unresolved', True), ('Ambiguous', True)],
                       [(cell(name), *[(f"{data[name][access]} ({data[name][access + ':ambiguous']} ambiguous)"
                                         if data[name].get(access + ':ambiguous') else data[name][access] or '-')
                                        for access in used],
                         data[name]['resolved'] or '-', data[name]['unresolved'] or '-',
                         data[name]['ambiguous'] or '-') for name in sorted(data)])

    links = context_links(index, domain_id)
    if links:
        lines += ['', '## Links to other contexts', '', *links]

    lines += ['', '## Call sequences', '',
              'Rebuilt from the traced call graph in source order. They show the static path a request '
              'can take, not a recorded run. Conditional calls are drawn as `opt` blocks; other calls '
              'are listed in source order, so branches without a recorded condition are not told apart.', '']
    drawn, not_drawn = False, []
    for activity in activities:
        diagrams, skipped = sequences.diagrams(activity)
        for title, caption, diagram in diagrams:
            drawn = True
            lines += [f"### {activity['name']}: {title}", '', f'_{caption}_', '',
                      '```mermaid', diagram, '```', '']
        not_drawn += [(activity['name'], entry, reason) for entry, reason in skipped]
    if not drawn:
        lines.append('No traced call path in this context has more than one step.')
    if not_drawn:
        lines += ['', 'Call paths not drawn:', '']
        lines += [f'- {name}, {entry}: {reason}' for name, entry, reason in not_drawn]

    rules = index.sorted_records(index.rules, domain.get('rules', ()))
    lines += ['', '## Business rules', '']
    if rules:
        by_category = defaultdict(list)
        for rule in rules:
            by_category[rule.get('category') or 'unclassified'].append(rule)
        for category in sorted(by_category, key=category_key):
            lines += [f"**{category.replace('_', ' ').capitalize()}**", '']
            lines += [f'- {rule_line(rule)}' for rule in by_category[category]]
            lines.append('')
    else:
        lines.append('No rules are attributed to this context.')
    return '\n'.join(lines).rstrip() + '\n'


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
    if not rows:
        return []
    return table([('Use case here', False), ('Link', False), ('Use case there', False), ('Data', False),
                  ('Context', False), ('Traced', False)], sorted(set(rows)))


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
    lines = ['# Business rules catalog', '', '_Generated by `speed discover domains --export ddd`._', '',
             '[Back to the domain model](README.md)', '']
    if not rules:
        return '\n'.join(lines + ['No rules were extracted.']) + '\n'
    statuses = sorted({rule_status(rule) for rule in rules})
    counts = Counter((rule.get('category') or 'unclassified', rule_status(rule)) for rule in rules)
    categories = sorted({rule.get('category') or 'unclassified' for rule in rules}, key=category_key)
    lines += [f'{plural(len(rules), "rule")} extracted from the source. Each rule lists the condition '
              'it checks, the outcome, where the code enforces it and the evidence behind it.', '']
    lines += table([('Category', False), *[(status, True) for status in statuses], ('Total', True)],
                   [(category.replace('_', ' '), *[counts[(category, status)] or '-' for status in statuses],
                     sum(counts[(category, status)] for status in statuses)) for category in categories])
    if not any(rule.get('enforcement_status') == 'verified_on_trace' for rule in rules):
        lines += ['', '> No rule is verified on a traced path. "Declared" means the check is written '
                  'down, in code, the API contract or tests, but no traced call path proves it runs.']
    lines.append('')
    current = None
    for rule in rules:
        category = rule.get('category') or 'unclassified'
        if category != current:
            current = category
            lines += [f"## {current.replace('_', ' ').capitalize()}", '']
        domains = ', '.join(f"[{index.domains[domain_id]['name']}](contexts/{index.domain_pages[domain_id]}.md)"
                            for domain_id in index.rule_domains.get(rule['id'], ())) or '-'
        lines += [f'<a id="rule-{short(rule["id"])}"></a>', f"### {rule['name']}", '',
                  f"{rule_status(rule)} · {badge(rule.get('support'), EVIDENCE)}", '']
        if rule.get('description'):
            lines += [rule['description'], '']
        lines.append(f'- **Context:** {domains}')
        if rule.get('preconditions'):
            lines.append(f"- **Applies when:** {'; '.join(rule['preconditions'])}")
        kind = 'Formula' if rule.get('evaluation_kind') == 'formula' else 'Checks'
        lines.append(f"- **{kind}:** {code(rule.get('predicate_or_formula'))}")
        lines.append(f"- **Outcome:** {rule.get('outcome') or '-'}")
        activities = index.sorted_records(index.activities, rule.get('activity_ids', ()))
        if activities:
            lines.append('- **Use cases:** ' + ', '.join(activity['name'] for activity in activities))
        sites = []
        for site in rule.get('enforcement_sites', ()):
            citation = index.cite(site.get('evidence_ids'), 1)
            sites.append(f"{code(index.name(site.get('source_id', '')))} at {citation}"
                         + (f" when {code(site['condition'])}" if site.get('condition') else ''))
        lines.append('- **Enforced at:** ' + ('; '.join(sites) if sites else 'no enforcement site in the traced code'))
        scope = rule.get('scope') or {}
        scoped = [f'{key} {value}' for key, value in sorted(scope.items()) if value and key != 'entrypoint_ids']
        if scoped:
            lines.append('- **Scope:** ' + ', '.join(scoped))
        lines.append('- **Basis:** ' + (', '.join(item.replace('_', ' ') for item in rule.get('basis', ())) or '-'))
        basis = set(rule.get('basis') or ())
        first = 'configuration' if 'contract_declared' in basis and 'source_observed' not in basis else None
        lines.append(f"- **Evidence:** {index.cite(rule.get('evidence_ids'), 3, every_kind=True, first_kind=first)}")
        if rule.get('conflicts'):
            lines.append('- **Conflicts with:** ' + ', '.join(index.name(item) for item in rule['conflicts']))
        for question in rule.get('unresolved_questions', ()):
            lines.append(f'- **Open question:** {question}')
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def glossary_page(index: Model, entities: Entities) -> str:
    lines = ['# Glossary', '', '_Generated by `speed discover domains --export ddd`._', '',
             '[Back to the domain model](README.md)', '',
             'The ubiquitous language of the system: the terms its code and its contexts use, '
             'and the code behind each.', '', '## Entities', '']
    usage = index.concept_usage()
    for concept in index.sorted_records(index.concepts, index.concepts):
        types = ', '.join(code(name) for name in concept.get('qualified_type_names', ())) \
            or 'no code type; it exists as a table'
        tables = ', '.join(code(name) for name in entities.concept_tables(concept['id'])) or '-'
        owners = [f"{index.domains[ownership['domain_id']]['name']} ({ownership['kind']})"
                  for ownership in sorted(index.ownerships.values(), key=lambda item: item['id'])
                  if ownership['concept_id'] == concept['id'] and ownership.get('domain_id') in index.domains]
        contexts = sorted(set(index.concept_domains[concept['id']]) | set(usage.get(concept['id'], {})),
                          key=index.domain_order.index)
        used = ', '.join(index.domains[domain_id]['name']
                         + (f" ({', '.join(sorted(usage[concept['id']][domain_id]))})"
                            if usage.get(concept['id'], {}).get(domain_id) else '')
                         for domain_id in contexts)
        definition = next((claim['text'] for claim in index.claims_about.get(concept['id'], ())), None)
        lines += [f'<a id="term-{short(concept["id"])}"></a>', f"### {concept['name']}", '']
        if definition:
            lines += [definition, '']
        lines += [f'- **Code type:** {types}', f'- **Table:** {tables}',
                  f"- **Owned by:** {', '.join(owners) or 'no owning context'}",
                  f"- **Used in:** {used or '-'}" + (' (shared across contexts)' if len(contexts) > 1 else ''), '']
    lines += ['## Bounded contexts', '']
    for domain_id in index.domain_order:
        domain = index.domains[domain_id]
        lines.append(f"- **[{domain['name']}](contexts/{index.domain_pages[domain_id]}.md)**: "
                     f"{first_sentence(domain['summary'])}")
    lines += ['', '## Roles', '']
    roles = defaultdict(lambda: [0, False, set()])
    for activity in index.activities.values():
        names, enforced = index.access(activity)
        for role in names:
            roles[role][0] += 1
            roles[role][1] |= enforced
            roles[role][2].update(index.role_conditions(activity))
    for role in sorted(roles):
        count, enforced, conditions = roles[role]
        condition = max(sorted(conditions), key=len) if conditions else None
        lines.append(f"- **{role}**: declared on {plural(count, 'use case')}"
                     + ('' if enforced else '; no traced path proves it is enforced')
                     + (f'. Enforced only when: {condition}' if condition and not enforced else ''))
    unspecified = sum(not index.access(activity)[0] for activity in index.activities.values())
    if unspecified:
        lines.append(f"- {plural(unspecified, 'use case')} declare no role")
    return '\n'.join(lines).rstrip() + '\n'


def gaps_page(index: Model) -> str:
    model = index.raw
    lines = ['# Gaps', '', '_Generated by `speed discover domains --export ddd`._', '',
             '[Back to the domain model](README.md)', '',
             'What the model could not prove. Read this before relying on the other documents.', '',
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
    unassigned = sorted(model.get('unassigned', ()), key=lambda item: (item.get('status') != 'pending',
                                                                        index.name(item['subject_id'])))
    if unassigned:
        lines += ['## Entry points not modelled', '']
        lines += table([('Entry point', False), ('Status', False), ('Reason', False)],
                       [(cell(index.name(item['subject_id'])),
                         'not modelled yet' if item.get('status') == 'pending' else 'excluded',
                         cell(item.get('reason'))) for item in unassigned])
        lines.append('')
    conflicts = sorted((claim for claim in index.claims.values()
                        if claim.get('kind') in ('conflict', 'contradiction')),
                       key=lambda claim: (index.name(claim['subject_id']), claim['id']))
    if conflicts:
        lines += ['## Contract and implementation disagreements', '',
                  'Places where the code, its API contract, tests or configuration say different things.', '']
        lines += table([('About', False), ('Disagreement', False), ('Evidence', False)],
                       [(cell(index.name(claim['subject_id'])), cell(claim['text']),
                         index.cite(claim.get('evidence_ids'), every_kind=True)) for claim in conflicts])
        lines.append('')
    questions = []
    for domain_id in index.domain_order:
        domain = index.domains[domain_id]
        questions += [(domain['name'], question) for question in domain.get('unresolved_questions', ())]
    for ownership in sorted(index.ownerships.values(), key=lambda item: item['id']):
        if ownership.get('domain_id') in index.domains:
            subject = (f"{index.name(ownership['concept_id'])} (ownership: {ownership['kind']}, "
                       f"{index.domains[ownership['domain_id']]['name']})")
            questions += [(subject, question) for question in ownership.get('unresolved_questions', ())]
    for activity in index.sorted_records(index.activities, index.activities):
        questions += [(activity['name'], question) for question in activity.get('unresolved_questions', ())]
    if questions:
        lines += ['## Open questions', '']
        lines += table([('About', False), ('Question', False)],
                       [(cell(subject), cell(question)) for subject, question in questions])
        lines.append('')
    open_uses = defaultdict(list)
    for use in index.uses.values():
        if use.get('resolution') != 'resolved':
            for resource_id in use.get('resource_ids', ()):
                open_uses[(index.name(resource_id), use.get('access') or '-', use.get('resolution'))].append(use)
    if open_uses:
        lines += ['## Data access not fully resolved', '',
                  'The table is known; the statement, its completion, which implementation performs it '
                  'or whether it happens at all is not.', '']
        rows = []
        for (table_name, access, resolution), uses in sorted(open_uses.items()):
            reasons = sorted({first_sentence(use.get('reason') or '', 140) for use in uses if use.get('reason')})
            text = '<br>'.join(cell(reason) for reason in reasons[:3])
            if len(reasons) > 3:
                text += f'<br>and {len(reasons) - 3} more reasons'
            rows.append((cell(table_name), access, resolution, len(uses), text or '-'))
        lines += table([('Table', False), ('Access', False), ('Resolution', False), ('Count', True),
                        ('Reasons', False)], rows)
        lines.append('')
    warnings = Counter(item.get('code') for item in model.get('warnings', ()))
    if warnings:
        lines += ['## Extraction warnings', '']
        lines += table([('Code', False), ('Count', True)],
                       [(code(name), count) for name, count in sorted(warnings.items(),
                                                                      key=lambda item: (-item[1], item[0]))])
    return '\n'.join(lines).rstrip() + '\n'


# Entry points

def export_ddd(model: dict) -> dict:
    """Return the DDD documents for a published model as {relative path: text}."""
    index = Model(model)
    entities = Entities(index)
    sequences = Sequences(index)
    files = {'README.md': readme(index, entities), 'rules.md': rules_page(index),
             'glossary.md': glossary_page(index, entities), 'gaps.md': gaps_page(index)}
    for domain_id in index.domain_order:
        files[f'contexts/{index.domain_pages[domain_id]}.md'] = context_page(
            index, entities, sequences, domain_id)
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
            'counts': {'contexts': len(index.domain_order), 'use_cases': len(index.activities),
                       'entities': len(index.concepts), 'rules': len(index.rules),
                       'links': len(index.relationships)}}
