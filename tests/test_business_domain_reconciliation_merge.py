"""How a reconciliation joins its children into one model.

SPEED does the bookkeeping of a merge: child groupings stay unless the answer
changes them, a returned domain takes over its activities, retired domains
hand their ownerships on, and relationships follow their activities. Where
children connect in ways none could see, SPEED states it and checks that the
candidate answers it.
"""
from lib.context.business_domain_synthesis import Synthesis
from lib.context.business_domain_work import (
    SEMANTIC_COLLECTIONS, Unit, _merge_concepts, expand_reconciliation,
    reconciliation_findings, verification_view,
)


def _domain(domain_id, *members, ownerships=(), alternatives=()):
    return {'id': domain_id, 'name': domain_id, 'evidence_ids': [], 'claim_ids': [],
            'activity_memberships': [{'activity_id': activity_id, 'role': 'primary',
                                      'claim_ids': []} for activity_id in members],
            'ownership_ids': list(ownerships), 'alternatives': list(alternatives),
            'exclusions': [], 'concepts': [], 'rules': []}


def _relationship(relationship_id, source, target, source_domain, target_domain):
    return {'id': relationship_id, 'from_activity_id': source, 'to_activity_id': target,
            'from_domain_id': source_domain, 'to_domain_id': target_domain,
            'kind': 'uses_information_from', 'trace_ids': [], 'evidence_ids': []}


def _regrouping_scope():
    """Three child domains, two owning one concept, and two relationships."""
    context = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    context['activities'] = {
        name: {'id': name, 'anchor_ids': [f'anchor:{name[-1]}'], 'claim_ids': [],
               'rule_ids': [], 'concept_ids': ['concept:c']}
        for name in ('activity:a', 'activity:b', 'activity:c')}
    context['concepts'] = {'concept:c': {'id': 'concept:c', 'claim_ids': []}}
    context['domains'] = {'domain:one': _domain('domain:one', 'activity:a',
                                                ownerships=['ownership:one']),
                          'domain:two': _domain('domain:two', 'activity:b',
                                                ownerships=['ownership:two']),
                          'domain:three': _domain('domain:three', 'activity:c')}
    context['ownerships'] = {
        name: {'id': name, 'domain_id': domain_id, 'concept_id': 'concept:c', 'kind': kind,
               'activity_ids': [activity_id], 'information_use_ids': [], 'claim_ids': [],
               'evidence_ids': [], 'unresolved_questions': []}
        for name, domain_id, kind, activity_id in (
            ('ownership:one', 'domain:one', 'maintains', 'activity:a'),
            ('ownership:two', 'domain:two', 'creates', 'activity:b'))}
    context['relationships'] = {
        'relationship:ab': _relationship('relationship:ab', 'activity:a', 'activity:b',
                                         'domain:one', 'domain:two'),
        'relationship:ac': _relationship('relationship:ac', 'activity:a', 'activity:c',
                                         'domain:one', 'domain:three')}
    context['claims'] = {'claim:two': {'id': 'claim:two', 'subject_id': 'domain:two',
                                       'kind': 'boundary'},
                         'claim:three': {'id': 'claim:three', 'subject_id': 'domain:three',
                                         'kind': 'boundary'}}
    answer = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    answer['dispositions'] = [{'subject_kind': 'child_scope', 'subject_id': 'scope:child',
                               'status': 'represented',
                               'incorporated_record_ids': sorted(context['activities'])}]
    return {'scope_kind': 'reconciliation', 'context': context, 'record_refs': {}}, answer


def test_child_groupings_the_answer_leaves_alone_are_kept():
    scope, answer = _regrouping_scope()

    complete = expand_reconciliation(scope, answer)

    assert set(complete['domains']) == {'domain:one', 'domain:two', 'domain:three'}
    assert set(complete['ownerships']) == {'ownership:one', 'ownership:two'}
    assert set(complete['relationships']) == {'relationship:ab', 'relationship:ac'}
    assert {'claim:two', 'claim:three'} <= set(complete['claims'])


