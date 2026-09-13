"""Canonical business-domain discovery build and read boundary."""
from __future__ import annotations
import copy
try:
    import fcntl
except ImportError:
    fcntl = None
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .business_domain_extract import Extractor, inventory
from .business_domain_schema import (
    DomainError, account_artifact_bytes, atomic_write, copy_facts, digest,
    identifier, limits, now,
    quarantine_file, read_json, read_status, record, settings, validate, validate_references,
    validate_evidence, activity_closure, information_use_closure,
    implementation_symbol_memberships, reject_findings, validation_finding,
)
from .business_domain_synthesis import (
    POLICY, Synthesis, TERMINAL_PROVIDER_CODES, allowed_evidence_ids,
    prompt_fingerprint,
)
from .utils import load_speed_toml

INCOMPLETE_WORK_CODES = frozenset({
    'BUILD_BUDGET', 'BUILD_TIMEOUT', 'PACKET_LIMIT', 'PROVIDER_BUDGET', 'ACTIVITY_LIMIT',
    'SYNTHESIS_INCOMPLETE', 'OVERSIZED_ATOMIC_RECORD',
    'HIERARCHY_RECONCILIATION_FAILED',
})
EXHAUSTED_CONTRACT_CODES = frozenset({
    'INVALID_PROVIDER_OUTPUT', 'INVALID_ARTIFACT', 'INVALID_REFERENCE',
    'INVALID_ID', 'INVALID_EVIDENCE', 'INVALID_TRACE', 'INVALID_COVERAGE',
    'INVALID_ENFORCEMENT', 'INVALID_MEMBERSHIP', 'INSUFFICIENT_EVIDENCE',
    'EMPTY_DOMAIN', 'INVALID_REVIEW', 'SEMANTIC_VERIFICATION_FAILED',
})


def paths(root):
    directory = Path(root).resolve()/'.speed/context'
    return {name:directory/filename for name,filename in {
        'model':'business-domains.json','facts':'business-domain-facts.json',
        'status':'business-domain-status.json','overrides':'business-domain-overrides.json',
        'lock':'.repository-digest.lock','cancel':'.business-domain-cancel.json',
        'quarantine':'business-domain-quarantine'}.items()}


@contextmanager
def build_lock(root):
    if fcntl is None:
        raise DomainError('BUILD_LOCK_UNAVAILABLE','This platform has no supported cross-process build lock')
    path = paths(root)['lock']; path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():
        raise DomainError('UNSAFE_PATH','Build lock cannot be a symlink')
    with path.open('a+') as handle:
        try:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DomainError('BUILD_BUSY','Repository digest build already running') from exc
        try:
            yield handle
        finally:
            fcntl.flock(handle,fcntl.LOCK_UN)


def _io_read(root, recorder, name, path, limit=None):
    if not recorder:
        return read_json(path,limit) if limit is not None else read_json(path)
    relative = str(Path(path).relative_to(root))
    schema = _artifact_schema(name)
    with recorder.boundary(name,{'artifact':relative}, schema='ArtifactReference',
                           artifact=relative) as boundary:
        value = read_json(path,limit) if limit is not None else read_json(path)
        boundary.success(value,schema=schema,artifact=relative)
        return value


def _io_write(root, recorder, name, path, value, limit):
    if not recorder:
        return atomic_write(path,value,limit)
    relative = str(Path(path).relative_to(root))
    schema = _artifact_schema(name)
    with recorder.boundary(name,value,schema=schema,artifact=relative) as boundary:
        result = atomic_write(path,value,limit)
        boundary.success({'written':True},schema='ArtifactWriteResult',artifact=relative)
        return result


def _artifact_schema(name):
    for marker, schema in (
            ('facts', 'FactsArtifact'), ('status', 'StatusArtifact'),
            ('overrides', 'OverridesArtifact'), ('cache', 'CacheArtifact'),
            ('model', 'DomainArtifact'), ('baseline', 'DomainArtifact'),
            ('history', 'DomainArtifact'), ('cancel', 'CancellationArtifact')):
        if marker in name:
            return schema
    return 'JsonArtifact'


def load(root):
    """Read stored output only; never inventory, interpret, reconcile or write."""
    locations = paths(root)
    model = read_json(locations['model'])
    if model:
        validate(model,'DomainArtifact'); validate_references(model)
    status = read_status(locations['status'])
    return model,status


def projection(root):
    model,status = load(root)
    if status is None:
        status = record('StatusArtifact',limits=limits(settings(None)))
    result = record('DigestDomainProjection',domain_status=status)
    if model:
        visible = {did for did,d in model['domains'].items()
                   if d['review_state'] != 'rejected' and d['support'] != 'insufficient'}
        result.update(domain_build_id=model['build_id'],domain_fingerprint=model['fingerprint']['value'],
            domains=[d for did,d in model['domains'].items() if did in visible],
            relationships=[r for r in model['relationships'].values()
                           if r['from_domain_id'] in visible and r['to_domain_id'] in visible
                           and r['from_domain_id'] != r['to_domain_id']])
    validate(result,'DigestDomainProjection')
    return result


