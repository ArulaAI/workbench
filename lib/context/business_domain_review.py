"""Apply and replay user review decisions on the domain model."""
from __future__ import annotations
import copy
import uuid
from pathlib import Path
from .business_domain_schema import (
    DomainError, atomic_write, canonical, digest, identifier, now, read_json,
    record, validate, validate_references, implementation_symbol_memberships,
)
from .business_domains import build_lock, load, paths


def _operation(operation):
    if not isinstance(operation,dict):
        raise DomainError('INVALID_REVIEW','Review operation must be an object')
    operation = copy.deepcopy(operation)
    if isinstance(operation.get('name'),str):
        operation['name'] = operation['name'].strip()
    if isinstance(operation.get('groups'),list):
        for group in operation['groups']:
            if isinstance(group,dict) and isinstance(group.get('name'),str):
                group['name'] = group['name'].strip()
    validate(operation,'ReviewOperation')
    return operation


def _recount(model, domain):
    members = {m['activity_id'] for m in domain['activity_memberships']}
    domain['symbol_memberships'] = implementation_symbol_memberships(model, members)
    symbols = {m['symbol_id'] for m in domain['symbol_memberships']}
    domain['symbol_count'] = len(symbols)
    domain['file_count'] = len({model['symbols'][sid]['file'] for sid in symbols})
    domain['concepts'] = sorted({cid for aid in members for cid in model['activities'][aid]['concept_ids']})
    domain['rules'] = sorted({rid for aid in members for rid in model['activities'][aid]['rule_ids']})
    domain['ownership_ids'] = sorted(k for k,v in model['ownerships'].items() if v['domain_id'] == domain['id'])


RECORD_CORRECTIONS = ('correct_rule', 'merge_rules', 'correct_activity', 'correct_domain')


def _cited_span(root, model, span, recorded_at):
    """Return the evidence id for lines of a repository file named by a reviewer, adding it when new."""
    if root is None:
        raise DomainError('INVALID_REVIEW', 'A correction that cites source lines needs the repository root')
    path, root = span['path'], Path(root)
    file = (root / path).resolve()
    if not file.is_relative_to(root.resolve()) or not file.is_file():
        raise DomainError('REVIEW_CONFLICT', f'Cited file is not in the repository: {path}')
    raw = file.read_bytes()
    lines = raw.decode('utf-8').splitlines(keepends=True)
    if not 1 <= span['start_line'] <= span['end_line'] <= len(lines):
        raise DomainError('REVIEW_CONFLICT', f'Cited lines are outside {path}')
    start = sum(len(line) for line in lines[:span['start_line'] - 1])
    excerpt = ''.join(lines[span['start_line'] - 1:span['end_line']]).rstrip('\n')
    source_hash = digest(raw)
    sid = identifier('snapshot', path, source_hash, start, start + len(excerpt))
    eid = identifier('ev', path, source_hash, start, start + len(excerpt))
    if eid in model['evidence']:
        return eid
    same_file = [item for item in model['evidence'].values() if item['locator'].get('path') == path]
    kinds = [model['source_snapshots'][item['locator']['snapshot_id']]['resource_kind'] for item in same_file
             if item['locator'].get('snapshot_id') in model['source_snapshots']]
    snapshot = record('SnapshotArtifact', snapshot_id=sid, source_hash=source_hash, fragments=[{
        'id': identifier('fragment', eid), 'original_locator': path, 'text': excerpt,
        'excerpt_hash': digest(excerpt.encode())}])
    relative = f'.speed/context/business-domain-snapshots/{digest(snapshot)}.json'
    atomic_write(root / relative, snapshot)
    model['source_snapshots'][sid] = record('Snapshot', id=sid, resource_kind=kinds[0] if kinds else 'source',
        resource_identity=path, content_hash=source_hash, local_blob_path=relative, retrieved_at=recorded_at)
    model['evidence'][eid] = record('Evidence', id=eid,
        source_kind=same_file[0]['source_kind'] if same_file else 'source',
        locator={'kind': 'repository_span', 'path': path, 'start_line': span['start_line'],
                 'end_line': span['end_line'], 'source_hash': source_hash, 'snapshot_id': sid,
                 'pointer': '/fragments/0/text'},
        content_hash=digest(excerpt.encode()), excerpt=excerpt, claim_kind='source_observation',
        extractor='domain-review', extractor_version='1')
    return eid


