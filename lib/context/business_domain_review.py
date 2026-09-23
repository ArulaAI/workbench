"""Deterministic, optimistic-concurrency review of canonical domain records."""
from __future__ import annotations
import copy
import uuid
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


def apply_decision(model, decision):
    """Apply to a private candidate. No provider calls and no source scanning."""
    operation = _operation(decision['operation']); kind = operation['operation']
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
        # Retired claims remain in immutable model history. Remove references
        # from the current projection rather than retargeting their meaning.
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
    for did in decision['result_domain_ids']:
        cid = identifier('claim',decision['id'],did)
        model['claims'][cid] = record('Claim',id=cid,subject_id=did,text=decision['explanation'],
            kind='user_asserted',evidence_ids=[eid],semantic_review='uncertain')
        model['domains'][did]['claim_ids'].append(cid)
        model['domains'][did]['evidence_ids'].append(eid)
    model['coverage']['evidence_valid'] = len(model['evidence'])


def replay(root, model, overrides, previous=None):
    """Replay committed decisions after a crash or discovery refresh.

    Missing targets become explicit review conflicts. Human acceptance is
    invalidated when the supporting source excerpts changed.
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
            apply_decision(candidate,decision)
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
        result_ids = apply_decision(candidate,decision)
        _review_evidence(root,candidate,decision)
        overrides['decisions'].append(decision);overrides.update(revision=decision['revision'],updated_at=now())
        candidate['fingerprint']['overrides'] = digest(overrides)
        candidate['fingerprint']['value'] = digest({k:v for k,v in candidate['fingerprint'].items() if k!='value'})
        validate(candidate,'DomainArtifact');validate_references(candidate);validate(overrides,'OverridesArtifact')
        atomic_write(root/'.speed/context/business-domain-history'/f'{model["build_id"]}.json',model)
        # Commit intent first. A subsequent explicit refresh can replay a
        # committed revision if a crash interrupts projection publication.
        atomic_write(locations['overrides'],overrides)
        atomic_write(locations['model'],candidate)
        if status:
            status['published_build_id'] = candidate['build_id']
            atomic_write(locations['status'],status)
        return {'accepted':True,'build_id':candidate['build_id'],'domain_ids':result_ids,'error':None}