def cancel_build(root, build_id):
    locations = paths(root)
    status = read_status(locations['status'])
    if not status or status['attempt_build_id'] != build_id or status['phase'] not in ('extracting','synthesizing','validating'):
        raise DomainError('BUILD_NOT_RUNNING','The requested domain build is not running')
    if fcntl is None or not locations['lock'].is_file() or locations['lock'].is_symlink():
        raise DomainError('BUILD_NOT_RUNNING','No active build lock exists')
    with locations['lock'].open('r') as handle:
        try:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            fcntl.flock(handle,fcntl.LOCK_UN)
            raise DomainError('BUILD_NOT_RUNNING','The build has no active worker')
    atomic_write(locations['cancel'],{'schema_version':1,'build_id':build_id})
    return {'accepted':True,'build_id':build_id,'error':None}


def _allowed_evidence(payload, packet):
    allowed = set(allowed_evidence_ids(packet))
    findings = []
    def walk(value, subject_id=None):
        if isinstance(value,dict):
            subject_id = value.get('id', subject_id)
            if value.get('review_state') not in (None,'proposed'):
                findings.append(validation_finding(
                    'INVALID_REVIEW', 'Provider cannot set human review state',
                    subject_ids=([subject_id] if subject_id else [])))
            for key, child in value.items():
                if key.endswith('evidence_ids'):
                    invalid = set(child)-allowed
                    if invalid:
                        findings.append(validation_finding(
                            'INVALID_EVIDENCE',
                            'Provider cited evidence outside its packet',
                            subject_ids=([subject_id] if subject_id else []),
                            evidence_ids=invalid))
                walk(child, subject_id)
        elif isinstance(value,list):
            for child in value:
                walk(child, subject_id)
    walk(payload)
    reject_findings(findings)


def accept_activity(model, packet, payload):
    """Validate before mutating the candidate model, including cached output."""
    _allowed_evidence(payload,packet)
    candidate = copy.deepcopy(model)
    for collection in ('activities','rules','concepts','information_uses','claims'):
        overlap = set(candidate[collection]) & set(payload[collection])
        if any(candidate[collection][key] != payload[collection][key] for key in overlap):
            raise DomainError('INVALID_ID','Semantic record ID reused with different contents')
        candidate[collection].update(copy.deepcopy(payload[collection]))
    expected = set(packet['anchor_ids'])
    represented = {a for activity in payload['activities'].values() for a in activity['anchor_ids']}
    excluded, pending = set(payload['excluded_anchor_ids']),set(payload['pending_anchor_ids'])
    if represented | excluded | pending != expected or represented & (excluded|pending) or excluded & pending:
        raise DomainError('INVALID_COVERAGE','Each packet anchor needs exactly one disposition')
    for activity in payload['activities'].values():
        if not activity['evidence_ids'] or not activity['claim_ids'] or not activity['trace_ids']:
            raise DomainError('INSUFFICIENT_EVIDENCE','Activity needs evidence, claims and a trace')
        if any(t not in packet['context']['traces'] for t in activity['trace_ids']):
            raise DomainError('INVALID_TRACE','Activity refers to a trace outside its packet')
        if activity['support'] == 'supported' and any(
                packet['context']['traces'][tid]['resolution'] != 'resolved'
                for tid in activity['trace_ids']):
            raise DomainError('INVALID_TRACE',
                'Supported activity requires semantically complete implementation traces')
        # These lists are deterministic projections of the accepted traces.
        # Provider values are hints only; normalizing them locally prevents a
        # semantically correct candidate from failing on mechanically derivable
        # closure fields.
        for field, ids in activity_closure(candidate, activity).items():
            candidate['activities'][activity['id']][field] = sorted(ids)
        for rid in activity['rule_ids']:
            rule = candidate['rules'].get(rid)
            if rule is None:
                raise DomainError('INVALID_REFERENCE','Activity references a rule that was not supplied')
            if rule['enforcement_status'] == 'verified_on_trace' and any(
                    candidate['traces'][tid]['resolution'] != 'resolved' for tid in activity['trace_ids']):
                # Trace resolution is authoritative and mechanically known.
                # Downgrade an overconfident provider projection rather than
                # spending a semantic repair request on this deterministic
                # support ceiling.
                candidate['rules'][rid]['enforcement_status'] = 'declared_only'
    for use in payload['information_uses'].values():
        if use['activity_id'] not in payload['activities']:
            raise DomainError('INVALID_REFERENCE', 'Information use refers outside its activity response')
        closure = information_use_closure(candidate, use)
        stored = candidate['information_uses'][use['id']]
        for field in ('trace_ids', 'binding_ids', 'effect_ids'):
            stored[field] = sorted(closure[field])
        stored['evidence_ids'] = sorted(set(stored['evidence_ids']) | closure['evidence_ids'])
    for disposition, identifiers in (('excluded',excluded),('pending',pending)):
        for anchor in identifiers:
            reasons = [c['text'] for c in payload['claims'].values() if c['subject_id'] == anchor]
            if not reasons:
                raise DomainError('INVALID_COVERAGE','Excluded or pending anchor needs an explanation')
            candidate['unassigned'].append(record('Unassigned',subject_id=anchor,status=disposition,reason=reasons[0]))
    for rule in payload['rules'].values():
        if not set(rule['observation_ids']) <= set(packet['context']['rule_observations']):
            raise DomainError('INVALID_REFERENCE','Rule cites an observation outside its activity packet')
    for oid, observation in candidate['rule_observations'].items():
        users = [rule for rule in candidate['rules'].values() if oid in rule['observation_ids']]
        observation['rule_id'] = users[0]['id'] if len(users)==1 else None
        observation['activity_ids'] = sorted({aid for rule in users for aid in rule['activity_ids']})
    validate(candidate,'DomainArtifact'); validate_references(candidate)
    model.clear(); model.update(candidate)