def _replace_references(value, old, new):
    """Point every reference to a retired id at its replacement, dropping duplicates in lists."""
    if isinstance(value, dict):
        for key, child in value.items():
            if child == old:
                value[key] = new
            else:
                _replace_references(child, old, new)
    elif isinstance(value, list):
        replaced = [new if child == old else child for child in value]
        if replaced != value:
            value[:] = list(dict.fromkeys(item for item in replaced if isinstance(item, str))) \
                if all(isinstance(item, str) for item in replaced) else replaced
        for child in value:
            _replace_references(child, old, new)


def _correct_records(model, operation, root=None, recorded_at=None):
    """Apply a reviewed correction to rules, use cases or a context's text. Returns the changed ids."""
    kind = operation['operation']
    if kind == 'correct_rule' or kind == 'merge_rules':
        rule_ids = [operation['rule_id']] if kind == 'correct_rule' else operation['rule_ids']
        if any(rid not in model['rules'] for rid in rule_ids):
            raise DomainError('REVIEW_CONFLICT', 'Reviewed rule no longer exists')
        keep = model['rules'][rule_ids[0]]
        for rid in rule_ids[1:]:
            other = model['rules'].pop(rid)
            for field in ('activity_ids', 'concept_ids', 'evidence_ids', 'unresolved_questions', 'observation_ids',
                          'conflicts', 'parameter_binding_ids', 'dependency_ids'):
                keep[field] = list(dict.fromkeys(keep[field] + other[field]))
            keep['enforcement_sites'] = keep['enforcement_sites'] + [site for site in other['enforcement_sites']
                                                                     if site not in keep['enforcement_sites']]
            keep['basis'] = list(dict.fromkeys(keep['basis'] + other['basis']))
            _replace_references(model, rid, rule_ids[0])
        keep['conflicts'] = [rid for rid in keep['conflicts'] if rid != rule_ids[0]]
        missing = [eid for eid in operation.get('add_evidence_ids', ()) if eid not in model['evidence']]
        if missing:
            raise DomainError('INVALID_REVIEW', 'Correction cites evidence that is not in the model')
        dropped = set(operation.get('drop_evidence_ids', ()))
        keep['evidence_ids'] = [eid for eid in keep['evidence_ids'] if eid not in dropped]
        keep['evidence_ids'] = list(dict.fromkeys(keep['evidence_ids'] + list(operation.get('add_evidence_ids', ()))))
        changes = copy.deepcopy(operation.get('set', {}))
        cite = lambda spans: [_cited_span(root, model, span, recorded_at) for span in spans]
        keep['evidence_ids'] = list(dict.fromkeys(keep['evidence_ids'] + cite(operation.get('cite', ()))))
        if 'enforcement_sites' in changes:
            sites = []
            for site in changes['enforcement_sites']:
                ids = list(dict.fromkeys(site.get('evidence_ids', []) + cite(site.get('cite', ()))))
                if any(eid not in model['evidence'] for eid in ids) or site['source_id'] not in model['symbols'] \
                        and site['source_id'] not in model['resources']:
                    raise DomainError('INVALID_REVIEW', 'Enforcement site cites a record that is not in the model')
                sites.append({'activity_ids': site.get('activity_ids', []), 'source_id': site['source_id'],
                              'condition': site['condition'], 'evidence_ids': ids})
                keep['evidence_ids'] = list(dict.fromkeys(keep['evidence_ids'] + ids))
            changes['enforcement_sites'] = sites
        keep.update(changes)
        if 'user_asserted' not in keep['basis']:
            keep['basis'].append('user_asserted')
        return [rule_ids[0]]
    if kind == 'correct_activity':
        if operation['activity_id'] not in model['activities']:
            raise DomainError('REVIEW_CONFLICT', 'Reviewed use case no longer exists')
        model['activities'][operation['activity_id']].update(copy.deepcopy(operation['set']))
        return [operation['activity_id']]
    if operation['domain_id'] not in model['domains']:
        raise DomainError('REVIEW_CONFLICT', 'Reviewed domain no longer exists')
    domain = model['domains'][operation['domain_id']]
    changes = copy.deepcopy(operation['set'])
    if 'alternatives' in changes:
        if len(changes['alternatives']) != len(domain['alternatives']):
            raise DomainError('REVIEW_CONFLICT', 'Reviewed domain lists a different number of alternatives')
        changes['alternatives'] = [dict(item, explanation=text)
                                   for item, text in zip(domain['alternatives'], changes['alternatives'])]
    domain.update(changes)
    return [operation['domain_id']]