def test_a_returned_domain_retires_the_child_domains_it_takes_over():
    scope, answer = _regrouping_scope()
    answer['domains'] = {'domain:merged': _domain('domain:merged', 'activity:a', 'activity:b')}

    complete = expand_reconciliation(scope, answer)

    # Both child domains whose activities it took are retired with the claims
    # about them; the untouched one stays.
    assert set(complete['domains']) == {'domain:merged', 'domain:three'}
    assert 'claim:two' not in complete['claims'] and 'claim:three' in complete['claims']
    # Their ownerships of the concept moved to the merged domain and combined,
    # the stronger kind standing.
    [ownership] = complete['ownerships'].values()
    assert ownership['domain_id'] == 'domain:merged' and ownership['kind'] == 'creates'
    assert set(ownership['activity_ids']) == {'activity:a', 'activity:b'}
    assert complete['domains']['domain:merged']['ownership_ids'] == [ownership['id']]
    # Relationships follow their activities into their current domains.
    ends = {relationship_id: (item['from_domain_id'], item['to_domain_id'])
            for relationship_id, item in complete['relationships'].items()}
    assert ends == {'relationship:ab': ('domain:merged', 'domain:merged'),
                    'relationship:ac': ('domain:merged', 'domain:three')}


def test_a_child_domain_keeps_only_the_activities_no_returned_domain_took():
    scope, answer = _regrouping_scope()
    scope['context']['domains']['domain:one']['activity_memberships'].append(
        {'activity_id': 'activity:c', 'role': 'supporting', 'claim_ids': []})
    answer['domains'] = {'domain:moved': _domain('domain:moved', 'activity:c')}

    complete = expand_reconciliation(scope, answer)

    assert [membership['activity_id'] for membership
            in complete['domains']['domain:one']['activity_memberships']] == ['activity:a']
    assert 'domain:three' not in complete['domains']


def test_verification_sees_only_the_child_records_the_candidate_replaced():
    scope, answer = _regrouping_scope()
    scope['context']['record_refs'] = {}
    answer['domains'] = {'domain:merged': _domain('domain:merged', 'activity:a', 'activity:b')}
    complete = expand_reconciliation(scope, answer)

    view = verification_view(scope, complete)

    assert set(view['context']['domains']) == {'domain:one', 'domain:two'}
    assert view['context']['activities'] == {}
    # The retired domains still name their activities, which stay identifiable.
    assert {'activity:a', 'activity:b'} <= set(view['context']['record_refs'])
    assert set(scope['context']['domains']) == {'domain:one', 'domain:two', 'domain:three'}


def test_kept_records_the_coverage_manifests_name_stay_identifiable():
    scope, answer = _regrouping_scope()
    scope['context']['record_refs'] = {}
    scope['coverage_manifests'] = [{'child_scope_id': 'scope:child',
                                    'represented': [{'anchor_id': 'anchor:c',
                                                     'activity_ids': ['activity:c']}]}]
    complete = expand_reconciliation(scope, answer)

    view = verification_view(scope, complete)

    # activity:c is kept, so the view omits it; its manifest still names it.
    assert 'activity:c' not in view['context']['activities']
    assert 'activity:c' in view['context']['record_refs']


def test_concepts_naming_one_code_type_are_supplied_as_one():
    model = {'symbols': {'symbol:p': {'qualified_name': 'src/pay.ts::Payment'},
                         'symbol:m': {'qualified_name': 'src/money.ts::Minor'}}}
    context = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    context['concepts'] = {
        'concept:1': {'id': 'concept:1', 'qualified_type_names': ['src/pay.ts::Payment'],
                      'symbol_ids': [], 'evidence_ids': ['ev:1'], 'claim_ids': []},
        'concept:2': {'id': 'concept:2', 'qualified_type_names': ['Payment', 'PaymentStore'],
                      'symbol_ids': [], 'evidence_ids': ['ev:2'], 'claim_ids': []},
        'concept:3': {'id': 'concept:3', 'qualified_type_names': ['Minor[]'],
                      'symbol_ids': [], 'evidence_ids': [], 'claim_ids': []}}
    context['activities'] = {'activity:a': {'id': 'activity:a',
                                            'concept_ids': ['concept:1', 'concept:2']}}

    aliases = _merge_concepts(model, context)

    # A bare name resolves to the one declared type carrying it; an array of
    # a type is not that type.
    assert aliases == {'concept:2': 'concept:1'}
    assert set(context['concepts']) == {'concept:1', 'concept:3'}
    assert context['concepts']['concept:1']['evidence_ids'] == ['ev:1', 'ev:2']
    assert context['activities']['activity:a']['concept_ids'] == ['concept:1']