def accept_activity_child(model, packet, payload):
    """Validate a hierarchical leaf without granting references outside it."""
    traces = set(packet['context']['traces'])
    effects = set(packet['context']['effects'])
    bindings = set(packet['context']['bindings'])
    resources = set(packet['context']['resources'])
    for activity in payload['activities'].values():
        if not set(activity['trace_ids']) <= traces:
            raise DomainError('INVALID_TRACE',
                              'Child activity refers outside its segment traces')
        if not set(activity['effect_ids']) <= effects:
            raise DomainError('INVALID_REFERENCE',
                              'Child activity refers outside its segment effects')
        if any(not set(activity[field]) <= bindings
               for field in ('input_binding_ids', 'output_binding_ids')):
            raise DomainError('INVALID_REFERENCE',
                              'Child activity refers outside its segment bindings')
    for use in payload['information_uses'].values():
        if (not set(use['resource_ids']) <= resources
                or not set(use['binding_ids']) <= bindings
                or not set(use['effect_ids']) <= effects):
            raise DomainError('INVALID_REFERENCE',
                              'Child information use refers outside its segment closure')
    for rule in payload['rules'].values():
        if (not set(rule['parameter_binding_ids']) <= bindings
                or not set(rule['dependency_ids']) <=
                    bindings | effects | resources | set(payload['rules'])):
            raise DomainError('INVALID_REFERENCE',
                              'Child rule refers outside its segment closure')
    accept_activity(model, packet, payload)


def materialize_observed_rules(model):
    """Promote every extracted constraint into a trace-linked declared rule."""
    activity_symbols = {
        activity_id: {symbol_id for trace_id in activity['trace_ids']
                      for symbol_id in model['traces'][trace_id]['symbol_ids']}
        for activity_id, activity in model['activities'].items()}
    symbol_locations = {}
    for symbol_id, symbol in model['symbols'].items():
        for evidence_id in symbol['evidence_ids']:
            locator = model['evidence'][evidence_id]['locator']
            symbol_locations.setdefault(locator['path'], []).append((
                locator['start_line'], locator['end_line'], symbol_id))
    for observation_id, observation in model['rule_observations'].items():
        existing = [rule for rule in model['rules'].values()
                    if observation_id in rule['observation_ids']]
        if existing:
            observation['rule_id'] = existing[0]['id'] if len(existing) == 1 else None
            observation['activity_ids'] = sorted({activity_id for rule in existing
                                                  for activity_id in rule['activity_ids']})
            continue
        observed_symbols = set()
        for evidence_id in observation['evidence_ids']:
            locator = model['evidence'][evidence_id]['locator']
            for start, end, symbol_id in symbol_locations.get(locator['path'], []):
                if start <= locator['start_line'] <= end:
                    observed_symbols.add(symbol_id)
        activity_ids = sorted(activity_id for activity_id, symbols in activity_symbols.items()
                              if symbols & observed_symbols)
        rule_id = identifier('rule', 'observation', observation_id)
        complete = bool(activity_ids) and all(
            model['traces'][trace_id]['resolution'] == 'resolved'
            for activity_id in activity_ids
            for trace_id in model['activities'][activity_id]['trace_ids'])
        source_kind = observation['source_location_kind']
        projection = POLICY['rule_projection'].get(
            source_kind, POLICY['rule_projection']['default'])
        model['rules'][rule_id] = record(
            'Rule', id=rule_id,
            name=(observation['native_expression'] or 'Observed constraint')[:120],
            description='Deterministically extracted constraint awaiting semantic refinement.',
            category=projection['category'], activity_ids=activity_ids,
            predicate_or_formula=observation['native_expression'],
            outcome='The declared constraint applies.',
            evidence_ids=observation['evidence_ids'], basis=[projection['basis']],
            enforcement_status='verified_on_trace' if complete else 'declared_only',
            support='supported' if activity_ids else 'partial',
            observation_ids=[observation_id], scope=copy.deepcopy(observation['scope']),
            parameter_binding_ids=observation['input_binding_ids'],
            dependency_ids=observation['dependency_ids'],
            evaluation_kind=projection['evaluation_kind'],
        )
        observation['rule_id'] = rule_id
        observation['activity_ids'] = activity_ids
        observation['resolution'] = 'resolved' if activity_ids else 'unresolved'
        observation['reason'] = (None if activity_ids else
            'No accepted activity trace contains the observed source symbol.')
        for activity_id in activity_ids:
            activity = model['activities'][activity_id]
            activity['rule_ids'] = sorted(set(activity['rule_ids']) | {rule_id})