def apply_decision(model, decision, root=None):
    """Apply a review decision to the model in place and return the resulting domain ids."""
    operation = _operation(decision['operation']); kind = operation['operation']
    if kind in RECORD_CORRECTIONS:
        changed = _correct_records(model, operation, root, decision['recorded_at'])
        model['override_revision'] = decision['revision']
        model['build_id'] = str(uuid.uuid5(uuid.NAMESPACE_URL,model['fingerprint']['sources']+decision['id']))
        decision['result_domain_ids'] = changed if kind == 'correct_domain' else []
        decision['result_record_ids'] = changed
        return changed
    target_ids = operation.get('domain_ids',[operation.get('domain_id')])
    if any(did not in model['domains'] for did in target_ids):
        raise DomainError('REVIEW_CONFLICT','Reviewed domain no longer exists')
    originals = [model['domains'][did] for did in target_ids]
    resulting = target_ids
    if kind in ('accept','reject'):
        originals[0]['review_state'] = 'accepted' if kind == 'accept' else 'rejected'
    elif kind == 'rename':
        originals[0]['name'] = operation['name']
    elif kind == 'set_membership':
        if not set(operation['activity_ids']) <= set(model['activities']):
            raise DomainError('INVALID_REVIEW','Membership references an unknown activity')
        originals[0]['activity_memberships'] = [record('ActivityMembership',activity_id=aid,role='primary')
                                               for aid in operation['activity_ids']]
    else:
        primary = {m['activity_id'] for d in originals for m in d['activity_memberships'] if m['role']=='primary'}
        if kind == 'merge':
            groups = [{'name':operation['name'],'activity_ids':sorted(primary)}]
        else:
            groups = operation['groups']
            assigned = [aid for g in groups for aid in g['activity_ids']]
            if len(assigned) != len(set(assigned)) or set(assigned) != primary:
                raise DomainError('INVALID_REVIEW','Split must partition every prior primary activity exactly once')
        resulting = []
        for index,group in enumerate(groups):
            did = identifier('domain','review',decision['id'],index)
            domain = copy.deepcopy(originals[0]);domain['id'] = did;domain['name'] = group['name']
            domain['activity_memberships'] = [record('ActivityMembership',activity_id=aid,role='primary')
                                              for aid in group['activity_ids']]
            supporting = {m['activity_id'] for d in originals for m in d['activity_memberships'] if m['role']=='supporting'}
            for aid in sorted(supporting-set(group['activity_ids'])):
                domain['activity_memberships'].append(record('ActivityMembership',activity_id=aid,role='supporting'))
            domain['claim_ids'] = [];domain['ownership_ids'] = []
            model['domains'][did] = domain;resulting.append(did)
        for did in target_ids:
            del model['domains'][did]
        retired_claims = {cid for cid,c in model['claims'].items() if c['subject_id'] in target_ids}
        for cid in retired_claims:
            del model['claims'][cid]
        # Drop references to retired claims; history keeps the originals.
        def remove_retired(value):
            if isinstance(value,dict):
                for key,child in value.items():
                    if key == 'claim_ids':
                        value[key] = [cid for cid in child if cid not in retired_claims]
                    else:remove_retired(child)
            elif isinstance(value,list):
                for child in value:remove_retired(child)
        remove_retired(model)
        for ownership in model['ownerships'].values():
            if ownership['domain_id'] in target_ids:
                ownership.update(domain_id=resulting[0] if kind=='merge' else None,
                                 review_state='needs_review')
                if ownership['support'] == 'supported':
                    ownership['support'] = 'partial'
        model['identity_changes'].append(record('IdentityChange',kind='merged' if kind=='merge' else 'split',
            from_ids=target_ids,to_ids=resulting,reason=decision['explanation']))
    if kind not in ('accept','reject'):
        for did in resulting:
            domain = model['domains'][did]
            domain['review_state'] = 'needs_review'
            if domain['support'] == 'supported':
                domain['support'] = 'partial'
            domain['boundary_rationale'] = decision['explanation']
            _recount(model,domain)
    primary_domains = {m['activity_id']:d['id'] for d in model['domains'].values()
                       for m in d['activity_memberships'] if m['role']=='primary'}
    for rid,relationship in list(model['relationships'].items()):
        source = primary_domains.get(relationship['from_activity_id'])
        target = primary_domains.get(relationship['to_activity_id'])
        if not source or not target or source==target:
            del model['relationships'][rid]
        else:
            relationship['from_domain_id'] = source
            relationship['to_domain_id'] = target
    model['override_revision'] = decision['revision']
    model['build_id'] = str(uuid.uuid5(uuid.NAMESPACE_URL,model['fingerprint']['sources']+decision['id']))
    decision['result_domain_ids'] = resulting
    return resulting