def test_concepts_sharing_several_types_merge_once():
    model = {'symbols': {}}
    context = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    context['concepts'] = {
        name: {'id': name, 'qualified_type_names': ['a.ts::Entry', 'a.ts::Account'],
               'symbol_ids': [], 'evidence_ids': [], 'claim_ids': []}
        for name in ('concept:1', 'concept:2')}

    assert _merge_concepts(model, context) == {'concept:2': 'concept:1'}


def test_a_bare_type_name_two_declarations_carry_resolves_to_neither():
    model = {'symbols': {'symbol:1': {'qualified_name': 'billing/a.ts::Order'},
                         'symbol:2': {'qualified_name': 'shipping/b.ts::Order'}}}
    context = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    context['concepts'] = {
        name: {'id': name, 'qualified_type_names': names, 'symbol_ids': [],
               'evidence_ids': [], 'claim_ids': []}
        for name, names in (('concept:1', ['billing/a.ts::Order']), ('concept:2', ['Order']))}

    assert _merge_concepts(model, context) == {}


def _connected_units():
    """Two slices: one creates the payments store, the other only reads it."""
    units = []
    for scope_id, activity_id, anchor_id, access, domain_id in (
            ('scope:write', 'activity:authorise', 'anchor:authorise', 'creates', 'domain:pay'),
            ('scope:read', 'activity:refund', 'anchor:refund', 'reads', 'domain:refunds')):
        payload = {collection: {} for collection in SEMANTIC_COLLECTIONS}
        payload['activities'] = {activity_id: {'id': activity_id, 'anchor_ids': [anchor_id],
                                               'name': activity_id}}
        payload['information_uses'] = {f'use:{activity_id}': {
            'activity_id': activity_id, 'resource_ids': ['resource:payments'],
            'access': access, 'evidence_ids': []}}
        payload['domains'] = {domain_id: _domain(domain_id, activity_id)}
        coverage = {anchor_id: {'status': 'represented', 'activity_ids': [activity_id],
                                'reason': None, 'evidence_ids': []}}
        units.append(Unit({'scope_id': scope_id}, payload, coverage))
    candidate = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    for unit in units:
        for collection in SEMANTIC_COLLECTIONS:
            candidate[collection].update(unit.payload[collection])
    candidate['dispositions'] = []
    return units, candidate


def test_information_only_another_slice_writes_needs_a_relationship():
    units, candidate = _connected_units()

    [finding] = reconciliation_findings({}, units, candidate)

    assert finding['code'] == 'MISSING_RELATIONSHIP'
    assert set(finding['subject_ids']) == {
        'activity:refund', 'activity:authorise', 'resource:payments'}
    candidate['relationships'] = {'relationship:x': {
        'from_activity_id': 'activity:refund', 'to_activity_id': 'activity:authorise'}}
    assert reconciliation_findings({}, units, candidate) == []


def test_a_shared_domain_answers_a_cross_slice_read():
    units, candidate = _connected_units()
    candidate['domains'] = {'domain:pay': _domain('domain:pay', 'activity:authorise',
                                                  'activity:refund')}

    assert reconciliation_findings({}, units, candidate) == []


def test_domains_one_class_declares_need_merging_or_a_decision():
    units, candidate = _connected_units()
    candidate['relationships'] = {'relationship:x': {
        'from_activity_id': 'activity:refund', 'to_activity_id': 'activity:authorise'}}
    model = {'anchors': {'anchor:authorise': {'symbol_id': 'symbol:a'},
                         'anchor:refund': {'symbol_id': 'symbol:r'}},
             'symbols': {'symbol:a': {'qualified_name': 'src/s.ts::Payments.authorise'},
                         'symbol:r': {'qualified_name': 'src/s.ts::Payments.refund'}}}

    [finding] = reconciliation_findings(model, units, candidate)
    assert finding['code'] == 'UNDECIDED_MERGE'

    candidate['domains']['domain:pay']['alternatives'] = [
        {'subject_ids': ['domain:refunds'], 'explanation': 'separate lifecycle', 'claim_ids': []}]
    assert reconciliation_findings(model, units, candidate) == []

    del candidate['domains']['domain:refunds']
    candidate['domains']['domain:pay'] = _domain('domain:pay', 'activity:authorise',
                                                 'activity:refund')
    assert reconciliation_findings(model, units, candidate) == []