def accept_grouping(model, packet, payload):
    _allowed_evidence(payload,packet)
    candidate = copy.deepcopy(model)
    for collection in ('domains','ownerships','relationships','rule_relationships','claims'):
        candidate[collection].update(copy.deepcopy(payload[collection]))
    for relationship in payload['rule_relationships'].values():
        if relationship['verification'] == 'verified':
            raise DomainError('INVALID_REVIEW','Semantic proposals cannot establish verified rule equivalence or precedence')
        endpoints = {relationship['from_observation_id'],relationship['to_observation_id']}
        if len(endpoints) != 2 or not endpoints <= set(packet['context']['rule_observations']):
            raise DomainError('INVALID_REFERENCE','Rule relationship needs two distinct observations supplied in the packet')
        claims = [claim for claim in payload['claims'].values() if claim['subject_id']==relationship['id']]
        if not relationship['evidence_ids'] or not claims or not relationship['explanation'].strip():
            raise DomainError('INSUFFICIENT_EVIDENCE','Rule relationship needs evidence, explanation and a reviewable claim')
    for domain in payload['domains'].values():
        if not domain['evidence_ids'] or not domain['claim_ids'] or not domain['boundary_rationale']:
            raise DomainError('INSUFFICIENT_EVIDENCE','Domain needs evidence and boundary claims')
        if not domain['activity_memberships']:
            raise DomainError('EMPTY_DOMAIN','Domain must contain a supported activity')
        domain = candidate['domains'][domain['id']]
        domain['symbol_memberships'] = []
        for membership in domain['activity_memberships']:
            if membership['activity_id'] not in packet['activity_ids']:
                raise DomainError('INVALID_MEMBERSHIP','Domain refers to an activity outside the grouping packet')
            activity = candidate['activities'].get(membership['activity_id'])
            if not activity or not membership['claim_ids']:
                raise DomainError('INVALID_MEMBERSHIP','Membership needs an existing activity and supporting claim')
        domain['symbol_memberships'] = implementation_symbol_memberships(
            candidate, (membership['activity_id'] for membership in domain['activity_memberships']))
        symbols = {m['symbol_id'] for m in domain['symbol_memberships']}
        domain['symbol_count'] = len(symbols)
        domain['file_count'] = len({candidate['symbols'][sid]['file'] for sid in symbols})
    assigned = {membership['activity_id'] for domain in payload['domains'].values()
                for membership in domain['activity_memberships']}
    for activity_id in sorted(set(packet['activity_ids'])-assigned):
        explanations = [claim['text'] for claim in payload['claims'].values()
                        if claim['subject_id'] == activity_id and claim['text'].strip()]
        if not explanations:
            raise DomainError('INVALID_COVERAGE','Activity omitted from all domains needs a grouping explanation')
        candidate['unassigned'].append(record('Unassigned',subject_id=activity_id,
            status='excluded',reason=explanations[0]))
    validate(candidate,'DomainArtifact');validate_references(candidate)
    model.clear();model.update(candidate)


