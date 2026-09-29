"""Read-only business participation for planning and task coordination."""
from collections import defaultdict
import logging

from .business_domains import load
from .business_domain_schema import DomainError


def read_business_model(root):
    try:
        return load(root)[0]
    except DomainError as exc:
        logging.getLogger(__name__).warning('Business context unavailable: %s',exc.code)
        return None


def participation(tasks, model):
    if not model:
        return []
    file_members = defaultdict(set)
    for domain in model['domains'].values():
        if domain['support']=='insufficient' or domain['review_state']=='rejected':
            continue
        for member in domain['symbol_memberships']:
            symbol = model['symbols'][member['symbol_id']]
            file_members[symbol['file']].add((domain['id'],member['activity_id']))
    result = []
    for task in tasks:
        matches = {member for path in task.get('files_touched',[]) for member in file_members[path]}
        result.append({'task_id':task['id'],'domain_ids':sorted({d for d,_ in matches}),
            'activity_ids':sorted({a for _,a in matches}),'participation':'potential',
            'reason':'File-scoped task; this is possible activity participation, not proof of the behavior being changed.'})
    return result


def domain_overlap(tasks, model):
    participating = participation(tasks,model)
    domain_tasks = defaultdict(set)
    for task in participating:
        for did in task['domain_ids']:
            domain_tasks[did].add(task['task_id'])
    return [{'domain_id':did,'name':model['domains'][did]['name'],
        'tasks_touching':sorted(task_ids),'participation':'potential',
        'activity_ids':sorted({aid for task in participating if task['task_id'] in task_ids
                              for aid in task['activity_ids'] if any(m['activity_id']==aid for m in model['domains'][did]['activity_memberships'])})}
        for did,task_ids in sorted(domain_tasks.items()) if len(task_ids)>1]


def file_participation(model, visible_ids=None):
    """Files can implement multiple responsibilities through distinct symbols."""
    files = defaultdict(set)
    if model:
        for did, domain in model['domains'].items():
            if visible_ids is not None and did not in visible_ids:
                continue
            if domain['review_state'] == 'rejected' or domain['support'] == 'insufficient':
                continue
            for member in domain['symbol_memberships']:
                files[model['symbols'][member['symbol_id']]['file']].add(did)
    return files


def project_participation(digest, model):
    """Project many-to-many file participation without reading source files."""
    visible = {d['id']:d for d in digest.get('domains',[])}
    files = file_participation(model,visible)
    for collection in ('hotspots','risks'):
        for item in digest.get(collection,[]):
            item.setdefault('cluster_id',item.pop('domain_id',''))
            paths = {item['file']} if item.get('file') else {e['path'] for e in item.get('evidence',[]) if e.get('path')}
            item['domain_ids'] = sorted({did for path in paths for did in files[path]})
            item['domain_participation'] = 'potential' if model else 'unknown'
    for row in digest.get('annotated_tree',[]):
        row.setdefault('dominant_structural_group_label',row.get('dominant_domain_label'))
        within = {path:ids for path,ids in files.items() if path.startswith(row['path']+'/') and ids}
        ids = sorted({did for group in within.values() for did in group})
        row['domain_ids'] = ids
        row['domain_labels'] = [visible[did]['name'] for did in ids]
        row['dominant_domain_label'] = row['domain_labels'][0] if len(ids)==1 else None
        row['shared_file_count'] = sum(len(group)>1 for group in within.values())
        row['unassigned_file_count'] = max(0,row['file_count']-len(within))
    digest['reading_path'] = [item for item in digest.get('reading_path',[]) if item.get('kind')!='domain']
    seen = {item['file'] for item in digest['reading_path']}
    if model:
        for did in sorted(visible):
            domain = visible[did]
            primary = {m['activity_id'] for m in domain['activity_memberships'] if m['role']=='primary'}
            anchors = sorted({anchor for aid in primary for anchor in model['activities'][aid]['anchor_ids']})
            for anchor_id in anchors:
                anchor = model['anchors'][anchor_id]
                symbol = model['symbols'].get(anchor['symbol_id'])
                if symbol and symbol['file'] not in seen:
                    digest['reading_path'].append({'file':symbol['file'],'kind':'domain',
                        'reason':f"Entry point for an evidenced activity in {domain['name']}; domain support is {domain['support']}."})
                    seen.add(symbol['file'])
                    break
    return digest