def _review_evidence(root, model, decision):
    text = canonical(decision).decode(); sid = identifier('snapshot',decision['id']); eid = identifier('ev',decision['id'])
    snapshot = record('SnapshotArtifact',snapshot_id=sid,source_hash=digest(text.encode()),
        fragments=[{'id':identifier('fragment',decision['id']),'original_locator':decision['id'],
                    'text':text,'excerpt_hash':digest(text.encode())}])
    blob = digest(snapshot); relative = f'.speed/context/business-domain-snapshots/{blob}.json'
    atomic_write(root/relative,snapshot)
    model['source_snapshots'][sid] = record('Snapshot',id=sid,resource_kind='user_review',
        resource_identity=decision['id'],content_hash=digest(text.encode()),local_blob_path=relative,retrieved_at=decision['recorded_at'])
    model['evidence'][eid] = record('Evidence',id=eid,source_kind='user_review',
        locator={'kind':'snapshot_pointer','snapshot_id':sid,'pointer':'/fragments/0/text'},
        content_hash=digest(text.encode()),excerpt=text,claim_kind='user_asserted',
        extractor='domain-review',extractor_version='1')
    for rid in decision.get('result_record_ids', ()):
        if rid in model['rules']:
            model['rules'][rid]['evidence_ids'].append(eid)
        elif rid in model['activities']:
            model['activities'][rid]['evidence_ids'].append(eid)
    for did in decision['result_domain_ids']:
        cid = identifier('claim',decision['id'],did)
        model['claims'][cid] = record('Claim',id=cid,subject_id=did,text=decision['explanation'],
            kind='user_asserted',evidence_ids=[eid],semantic_review='uncertain')
        model['domains'][did]['claim_ids'].append(cid)
        model['domains'][did]['evidence_ids'].append(eid)
    model['coverage']['evidence_valid'] = len(model['evidence'])


def replay(root, model, overrides, previous=None):
    """Replay saved decisions newer than the model's override revision.

    Decisions that no longer apply are recorded as REVIEW_CONFLICT warnings.
    An accept goes back to needs_review if its supporting evidence changed.
    """
    validate(overrides,'OverridesArtifact')
    def support_hashes(artifact,domain):
        return {artifact['evidence'][eid]['content_hash'] for eid in domain['evidence_ids']
                if artifact['evidence'][eid]['source_kind'] != 'user_review'}
    for saved in overrides['decisions']:
        if saved['revision'] <= model['override_revision']:
            continue
        decision = copy.deepcopy(saved)
        did = decision['operation'].get('domain_id')
        changed = False
        if decision['operation']['operation'] == 'accept' and previous and did in previous['domains'] and did in model['domains']:
            changed = support_hashes(previous,previous['domains'][did]) != support_hashes(model,model['domains'][did])
        candidate = copy.deepcopy(model)
        try:
            apply_decision(candidate,decision,root)
            _review_evidence(root,candidate,decision)
            if changed:
                candidate['domains'][did]['review_state'] = 'needs_review'
                candidate['warnings'].append(record('Diagnostic',code='REVIEW_EVIDENCE_CHANGED',
                    message='Prior acceptance requires review because supporting excerpts changed.',subject_ids=[did]))
            validate(candidate,'DomainArtifact');validate_references(candidate)
        except DomainError as exc:
            model['warnings'].append(record('Diagnostic',code='REVIEW_CONFLICT',
                message=f"Committed review revision {saved['revision']} could not be applied: {exc}"))
            model['override_revision'] = saved['revision']
            continue
        model.clear();model.update(candidate)
    model['fingerprint']['overrides'] = digest(overrides)
    model['fingerprint']['value'] = digest({k:v for k,v in model['fingerprint'].items() if k!='value'})
    return model