def accept_candidate(model, graph, payload, *, verified=False):
    """Validate one complete canonical candidate before changing its model."""
    _allowed_evidence(payload, graph)
    candidate = copy.deepcopy(model)
    grouped_findings = {}

    def report(code, message, *subject_ids):
        """Collect equal violations while retaining every affected subject."""
        grouped_findings.setdefault((code, message), set()).update(
            subject_id for subject_id in subject_ids if subject_id)

    semantic_collections = (
        'activities', 'rules', 'concepts', 'information_uses', 'ownerships',
        'rule_relationships', 'claims', 'domains', 'relationships')
    for collection in semantic_collections:
        overlap = set(candidate[collection]) & set(payload[collection])
        conflicts = {
            record_id for record_id in overlap
            if candidate[collection][record_id] != payload[collection][record_id]
        }
        if conflicts:
            report(
                'INVALID_ID',
                'Semantic record ID reused with different contents',
                *conflicts)
        candidate[collection].update(copy.deepcopy(payload[collection]))

    traces = graph['context']['traces']
    observations = set(graph['context']['rule_observations'])
    for activity_id in sorted(payload['activities']):
        activity = payload['activities'][activity_id]
        trace_ids = set(activity['trace_ids'])
        outside_trace_ids = trace_ids-set(traces)
        unresolved_trace_ids = {
            trace_id for trace_id in trace_ids & set(traces)
            if traces[trace_id]['resolution'] != 'resolved'}
        if (not activity['evidence_ids'] or not activity['claim_ids']
                or not activity['trace_ids']):
            report(
                'INSUFFICIENT_EVIDENCE',
                'Activity needs evidence, claims and a trace', activity_id)
        if outside_trace_ids:
            report(
                'INVALID_TRACE',
                'Activity refers to a trace outside its graph scope',
                activity_id, *outside_trace_ids)
        incomplete_trace_ids = outside_trace_ids | unresolved_trace_ids
        if activity['support'] == 'supported' and incomplete_trace_ids:
            report(
                'INVALID_TRACE',
                'Supported activity requires resolved implementation traces',
                activity_id, *incomplete_trace_ids)
        for rule_id in sorted(activity['rule_ids']):
            rule = candidate['rules'].get(rule_id)
            if rule is None:
                report(
                    'INVALID_REFERENCE',
                    'Activity references a rule absent from the candidate',
                    activity_id, rule_id)
                continue
            if (rule['enforcement_status'] == 'verified_on_trace'
                    and incomplete_trace_ids):
                report(
                    'INVALID_ENFORCEMENT',
                    'Verified rule enforcement requires resolved traces',
                    activity_id, rule_id, *incomplete_trace_ids)
        if not outside_trace_ids:
            for field, identifiers in activity_closure(
                    candidate, activity).items():
                candidate['activities'][activity_id][field] = sorted(identifiers)

    for use_id in sorted(payload['information_uses']):
        use = payload['information_uses'][use_id]
        if use['activity_id'] not in payload['activities']:
            report(
                'INVALID_REFERENCE',
                'Information use refers outside its candidate activities',
                use_id, use['activity_id'])
            continue
        activity = payload['activities'][use['activity_id']]
        outside_trace_ids = set(activity['trace_ids'])-set(traces)
        if outside_trace_ids:
            continue
        try:
            closure = information_use_closure(candidate, use)
        except DomainError as exc:
            report(
                exc.code, str(exc), use_id, use['activity_id'],
                use['concept_id'], *use['resource_ids'])
            continue
        stored = candidate['information_uses'][use_id]
        for field in ('trace_ids', 'binding_ids', 'effect_ids'):
            stored[field] = sorted(closure[field])
        stored['evidence_ids'] = sorted(
            set(stored['evidence_ids']) | closure['evidence_ids'])

    for rule_id in sorted(payload['rules']):
        rule = payload['rules'][rule_id]
        outside_observation_ids = set(rule['observation_ids'])-observations
        if outside_observation_ids:
            report(
                'INVALID_REFERENCE',
                'Rule cites an observation outside its graph scope',
                rule_id, *outside_observation_ids)
    for observation_id, observation in candidate['rule_observations'].items():
        users = [rule for rule in candidate['rules'].values()
                 if observation_id in rule['observation_ids']]
        observation['rule_id'] = users[0]['id'] if len(users) == 1 else None
        observation['activity_ids'] = sorted({
            activity_id for rule in users
            for activity_id in rule['activity_ids']})

    for relationship_id in sorted(payload['rule_relationships']):
        relationship = payload['rule_relationships'][relationship_id]
        if relationship['verification'] == 'verified':
            report(
                'INVALID_REVIEW',
                'A semantic proposal cannot verify rule equivalence or precedence',
                relationship_id)
        endpoints = {
            relationship['from_observation_id'],
            relationship['to_observation_id']}
        if len(endpoints) != 2 or not endpoints <= observations:
            report(
                'INVALID_REFERENCE',
                'Rule relationship requires two supplied observations',
                relationship_id, *endpoints)
        claims = [claim for claim in payload['claims'].values()
                  if claim['subject_id'] == relationship_id]
        if (not relationship['evidence_ids'] or not claims
                or not relationship['explanation'].strip()):
            report(
                'INSUFFICIENT_EVIDENCE',
                'Rule relationship needs evidence, explanation and a claim',
                relationship_id)

    for domain_id in sorted(payload['domains']):
        domain = payload['domains'][domain_id]
        if (not domain['evidence_ids'] or not domain['claim_ids']
                or not domain['boundary_rationale'].strip()):
            report(
                'INSUFFICIENT_EVIDENCE',
                'Domain needs evidence and boundary claims', domain_id)
        if not domain['activity_memberships']:
            report('EMPTY_DOMAIN', 'Domain must contain an activity', domain_id)
        stored = candidate['domains'][domain_id]
        valid_activity_ids = []
        for membership in domain['activity_memberships']:
            activity_id = membership['activity_id']
            activity = payload['activities'].get(activity_id)
            if activity is None or not membership['claim_ids']:
                report(
                    'INVALID_MEMBERSHIP',
                    'Domain membership needs a candidate activity and claim',
                    domain_id, activity_id, *membership['claim_ids'])
            if (activity is not None
                    and set(activity['trace_ids']) <= set(traces)):
                valid_activity_ids.append(activity_id)
        stored['symbol_memberships'] = implementation_symbol_memberships(
            candidate, valid_activity_ids)
        symbols = {membership['symbol_id']
                   for membership in stored['symbol_memberships']}
        stored['symbol_count'] = len(symbols)
        missing_symbols = symbols-set(candidate['symbols'])
        if missing_symbols:
            report(
                'INVALID_REFERENCE',
                'Derived domain membership refers to an absent symbol',
                domain_id, *missing_symbols)
        stored['file_count'] = len({
            candidate['symbols'][symbol_id]['file']
            for symbol_id in symbols & set(candidate['symbols'])})

    candidate['unassigned'] = []
    for disposition in payload['dispositions']:
        if disposition['status'] == 'represented':
            continue
        candidate['unassigned'].append(record(
            'Unassigned', subject_id=disposition['subject_id'],
            status=('excluded' if disposition['status'] == 'excluded'
                    else 'pending'),
            reason=disposition['reason']))
    for claim_id in sorted(candidate['claims']):
        claim = candidate['claims'][claim_id]
        if not verified and claim['semantic_review'] != 'uncertain':
            report(
                'INVALID_REVIEW',
                'Candidate claims must remain unverified before verification',
                claim_id)
        if verified:
            claim['semantic_review'] = 'supported'

    findings = [
        validation_finding(code, message, subject_ids=subject_ids)
        for (code, message), subject_ids in sorted(grouped_findings.items())]
    reject_findings(findings)
    validate(candidate, 'DomainArtifact')
    validate_references(candidate)
    model.clear()
    model.update(candidate)