def test_a_repair_that_ignores_its_findings_is_recognised():
    before = {'domains': {'domain:a': {'id': 'domain:a', 'name': 'A'}},
              'claims': {'claim:1': {'id': 'claim:1', 'text': 'old'}}}
    reworded = {'domains': before['domains'],
                'claims': {'claim:2': {'id': 'claim:2', 'text': 'merged, in prose'}}}
    report = {'findings': [{'severity': 'blocking', 'subject_ids': ['domain:a']}]}

    assert Synthesis._ignored_findings(before, reworded, [], report) == ['domain:a']

    changed = {**reworded, 'domains': {'domain:b': {'id': 'domain:b', 'name': 'AB'}}}
    assert Synthesis._ignored_findings(before, changed, [], report) == []
    # A finding about a claim is answered by rewording that claim.
    about_a_claim = {'findings': [{'severity': 'blocking', 'subject_ids': ['claim:1']}]}
    assert Synthesis._ignored_findings(before, reworded, [], about_a_claim) == []


def _merging_scope():
    """Two child activities of one anchor, each with a use and a rule."""
    context = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    context['activities'] = {
        name: {'id': name, 'anchor_ids': ['anchor:pay'], 'claim_ids': [], 'rule_ids': [rule],
               'concept_ids': [], 'information_use_ids': [use]}
        for name, rule, use in (('activity:one', 'rule:one', 'use:one'),
                                ('activity:two', 'rule:two', 'use:two'))}
    context['information_uses'] = {
        use: {'id': use, 'activity_id': activity, 'concept_id': 'concept:payment',
              'resource_ids': [resource], 'access': 'creates'}
        for use, activity, resource in (('use:one', 'activity:one', 'resource:payments'),
                                        ('use:two', 'activity:two', 'resource:ledger'))}
    context['concepts'] = {'concept:payment': {'id': 'concept:payment', 'claim_ids': []}}
    context['rules'] = {rule: {'id': rule} for rule in ('rule:one', 'rule:two')}
    answer = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    answer['activities'] = {'activity:merged': {
        'id': 'activity:merged', 'anchor_ids': ['anchor:pay'], 'claim_ids': [],
        'rule_ids': ['rule:merged'], 'concept_ids': [], 'information_use_ids': []}}
    answer['rules'] = {'rule:merged': {'id': 'rule:merged'}}
    answer['claims'] = {'claim:merged': {'id': 'claim:merged', 'subject_id': 'activity:merged',
                                         'kind': 'behavior'}}
    answer['dispositions'] = [{'subject_kind': 'child_scope', 'subject_id': 'scope:child',
                               'status': 'represented',
                               'incorporated_record_ids': ['rule:one', 'rule:two']}]
    return {'scope_kind': 'reconciliation', 'context': context}, answer


def test_a_merged_activity_takes_over_the_information_uses_it_replaced():
    scope, answer = _merging_scope()

    complete = expand_reconciliation(scope, answer)

    merged = complete['activities']['activity:merged']
    assert {use['activity_id'] for use in complete['information_uses'].values()} == {
        'activity:merged'}
    assert set(merged['information_use_ids']) == {'use:one', 'use:two'}
    assert merged['concept_ids'] == ['concept:payment']


def test_child_rules_nothing_applies_after_a_merge_are_dropped():
    scope, answer = _merging_scope()

    complete = expand_reconciliation(scope, answer)

    assert set(complete['rules']) == {'rule:merged'}


def test_a_record_lists_every_claim_about_it():
    scope, answer = _merging_scope()

    complete = expand_reconciliation(scope, answer)

    assert complete['activities']['activity:merged']['claim_ids'] == ['claim:merged']


def test_claims_about_replaced_activities_move_to_the_merged_one():
    scope, answer = _merging_scope()
    scope['context']['claims'] = {'claim:one': {'id': 'claim:one', 'subject_id': 'activity:one',
                                                'kind': 'behavior'}}
    del answer['claims']['claim:merged']

    complete = expand_reconciliation(scope, answer)

    assert complete['claims']['claim:one']['subject_id'] == 'activity:merged'
    assert complete['activities']['activity:merged']['claim_ids'] == ['claim:one']


def test_a_membership_without_claims_rests_on_its_activity_claims():
    scope, answer = _merging_scope()
    answer['domains'] = {'domain:pay': _domain('domain:pay', 'activity:merged')}

    complete = expand_reconciliation(scope, answer)

    [membership] = complete['domains']['domain:pay']['activity_memberships']
    assert membership['claim_ids'] == ['claim:merged']


