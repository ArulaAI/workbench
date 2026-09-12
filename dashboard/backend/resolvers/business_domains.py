"""Read-only, build-scoped detail paging and deterministic review adapters."""
import base64
import json
from dataclasses import asdict

from lib.context.business_domains import load, cancel_build
from lib.context.business_domain_schema import DomainError as CoreError, canonical, limits, record, settings
from lib.context.business_domain_review import review
from . import business_domain_types as types


def error(exc, expected=None, current=None):
    return types.DomainError(code=exc.code,message=str(exc),field=exc.field,
        expected_build_id=expected,current_build_id=current)


def current_model(root, expected):
    model,_ = load(root)
    if not model:
        return None,types.DomainError(code='DOMAIN_DISCOVERY_MISSING',message='No domain model has been published',expected_build_id=expected)
    if model['build_id'] != expected:
        return None,types.DomainError(code='STALE_BUILD',message='Reload the domain model before continuing',
            expected_build_id=expected,current_build_id=model['build_id'])
    return model,None


def status(root):
    try:
        _,value = load(root)
    except CoreError as exc:
        value = record('StatusArtifact',phase='failed',limits=limits(settings(None)),error=exc.record())
    return types.to_record(value or record('StatusArtifact',limits=limits(settings(None))),'StatusArtifact')


def connection(root, build_id, domain_id, collection, first, after):
    singular = {'activities':'Activity','rules':'Rule','evidence':'Evidence',
                'concepts':'Concept','ownerships':'Ownership','claims':'Claim','unassigned':'Unassigned'}[collection]
    result_type = getattr(types,'Domain'+singular+'Connection')
    edge_type = getattr(types,'Domain'+singular+'Edge')
    empty = dict(edges=[],page_info=types.DomainPageInfo(end_cursor=None,has_next_page=False))
    try:
        if not 1 <= first <= 100:
            raise CoreError('INVALID_INPUT','first must be between 1 and 100','first')
        model,problem = current_model(root,build_id)
        if problem:
            return result_type(**empty,error=problem)
        domain = model['domains'].get(domain_id)
        records = model[collection]
        if collection == 'unassigned':
            # This canonical collection is a list; positions are stable within
            # the immutable build used by the existing cursor contract.
            records = {str(index):value for index,value in enumerate(records)}
        elif domain is None:
            raise CoreError('DOMAIN_NOT_FOUND','The requested domain does not exist in this build','domainId')
        if collection == 'unassigned':
            selected = set(records)
        elif collection == 'activities':
            selected = {m['activity_id'] for m in domain['activity_memberships']}
        elif collection == 'claims':
            subjects = {domain_id,*domain['concepts'],*domain['rules'],*domain['ownership_ids'],
                        *(m['activity_id'] for m in domain['activity_memberships'])}
            selected = set(domain['claim_ids']) | {cid for member in domain['activity_memberships'] for cid in member['claim_ids']}
            selected.update(cid for cid,claim in model['claims'].items() if claim['subject_id'] in subjects)
        else:
            selected = set(domain[{'rules':'rules','evidence':'evidence_ids',
                                   'concepts':'concepts','ownerships':'ownership_ids'}[collection]])
        ids = sorted(selected)
        scope = {'schema_version':1,'build_id':build_id,'collection':collection,'parent_id':domain_id}
        start = 0
        if after is not None:
            try:
                cursor = json.loads(base64.b64decode(after,altchars=b'-_',validate=True))
                if not isinstance(cursor,dict) or set(cursor) != set(scope)|{'last_id'}:
                    raise ValueError()
                if cursor['build_id'] != build_id:
                    raise CoreError('STALE_BUILD','Cursor belongs to another build','after')
                if any(cursor[k]!=v for k,v in scope.items()):
                    raise ValueError()
                start = ids.index(cursor['last_id'])+1
            except (ValueError,TypeError,KeyError) as exc:
                if isinstance(exc,CoreError):
                    raise
                raise CoreError('INVALID_CURSOR','Cursor does not belong to this collection','after') from exc
        edges = []
        for ident in ids[start:start+first]:
            cursor = base64.urlsafe_b64encode(canonical({**scope,'last_id':ident})).decode()
            stored = records[ident]
            node = types.to_record(stored,singular)
            if collection == 'activities':
                for attr,key,source,type_name in (
                    ('_input_records','input_binding_ids','bindings','Binding'),
                    ('_output_records','output_binding_ids','bindings','Binding'),
                    ('_trace_records','trace_ids','traces','Trace'),
                    ('_effect_records','effect_ids','effects','Effect')):
                    setattr(node,attr,[types.to_record(model[source][key_id],type_name) for key_id in stored[key]])
                for trace in node._trace_records:
                    trace._obligation_records = [types.to_record(model['trace_obligations'][oid], 'TraceObligation')
                                                 for oid in trace.obligation_ids]
            elif collection == 'rules':
                observation_ids = set(stored['observation_ids'])
                node._observation_records = [types.to_record(model['rule_observations'][oid],'RuleObservation')
                                             for oid in sorted(observation_ids)]
                node._relationship_records = [types.to_record(relation,'RuleRelationship')
                    for relation in model['rule_relationships'].values()
                    if observation_ids & {relation['from_observation_id'],relation['to_observation_id']}]
            elif collection == 'ownerships':
                node._concept_record = types.to_record(model['concepts'][stored['concept_id']],'Concept')
            edges.append(edge_type(cursor=cursor,node=node))
        return result_type(edges=edges,page_info=types.DomainPageInfo(
            end_cursor=edges[-1].cursor if edges else None,has_next_page=start+first<len(ids)),error=None)
    except CoreError as exc:
        return result_type(**empty,error=error(exc,build_id))


def review_input(value):
    operation = {'operation':value.operation.value}
    ids = [str(ident) for ident in value.domain_ids]
    if value.operation.value == 'merge':
        operation['domain_ids'] = ids
    else:
        if len(ids) != 1:
            raise CoreError('INVALID_INPUT','This operation requires exactly one domain ID','domainIds')
        operation['domain_id'] = ids[0]
    for name in ('name','activity_ids','groups'):
        supplied = getattr(value,name)
        if supplied is not None:
            operation[name] = [asdict(group) for group in supplied] if name=='groups' else supplied
    return operation