def apply_verdicts(model, submitted, payload):
    verdicts = {v['claim_id']:v for v in payload['verdicts']}
    if len(verdicts) != len(payload['verdicts']) or set(verdicts) != set(submitted):
        raise DomainError('INVALID_REVIEW','Semantic verification must cover every submitted claim exactly once')
    for claim_id in submitted:
        model['claims'][claim_id]['semantic_review'] = verdicts[claim_id]['verdict']
    for collection in ('activities','domains','ownerships','rules'):
        for item in model[collection].values():
            claim_ids = item.get('claim_ids')
            if claim_ids is None:
                claim_ids = [cid for cid,claim in model['claims'].items() if claim['subject_id']==item['id']]
            statuses = [model['claims'][cid]['semantic_review'] for cid in claim_ids]
            if not statuses or 'unsupported' in statuses:
                item['support'] = 'insufficient'
            elif 'uncertain' in statuses:
                item['support'] = 'partial'
            if collection == 'activities' and item['support'] == 'supported' and (
                    not item['trace_ids'] or any(model['traces'][tid]['resolution'] != 'resolved' for tid in item['trace_ids'])):
                item['support'] = 'partial'
            if collection == 'domains' and item['support'] == 'supported' and any(
                    model['activities'][m['activity_id']]['support'] != 'supported' for m in item['activity_memberships']):
                item['support'] = 'partial'
            if collection == 'rules' and item['support'] != 'supported' and item['enforcement_status'] == 'verified_on_trace':
                item['enforcement_status'] = 'unresolved'
    for relationship in model['rule_relationships'].values():
        statuses = [claim['semantic_review'] for claim in model['claims'].values()
                    if claim['subject_id']==relationship['id']]
        if not statuses or any(value!='supported' for value in statuses):
            relationship['verification'] = 'unresolved'
    for rule in model['rules'].values():
        rule['conflicts'] = sorted(relation['id'] for relation in model['rule_relationships'].values()
            if relation['kind']=='conflicts_with' and relation['verification']!='unresolved'
            and {relation['from_observation_id'],relation['to_observation_id']} & set(rule['observation_ids']))



def publication_status(model, external_freshness):
    """Derive publication completeness from evidenced work and declared gaps."""
    complete = (
        model['coverage']['anchors_pending'] == 0
        and not model['limits']['truncated']
        and external_freshness not in ('stale', 'unknown')
        and all(item['status'] == 'supported' for item in model['capabilities'])
        and all(item['resolution'] == 'resolved'
                for collection in ('traces', 'information_uses')
                for item in model[collection].values())
        and all(item.get('traversal_complete', True)
                for item in model['traces'].values())
        and all(item['support'] == 'supported'
                for collection in ('activities', 'domains', 'ownerships', 'rules')
                for item in model[collection].values())
        and all(item['semantic_review'] == 'supported'
                for item in model['claims'].values())
        and not any(item['status'] == 'pending' for item in model['unassigned'])
    )
    return 'complete' if complete else 'partial'