def review(root, expected_build_id, operation, explanation, author):
    from pathlib import Path
    root = Path(root).resolve(); operation = _operation(operation)
    explanation = explanation.strip()
    with build_lock(root):
        model,status = load(root)
        if model is None:
            raise DomainError('DOMAIN_DISCOVERY_MISSING','No canonical domains have been published')
        if model['build_id'] != expected_build_id:
            raise DomainError('STALE_BUILD','The domain model changed; reload before reviewing')
        locations = paths(root)
        overrides = read_json(locations['overrides']) or record('OverridesArtifact')
        validate(overrides,'OverridesArtifact')
        decision = record('Decision',id=identifier('decision',str(uuid.uuid4())),
            revision=overrides['revision']+1,expected_build_id=expected_build_id,
            author=author,recorded_at=now(),explanation=explanation,operation=operation)
        validate(decision,'Decision')
        candidate = copy.deepcopy(model)
        result_ids = apply_decision(candidate,decision,root)
        _review_evidence(root,candidate,decision)
        overrides['decisions'].append(decision);overrides.update(revision=decision['revision'],updated_at=now())
        candidate['fingerprint']['overrides'] = digest(overrides)
        candidate['fingerprint']['value'] = digest({k:v for k,v in candidate['fingerprint'].items() if k!='value'})
        validate(candidate,'DomainArtifact');validate_references(candidate);validate(overrides,'OverridesArtifact')
        atomic_write(root/'.speed/context/business-domain-history'/f'{model["build_id"]}.json',model)
        # Write overrides first so a crash before the model write can be replayed.
        atomic_write(locations['overrides'],overrides)
        atomic_write(locations['model'],candidate)
        if status:
            status['published_build_id'] = candidate['build_id']
            atomic_write(locations['status'],status)
        return {'accepted':True,'build_id':candidate['build_id'],'domain_ids':result_ids,'error':None}


def review_batch(root, expected_build_id, items, author):
    """Apply several review decisions as one change: one validation, one history copy, one write.

    `items` is a list of (operation, explanation). Returns the new build id.
    """
    from pathlib import Path
    root = Path(root).resolve()
    with build_lock(root):
        model,status = load(root)
        if model is None:
            raise DomainError('DOMAIN_DISCOVERY_MISSING','No canonical domains have been published')
        if model['build_id'] != expected_build_id:
            raise DomainError('STALE_BUILD','The domain model changed; reload before reviewing')
        locations = paths(root)
        overrides = read_json(locations['overrides']) or record('OverridesArtifact')
        validate(overrides,'OverridesArtifact')
        candidate = copy.deepcopy(model)
        for operation, explanation in items:
            operation = _operation(operation)
            decision = record('Decision',id=identifier('decision',str(uuid.uuid4())),
                revision=overrides['revision']+1,expected_build_id=candidate['build_id'],
                author=author,recorded_at=now(),explanation=explanation.strip(),operation=operation)
            validate(decision,'Decision')
            apply_decision(candidate,decision,root)
            _review_evidence(root,candidate,decision)
            overrides['decisions'].append(decision);overrides.update(revision=decision['revision'],updated_at=now())
        candidate['fingerprint']['overrides'] = digest(overrides)
        candidate['fingerprint']['value'] = digest({k:v for k,v in candidate['fingerprint'].items() if k!='value'})
        validate(candidate,'DomainArtifact');validate_references(candidate);validate(overrides,'OverridesArtifact')
        atomic_write(root/'.speed/context/business-domain-history'/f'{model["build_id"]}.json',model)
        # Write overrides first so a crash before the model write can be replayed.
        atomic_write(locations['overrides'],overrides)
        atomic_write(locations['model'],candidate)
        if status:
            status['published_build_id'] = candidate['build_id']
            atomic_write(locations['status'],status)
        return candidate['build_id']
