"""Conservative domain and entry-point identity, never display names."""
import json
import copy
from pathlib import Path
from .business_domain_schema import identifier, record

POLICY = json.loads(Path(__file__).with_name('business_domain_policies.json').read_text())

ENTRYPOINT_ROLES = frozenset({'registration', 'exposure', 'contract'})


def _anchor_defaults(anchor):
    """Permit legacy producers while making their missing decision explicit."""
    anchor.setdefault('canonical_anchor_id', None)
    anchor.setdefault('eligibility', 'unresolved')
    anchor.setdefault('representations', [])
    anchor.setdefault('correspondences', [])


def _eligible_representations(anchor):
    return [representation for representation in anchor['representations']
            if representation['role'] in ENTRYPOINT_ROLES
            and representation['eligibility'] == 'eligible'
            and representation['identity_key']]


def _canonical_identity(representations):
    """Choose an adapter-established entry-point identity without source ordering."""
    for role in ('registration', 'exposure', 'contract'):
        identities = {item['identity_key'] for item in representations if item['role'] == role}
        if len(identities) == 1:
            return next(iter(identities))
        if len(identities) > 1:
            return None
    return None


def _canonical_representation(representations):
    """Return the stable representation that owns canonical display fields."""
    for role in ('registration', 'exposure', 'contract'):
        candidates = sorted(
            (item for item in representations if item['role'] == role),
            key=lambda item: item['id'],
        )
        identities = {item['identity_key'] for item in candidates}
        if len(identities) == 1:
            return candidates[0]
        if len(identities) > 1:
            return None
    return None


def update_anchor_coverage(model):
    """Recalculate source-representation and canonical-anchor inventory."""
    anchors = model.get('anchors', {})
    coverage = model.get('coverage')
    if coverage is None:
        return
    representations = {
        item['id']: item
        for anchor in anchors.values()
        for item in anchor.get('representations', [])
    }
    correspondences = {
        item['id']: item
        for anchor in anchors.values()
        for item in anchor.get('correspondences', [])
    }
    canonicalized = {
        representation['id']
        for anchor in anchors.values()
        if anchor.get('canonical_anchor_id')
        for representation in anchor.get('representations', [])
    }
    coverage.update(
        anchors_total=len(anchors),
        representations_total=len(representations),
        representations_canonicalized=len(canonicalized),
        correspondences_ambiguous=sum(
            item['state'] == 'ambiguous' for item in correspondences.values()),
        correspondences_unresolved=sum(
            item['state'] == 'unresolved' for item in correspondences.values()),
    )


def reconcile_anchors(model):
    """Canonicalize representations connected by explicit resolved correspondence.

    Adapters own registration, exposure and implementation semantics.  This pass
    deliberately does not compare names, routes, languages, frameworks or source
    order.  A resolved one-to-one correspondence is the only evidence that lets
    a supporting representation join an eligible entry point.
    """
    anchors = model.get('anchors', {})
    for anchor in anchors.values():
        _anchor_defaults(anchor)

    representation_owners = {}
    for anchor_id, anchor in anchors.items():
        for representation in anchor['representations']:
            representation_owners.setdefault(representation['id'], []).append(anchor_id)

    # Resolved one-to-one correspondences form representation components.  The
    # component is merged only when it has one unambiguous canonical identity;
    # ambiguous/unresolved/review-required proposals never establish identity.
    adjacency = {anchor_id: set() for anchor_id in anchors}
    for anchor_id, anchor in anchors.items():
        for correspondence in anchor['correspondences']:
            if correspondence['state'] != 'resolved' or len(correspondence['to_representations']) != 1:
                continue
            source_owners = representation_owners.get(correspondence['from_representation'], [])
            target_owners = representation_owners.get(correspondence['to_representations'][0], [])
            if source_owners != [anchor_id] or len(target_owners) != 1:
                continue
            target_id = target_owners[0]
            if target_id != anchor_id:
                adjacency[anchor_id].add(target_id)
                adjacency[target_id].add(anchor_id)

    components = []
    remaining = set(anchors)
    while remaining:
        start = min(remaining)
        component = set()
        frontier = [start]
        while frontier:
            current = frontier.pop()
            if current in component:
                continue
            component.add(current)
            frontier.extend(adjacency[current] - component)
        remaining -= component
        components.append(component)

    replacements = {}
    identity_counts = {}
    component_identities = []
    for component in components:
        eligible = [item for anchor_id in component
                    for item in _eligible_representations(anchors[anchor_id])]
        identity_key = _canonical_identity(eligible)
        component_identities.append(identity_key)
        if identity_key:
            identity_counts[identity_key] = identity_counts.get(identity_key, 0) + 1

    canonical = {}
    for component, identity_key in zip(components, component_identities):
        component_anchors = [anchors[anchor_id] for anchor_id in sorted(component)]
        eligible = [item for anchor in component_anchors
                    for item in _eligible_representations(anchor)]
        if not identity_key or identity_counts.get(identity_key) != 1:
            for anchor in component_anchors:
                anchor['eligibility'] = 'supporting' if (
                    anchor['representations']
                    and all(item['eligibility'] == 'supporting'
                            for item in anchor['representations'])) else 'unresolved'
                if identity_key and identity_counts[identity_key] != 1:
                    anchor['resolution'] = 'ambiguous'
                    anchor['reason'] = (
                        'Canonical identity key is shared without a resolved correspondence.')
                elif eligible:
                    anchor['resolution'] = 'ambiguous'
                    anchor['reason'] = (
                        'Resolved representations supply conflicting canonical identity keys.')
                canonical[anchor['id']] = anchor
            continue

        canonical_id = identifier('anchor', 'canonical', identity_key)
        selected = _canonical_representation(eligible)
        owner = next(anchor for anchor in component_anchors
                     if any(item['id'] == selected['id']
                            for item in anchor['representations']))
        result = copy.deepcopy(owner)
        result['id'] = canonical_id
        result['source_id'] = selected['source_id']
        result['symbol_id'] = selected['symbol_id']
        result['operation'] = copy.deepcopy(selected['operation'])
        result['canonical_anchor_id'] = canonical_id
        result['eligibility'] = 'eligible'
        result['reason'] = (None if result['resolution'] == 'resolved' else
                            owner.get('reason') or
                            'Canonical identity is stable, but implementation resolution remains incomplete.')
        result['representations'] = []
        result['correspondences'] = []
        result['evidence_ids'] = []
        for anchor in component_anchors:
            result['representations'].extend(copy.deepcopy(anchor['representations']))
            result['correspondences'].extend(copy.deepcopy(anchor['correspondences']))
            result['evidence_ids'].extend(anchor['evidence_ids'])
            replacements[anchor['id']] = canonical_id
        result['representations'] = sorted(
            {item['id']: item for item in result['representations']}.values(), key=lambda item: item['id'])
        result['correspondences'] = sorted(
            {item['id']: item for item in result['correspondences']}.values(), key=lambda item: item['id'])
        result['evidence_ids'] = sorted(set(result['evidence_ids']))
        canonical[canonical_id] = result

    def rewrite(value, parent=None):
        if isinstance(value, str) and parent not in {
                'from_representation', 'to_representations', 'identity_key'}:
            return replacements.get(value, value)
        if isinstance(value, list):
            return [rewrite(item, parent) for item in value]
        if isinstance(value, dict):
            return {replacements.get(key, key): rewrite(item, key) for key, item in value.items()}
        return value

    model['anchors'] = canonical
    rewritten = rewrite(model)
    model.clear()
    model.update(rewritten)
    update_anchor_coverage(model)
    return replacements