def discover(root, config=None, provider=None, lock_held=False, *,
             recorder=None, run_id=None):
    """Explicit refresh only. Failed attempts preserve the last valid model."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise DomainError('INVALID_ROOT','Repository root does not exist')
    raw_config = config if config is not None else load_speed_toml(str(root))
    config = settings(raw_config)
    if not lock_held:
        with build_lock(root):
            return discover(root,raw_config,provider,True,recorder=recorder,
                            run_id=run_id)
    locations = paths(root)
    def io_read(name, path, limit=None):
        return _io_read(root,recorder,name,path,limit)
    def io_write(name, path, value, limit):
        return _io_write(root,recorder,name,path,value,limit)
    previous_error = None
    try:
        old = io_read('artifact.model.read',locations['model'],config['max_artifact_bytes'])
        if old:
            validate(old,'DomainArtifact'); validate_references(old)
    except DomainError as exc:
        old = None
        previous_error = exc
        quarantine_file(locations['model'], locations['quarantine'],
                        config['max_artifact_bytes'])
    overrides = io_read('artifact.overrides.read',locations['overrides'])
    if old and overrides and overrides['revision'] > old['override_revision']:
        from .business_domain_review import replay
        recovered = replay(root,copy.deepcopy(old),overrides,previous=old)
        io_write('artifact.model.write',locations['model'],recovered,config['max_artifact_bytes'])
        old = recovered
    build_id = run_id or str(uuid.uuid4()); started = time.monotonic()
    status = record('StatusArtifact',attempt_build_id=build_id,phase='extracting',
        started_at=now(),published_build_id=old['build_id'] if old else None,
        freshness='stale' if old else 'missing',limits=limits(config))
    if previous_error:
        status['warnings'].append(record('Diagnostic',code='PREVIOUS_ARTIFACT_INVALID',
            message='The stored model could not be validated; refreshing from source evidence.'))
    def heartbeat():
        status['heartbeat_at'] = now()
        status['limits']['elapsed_ms'] = int((time.monotonic()-started)*1000)
        validate(status,'StatusArtifact')
        io_write('artifact.status.write',locations['status'],status,config['max_artifact_bytes'])
    def cancelled():
        marker = io_read('artifact.cancel.read',locations['cancel'])
        return bool(marker and marker.get('build_id') == build_id)
    heartbeat()
    pending_scope = []
    try:
        if recorder:
            recorder.progress('domain.extract','Extracting business-domain facts')
        extractor = Extractor(root,config,build_id)
        if recorder:
            with recorder.boundary('domain.extract',{'build_id':build_id}) as boundary:
                facts,_ = extractor.extract()
                boundary.success(facts,schema='FactsArtifact',
                    artifact='.speed/context/business-domain-facts.json')
        else:
            facts,_ = extractor.extract()
        facts['warnings'].extend(status['warnings'])
        status['external_freshness'] = extractor.external_freshness
        account_artifact_bytes(facts)
        io_write('artifact.facts.write',locations['facts'],facts,config['max_artifact_bytes'])
        status['coverage'] = facts['coverage']; status['limits'] = facts['limits']
        synthesis = Synthesis(root,config,provider,status['limits'],cancelled,
                              heartbeat,recorder=recorder)
        # Provider/model caps resolve after deterministic extraction. Persist
        # the updated shared Limits object so facts, attempt status and any
        # eventual model report the same effective request boundary.
        io_write('artifact.facts.write',locations['facts'],facts,config['max_artifact_bytes'])
        model = copy_facts(facts,build_id)
        model['fingerprint'].update(prompts=prompt_fingerprint(),provider=synthesis.provider_hash)
        model['fingerprint']['value'] = digest({k:v for k,v in model['fingerprint'].items() if k!='value'})
        synthesis.deadline = started+config['deadline_seconds']
        baseline = copy.deepcopy(model)
        graph = synthesis.graph_scope(baseline)
        pending_scope = [graph['scope_id']]
        status['limits']['model_ready_graph_tokens'] = \
            graph['estimated_input_tokens']
        status['limits']['semantic_units_total'] = 1
        status['limits']['semantic_units_validated'] = 0
        status['limits']['semantic_units_pending'] = 1
        status['execution_mode'] = 'whole_graph'
        status['root_reconciled'] = False
        status['phase'] = 'synthesizing'
        status['current_scope_id'] = graph['scope_id']
        heartbeat()

        def validate_candidate(payload):
            accept_candidate(
                copy.deepcopy(baseline), graph, payload, verified=False)

        if recorder:
            recorder.progress('semantic','Synthesizing and verifying business domains')
        payload = synthesis.run(graph, validate_candidate)
        if cancelled():
            raise DomainError('CANCELLED', 'Discovery cancelled')
        accept_candidate(model, graph, payload, verified=True)
        pending_scope = []
        status['current_scope_id'] = None
        status['root_reconciled'] = True
        represented = {
            anchor_id
            for activity in model['activities'].values()
            for anchor_id in activity['anchor_ids']}
        excluded = {
            disposition['subject_id']
            for disposition in payload['dispositions']
            if (disposition['subject_kind'] == 'anchor'
                and disposition['status'] == 'excluded')}
        model['coverage']['anchors_processed'] = len(represented)
        model['coverage']['anchors_excluded'] = len(excluded)
        model['coverage']['anchors_pending'] = (
            model['coverage']['anchors_total']
            - len(represented) - len(excluded))
        status['coverage'] = copy.deepcopy(model['coverage'])
        status['warnings'] = copy.deepcopy(model['warnings'])
        status['phase'] = 'validating'
        heartbeat()
        # Verify the input inventory again before publishing. A dirty/untracked
        # edit matters even when Git HEAD did not change.
        if cancelled():
            raise DomainError('CANCELLED','Discovery cancelled before publication')
        current,_ = inventory(root,config)
        if digest({s.path:s.source_hash for s in current}) != facts['fingerprint']['sources']:
            raise DomainError('SUPERSEDED','Sources changed during discovery')
        from .business_domain_snapshots import unchanged
        if not unchanged(root,extractor.snapshot_inputs,config['max_source_bytes']):
            raise DomainError('SUPERSEDED','Supplied snapshots changed during discovery')
        model['coverage']['anchors_processed'] = len({a for v in model['activities'].values() for a in v['anchor_ids']})
        model['coverage']['anchors_excluded'] = sum(u['status']=='excluded' and u['subject_id'] in facts['anchors'] for u in model['unassigned'])
        model['coverage']['anchors_pending'] = model['coverage']['anchors_total']-model['coverage']['anchors_processed']-model['coverage']['anchors_excluded']
        model['limits'] = copy.deepcopy(status['limits'])
        from .business_domain_identity import reconcile
        if recorder:
            recorder.progress('domain.validate','Reconciling canonical identities and validating references')
        previous = old
        if old and old['override_revision']:
            previous = io_read('artifact.baseline.read',root/'.speed/context/business-domain-baselines'/f'{old["facts_build_id"]}.json')
            if previous is None and overrides and overrides['decisions']:
                previous = io_read('artifact.history.read',root/'.speed/context/business-domain-history'/f'{overrides["decisions"][0]["expected_build_id"]}.json')
        reconcile(model,previous)
        validate(model,'DomainArtifact');validate_references(model)
        if overrides:
            from .business_domain_review import replay
            replay(root,model,overrides,previous=old)
        model['status'] = publication_status(model, status['external_freshness'])
        validate(model,'DomainArtifact');validate_references(model)
        validate_evidence(root,model,config['max_artifact_bytes'])
        if time.monotonic() >= synthesis.deadline:
            raise DomainError('BUILD_TIMEOUT', 'Discovery deadline exceeded before publication')
        account_artifact_bytes(model)
        # A baseline is a validated publication companion, not an attempt
        # scratch file.  Do not persist the candidate before every semantic,
        # override, evidence and deadline gate has passed.
        if recorder:
            recorder.progress('domain.publish','Publishing verified domain model')
            publication = recorder.boundary('domain.publish',model)
        else:
            publication = None
        try:
            io_write('artifact.baseline.write',root/'.speed/context/business-domain-baselines'/f'{model["facts_build_id"]}.json',model,config['max_artifact_bytes'])
            if old:
                io_write('artifact.history.write',root/'.speed/context/business-domain-history'/f'{old["build_id"]}.json',old,config['max_artifact_bytes'])
            io_write('artifact.model.write',locations['model'],model,config['max_artifact_bytes'])
            if publication:
                publication.success(model,schema='DomainArtifact',
                    artifact='.speed/context/business-domains.json')
        except Exception as exc:
            if publication:
                publication.__exit__(type(exc),exc,exc.__traceback__)
            raise
        status.update(phase=model['status'],published_build_id=model['build_id'],freshness='current',
                      coverage=model['coverage'],warnings=model['warnings'])
        status['limits']['artifact_bytes'] = model['limits']['artifact_bytes']
        from .business_domain_retention import cleanup
        try:
            if recorder:
                with recorder.boundary('artifact.retention',{
                        'retention_days':config['cache_retention_days']}) as boundary:
                    cleanup(root,config)
                    boundary.success({'completed':True})
            else:
                cleanup(root,config)
        except (DomainError,OSError):
            # Publication is complete. Disposable storage maintenance cannot
            # invalidate the newly validated result or remove review history.
            status['warnings'] = list(status['warnings'])+[record('Diagnostic',
                code='CLEANUP_FAILED',message='Published discovery is available; disposable artifact cleanup could not finish.')]
    except (DomainError,KeyboardInterrupt) as exc:
        if isinstance(exc,KeyboardInterrupt):
            exc = DomainError('CANCELLED','Discovery interrupted')
        if exc.code in INCOMPLETE_WORK_CODES:
            status['limits']['truncated'] = True
            status['warnings'].append(record('Diagnostic', code=exc.code,
                message=str(exc), subject_ids=([exc.field] if exc.field else pending_scope)))
        elif exc.code in TERMINAL_PROVIDER_CODES:
            # Keep the exact undispatched/incomplete semantic scope visible;
            # provider causality remains on the terminal error itself.
            status['warnings'].append(record('Diagnostic', code=exc.code,
                message=str(exc), subject_ids=pending_scope))
        status['phase'] = {'CANCELLED':'cancelled','SUPERSEDED':'superseded',
                           'PROVIDER_UNAVAILABLE':'unavailable'}.get(exc.code,'failed')
        status['error'] = exc.record()
        if recorder:
            recorder.emit('domain.pipeline','error',error=status['error'])
    except Exception as exc:
        status['phase'] = 'failed'
        status['error'] = DomainError('INTERNAL_ERROR',f'Discovery failed unexpectedly ({type(exc).__name__}); previous published output is preserved').record()
        if recorder:
            recorder.emit('domain.pipeline','error',error=status['error'])
    finally:
        status['current_scope_id'] = None
        status['completed_at'] = now(); heartbeat()
    if previous_error and status['phase'] in ('failed','cancelled','unavailable','superseded'):
        return None,status
    return load(root)