def test_a_returned_rule_replaces_child_rules_over_the_same_observations():
    scope, answer = _merging_scope()
    for rule_id in ('rule:one', 'rule:two'):
        scope['context']['rules'][rule_id]['observation_ids'] = ['observation:velocity']
    answer['activities'] = {}
    answer['rules'] = {'rule:velocity': {'id': 'rule:velocity',
                                         'observation_ids': ['observation:velocity']}}
    answer['dispositions'][0]['incorporated_record_ids'] = ['activity:one', 'activity:two']

    complete = expand_reconciliation(scope, answer)

    assert set(complete['rules']) == {'rule:velocity'}
    assert {activity['rule_ids'][0] for activity in complete['activities'].values()} == {
        'rule:velocity'}


def test_rules_of_different_slices_over_one_observation_must_become_one():
    units, candidate = _connected_units()
    candidate['relationships'] = {'relationship:x': {
        'from_activity_id': 'activity:refund', 'to_activity_id': 'activity:authorise'}}
    for unit, rule_id in zip(units, ('rule:a', 'rule:b')):
        rule = {'id': rule_id, 'observation_ids': ['observation:velocity']}
        unit.payload['rules'][rule_id] = rule
        candidate['rules'][rule_id] = rule

    [finding] = reconciliation_findings({}, units, candidate)

    assert finding['code'] == 'DUPLICATE_RULE'
    assert finding['subject_ids'] == ['rule:a', 'rule:b']


def test_a_retired_domains_ownerships_follow_their_own_activities():
    scope, answer = _regrouping_scope()
    context = scope['context']
    # domain:one holds a and b; its two ownerships rest on one activity each.
    context['domains']['domain:one']['activity_memberships'].append(
        {'activity_id': 'activity:b', 'role': 'supporting', 'claim_ids': []})
    context['ownerships']['ownership:two']['domain_id'] = 'domain:one'
    context['concepts']['concept:d'] = {'id': 'concept:d', 'claim_ids': []}
    context['ownerships']['ownership:two']['concept_id'] = 'concept:d'
    del context['domains']['domain:two']
    answer['domains'] = {'domain:ledger': _domain('domain:ledger', 'activity:a'),
                         'domain:payments': _domain('domain:payments', 'activity:b')}

    complete = expand_reconciliation(scope, answer)

    owners = {ownership_id: item['domain_id']
              for ownership_id, item in complete['ownerships'].items()}
    assert owners == {'ownership:one': 'domain:ledger', 'ownership:two': 'domain:payments'}


def test_rules_without_observations_are_one_rule_where_they_are_enforced_alike():
    scope, answer = _merging_scope()
    site = {'source_id': 'symbol:post', 'activity_ids': [], 'condition': None, 'evidence_ids': []}
    for rule_id in ('rule:one', 'rule:two'):
        scope['context']['rules'][rule_id].update(
            observation_ids=[], enforcement_sites=[site], evaluation_kind='data_constraint')
    answer['activities'] = {}
    answer['rules'] = {'rule:balanced': {'id': 'rule:balanced', 'observation_ids': [],
                                         'enforcement_sites': [site],
                                         'evaluation_kind': 'data_constraint'}}
    answer['dispositions'][0]['incorporated_record_ids'] = ['activity:one', 'activity:two']

    complete = expand_reconciliation(scope, answer)

    assert set(complete['rules']) == {'rule:balanced'}


def test_unmerged_rules_enforced_alike_in_different_slices_are_a_finding():
    units, candidate = _connected_units()
    candidate['relationships'] = {'relationship:x': {
        'from_activity_id': 'activity:refund', 'to_activity_id': 'activity:authorise'}}
    site = {'source_id': 'symbol:post', 'activity_ids': [], 'condition': None, 'evidence_ids': []}
    for unit, rule_id in zip(units, ('rule:a', 'rule:b')):
        rule = {'id': rule_id, 'observation_ids': [], 'enforcement_sites': [site],
                'evaluation_kind': 'data_constraint'}
        unit.payload['rules'][rule_id] = rule
        candidate['rules'][rule_id] = rule

    [finding] = reconciliation_findings({}, units, candidate)

    assert finding['code'] == 'DUPLICATE_RULE'