def reconcile(model,previous):
    if not previous:
        return
    before={did:{m['activity_id'] for m in d['activity_memberships'] if m['role']=='primary'}
            for did,d in previous['domains'].items()}
    after={did:{m['activity_id'] for m in d['activity_memberships'] if m['role']=='primary'}
           for did,d in model['domains'].items()}
    scores={(old,new):len(a&b)/len(a|b) if a|b else 0
            for old,a in before.items() for new,b in after.items()}
    def best(ident,candidates,reverse=False):
        ranked=[(scores[(other,ident) if reverse else (ident,other)],other) for other in candidates]
        if not ranked:return None
        score=max(s for s,_ in ranked)
        winners=[other for s,other in ranked if s==score]
        return winners[0] if len(winners)==1 and score>=POLICY['domain_identity_min_overlap'] else None
    replacements={}
    for new in after:
        old=best(new,before,True)
        if old and best(old,after)==new:
            replacements[new]=old
    def rewrite(value):
        if isinstance(value,str):return replacements.get(value,value)
        if isinstance(value,list):return [rewrite(v) for v in value]
        if isinstance(value,dict):return {replacements.get(k,k):rewrite(v) for k,v in value.items()}
        return value
    rewritten=rewrite(model)
    model.clear();model.update(rewritten)
    for new,old in replacements.items():
        model['identity_changes'].append(record('IdentityChange',kind='retained',from_ids=[old],to_ids=[old],
            reason='Unique mutual activity-membership match exceeds the configured identity threshold.'))
    for old,old_members in before.items():
        successors=[replacements.get(new,new) for new,members in after.items() if old_members & members]
        if old in replacements.values():continue
        if len(successors)>1:
            model['identity_changes'].append(record('IdentityChange',kind='split',from_ids=[old],to_ids=sorted(successors),
                reason='Overlapping activity memberships have no unique mutual identity match.'))
        elif not successors:
            model['identity_changes'].append(record('IdentityChange',kind='retired',from_ids=[old],to_ids=[],
                reason='No current activity membership overlaps this previous domain.'))
        elif sum(bool(before[other] & after[new]) for other in before
                 for new in after if replacements.get(new,new)==successors[0]) == 1:
            model['identity_changes'].append(record('IdentityChange',kind='retired',from_ids=[old],to_ids=[],
                reason='The only overlapping successor does not meet the identity continuity threshold.'))
    for new,new_members in after.items():
        predecessors=[old for old,members in before.items() if new_members & members]
        if new in replacements:continue
        if len(predecessors)>1:
            model['identity_changes'].append(record('IdentityChange',kind='merged',from_ids=sorted(predecessors),to_ids=[new],
                reason='Overlapping activity memberships have no unique mutual identity match.'))
        elif not predecessors:
            model['identity_changes'].append(record('IdentityChange',kind='added',from_ids=[],to_ids=[new],
                reason='No previous domain contains these activity memberships.'))
        elif sum(bool(before[predecessors[0]] & members) for members in after.values()) == 1:
            model['identity_changes'].append(record('IdentityChange',kind='added',from_ids=[],to_ids=[new],
                reason='The only overlapping predecessor does not meet the identity continuity threshold.'))
