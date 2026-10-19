"""How a reconciliation joins its children into one model.

SPEED does the bookkeeping of a merge: child groupings stay unless the answer
changes them, a returned domain takes over its activities, retired domains
hand their ownerships on, and relationships follow their activities. Where
children connect in ways none could see, SPEED states it and checks that the
candidate answers it.
"""
from lib.context.business_domain_synthesis import Synthesis
from lib.context.business_domain_work import (
    SEMANTIC_COLLECTIONS, Unit, _combine_records, _merge_concepts, expand_reconciliation,
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


def test_a_disposition_naming_the_answers_own_records_names_only_child_records():
    scope, answer = _merging_scope()
    answer['dispositions'][0]['incorporated_record_ids'] += ['activity:merged', 'rule:merged']

    complete = expand_reconciliation(scope, answer)

    assert complete['dispositions'][0]['incorporated_record_ids'] == ['rule:one', 'rule:two']


def test_a_kept_domain_naming_a_replaced_rule_names_its_replacement():
    scope, answer = _merging_scope()
    context = scope['context']
    for rule_id in ('rule:one', 'rule:two'):
        context['rules'][rule_id]['observation_ids'] = ['observation:velocity']
    context['domains'] = {'domain:risk': {**_domain('domain:risk', 'activity:one'),
                                          'rules': ['rule:one']}}
    answer['activities'] = {}
    answer['rules'] = {'rule:velocity': {'id': 'rule:velocity',
                                         'observation_ids': ['observation:velocity']}}
    answer['dispositions'][0]['incorporated_record_ids'] = ['activity:one', 'activity:two']

    complete = expand_reconciliation(scope, answer)

    assert set(complete['rules']) == {'rule:velocity'}
    assert complete['domains']['domain:risk']['rules'] == ['rule:velocity']


def test_concepts_of_one_name_kept_in_one_store_are_one():
    context = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    context['concepts'] = {
        name: {'id': name, 'name': 'Idempotency record', 'qualified_type_names': names,
               'symbol_ids': [], 'evidence_ids': [], 'claim_ids': []}
        for name, names in (('concept:1', ['src/pay.ts::Payments.idempotent']),
                            ('concept:2', []))}
    context['information_uses'] = {
        use: {'id': use, 'activity_id': 'activity:a', 'concept_id': concept,
              'resource_ids': ['resource:idempotent'], 'access': 'creates'}
        for use, concept in (('use:1', 'concept:1'), ('use:2', 'concept:2'))}

    assert _merge_concepts({'symbols': {}}, context) == {'concept:2': 'concept:1'}


def test_a_creating_ownership_keeps_only_activities_that_write_its_concept():
    scope, answer = _merging_scope()
    context = scope['context']
    context['activities']['activity:reader'] = {
        'id': 'activity:reader', 'anchor_ids': ['anchor:read'], 'claim_ids': [], 'rule_ids': [],
        'concept_ids': [], 'information_use_ids': ['use:read']}
    context['information_uses']['use:read'] = {
        'id': 'use:read', 'activity_id': 'activity:reader', 'concept_id': 'concept:payment',
        'resource_ids': ['resource:payments'], 'access': 'reads'}
    answer['dispositions'][0]['incorporated_record_ids'].append('activity:reader')
    answer['domains'] = {'domain:pay': _domain('domain:pay', 'activity:merged', 'activity:reader')}
    answer['ownerships'] = {'ownership:payment': {
        'id': 'ownership:payment', 'domain_id': 'domain:pay', 'concept_id': 'concept:payment',
        'kind': 'creates', 'activity_ids': ['activity:merged', 'activity:reader'],
        'information_use_ids': ['use:one', 'use:read'], 'claim_ids': [], 'evidence_ids': [],
        'unresolved_questions': []}}

    complete = expand_reconciliation(scope, answer)

    ownership = complete['ownerships']['ownership:payment']
    assert ownership['activity_ids'] == ['activity:merged']
    assert ownership['information_use_ids'] == ['use:one']


def test_a_domain_lists_the_rules_its_activities_apply():
    scope, answer = _merging_scope()
    answer['domains'] = {'domain:pay': _domain('domain:pay', 'activity:merged')}

    complete = expand_reconciliation(scope, answer)

    assert complete['domains']['domain:pay']['rules'] == ['rule:merged']


def test_a_returned_ownership_replaces_the_childrens_without_widening():
    scope, answer = _regrouping_scope()
    answer['domains'] = {'domain:merged': _domain('domain:merged', 'activity:a', 'activity:b')}
    answer['ownerships'] = {'ownership:revised': {
        'id': 'ownership:revised', 'domain_id': 'domain:merged', 'concept_id': 'concept:c',
        'kind': 'creates', 'activity_ids': ['activity:b'], 'information_use_ids': [],
        'claim_ids': [], 'evidence_ids': [], 'unresolved_questions': []}}

    complete = expand_reconciliation(scope, answer)

    assert list(complete['ownerships']) == ['ownership:revised']
    assert complete['ownerships']['ownership:revised']['activity_ids'] == ['activity:b']


def test_a_reconciliation_has_its_own_repair_limit():
    from lib.context.business_domain_synthesis import POLICY, _repair_limit

    assert _repair_limit({'scope_kind': 'reconciliation'}) == POLICY['reconciliation_repair_limit']
    assert _repair_limit({'scope_kind': 'slice'}) == POLICY['semantic_repair_limit']
    assert POLICY['reconciliation_repair_limit'] >= POLICY['semantic_repair_limit']


def test_a_bare_type_name_resolves_to_the_full_name_another_concept_gives():
    context = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    context['concepts'] = {
        name: {'id': name, 'name': label, 'qualified_type_names': names,
               'symbol_ids': [], 'evidence_ids': [], 'claim_ids': []}
        for name, label, names in (
            ('concept:1', 'Card attempt history', ['RiskRules.attempts']),
            ('concept:2', 'Card attempt history (velocity)',
             ['src/risk/rules.ts::RiskRules.attempts']))}

    assert _merge_concepts({'symbols': {}}, context) == {'concept:2': 'concept:1'}


def test_a_child_naming_a_concept_merged_by_store_names_one_it_contributed():
    units, candidate = _connected_units()
    candidate['relationships'] = {'relationship:x': {
        'from_activity_id': 'activity:refund', 'to_activity_id': 'activity:authorise'}}
    for unit, concept_id in zip(units, ('concept:1', 'concept:2')):
        unit.payload['concepts'][concept_id] = {
            'id': concept_id, 'name': 'Payment', 'qualified_type_names': [],
            'symbol_ids': [], 'evidence_ids': [], 'claim_ids': []}
        for use in unit.payload['information_uses'].values():
            use['concept_id'] = concept_id
    candidate['dispositions'] = [{'subject_kind': 'child_scope', 'subject_id': 'scope:read',
                                  'status': 'represented',
                                  'incorporated_record_ids': ['concept:1']}]

    assert reconciliation_findings({}, units, candidate) == []


def test_a_returned_domain_naming_a_merged_away_activity_holds_its_replacement():
    scope, answer = _merging_scope()
    answer['domains'] = {'domain:pay': _domain('domain:pay', 'activity:one', 'activity:two')}

    complete = expand_reconciliation(scope, answer)

    assert [membership['activity_id'] for membership
            in complete['domains']['domain:pay']['activity_memberships']] == ['activity:merged']


def test_a_rule_lists_the_activities_that_apply_it():
    scope, answer = _merging_scope()
    answer['rules']['rule:merged']['activity_ids'] = []

    complete = expand_reconciliation(scope, answer)

    assert complete['rules']['rule:merged']['activity_ids'] == ['activity:merged']


def test_rules_at_one_site_that_name_the_same_rule_are_one_whatever_their_kind():
    site = [{'source_id': 'symbol:post', 'activity_ids': [], 'condition': None, 'evidence_ids': []}]
    balanced = {'name': 'Every ledger posting is a balanced pair', 'observation_ids': [],
                'enforcement_sites': site, 'evaluation_kind': 'calculation'}
    written = {'name': 'Every ledger post writes a balanced pair', 'observation_ids': [],
               'enforcement_sites': site, 'evaluation_kind': 'data_constraint'}
    other = {'name': 'Amounts must be integer minor units', 'observation_ids': [],
             'enforcement_sites': site, 'evaluation_kind': 'predicate'}

    from lib.context.business_domain_work import _same_rule
    assert _same_rule(balanced, written)
    assert not _same_rule(balanced, other)


def test_an_activity_that_only_calls_the_writer_leaves_the_ownership():
    from lib.context.business_domain_work import _drop_delegating_owners
    model = {'anchors': {'anchor:gateway': {'symbol_id': 'symbol:gateway'},
                         'anchor:authorise': {'symbol_id': 'symbol:authorise'}},
             'traces': {'trace:gateway': {'symbol_ids': ['symbol:gateway', 'symbol:authorise']},
                        'trace:authorise': {'symbol_ids': ['symbol:authorise']}}}
    candidate = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    candidate['activities'] = {
        'activity:gateway': {'id': 'activity:gateway', 'anchor_ids': ['anchor:gateway'],
                             'trace_ids': ['trace:gateway']},
        'activity:authorise': {'id': 'activity:authorise', 'anchor_ids': ['anchor:authorise'],
                               'trace_ids': ['trace:authorise']}}
    candidate['information_uses'] = {
        f'use:{name}': {'activity_id': f'activity:{name}', 'concept_id': 'concept:payment',
                        'access': 'creates', 'effect_ids': ['effect:store'],
                        'resource_ids': ['resource:payments']}
        for name in ('gateway', 'authorise')}
    candidate['ownerships'] = {
        'ownership:gateway': {'id': 'ownership:gateway', 'concept_id': 'concept:payment',
                              'domain_id': 'domain:gateway', 'kind': 'creates',
                              'activity_ids': ['activity:gateway']},
        'ownership:lifecycle': {'id': 'ownership:lifecycle', 'concept_id': 'concept:payment',
                                'domain_id': 'domain:lifecycle', 'kind': 'creates',
                                'activity_ids': ['activity:authorise', 'activity:gateway']}}
    candidate['domains'] = {'domain:gateway': {'ownership_ids': ['ownership:gateway']}}

    _drop_delegating_owners(candidate, model)

    assert list(candidate['ownerships']) == ['ownership:lifecycle']
    assert candidate['ownerships']['ownership:lifecycle']['activity_ids'] == ['activity:authorise']
    assert candidate['domains']['domain:gateway']['ownership_ids'] == []


def test_a_rule_enforced_inside_a_called_activity_applies_to_it():
    from lib.context.business_domain_work import _attach_rules_to_enforcers
    model = {'anchors': {'anchor:gateway': {'symbol_id': 'symbol:gateway'},
                         'anchor:authorise': {'symbol_id': 'symbol:authorise'}},
             'traces': {'trace:gateway': {'symbol_ids': ['symbol:gateway', 'symbol:authorise',
                                                         'symbol:vault']},
                        'trace:authorise': {'symbol_ids': ['symbol:authorise', 'symbol:vault']}}}
    candidate = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    candidate['activities'] = {
        'activity:gateway': {'anchor_ids': ['anchor:gateway'], 'trace_ids': ['trace:gateway'],
                             'rule_ids': ['rule:last4']},
        'activity:authorise': {'anchor_ids': ['anchor:authorise'],
                               'trace_ids': ['trace:authorise'], 'rule_ids': []}}
    candidate['rules'] = {'rule:last4': {'enforcement_sites': [{'source_id': 'symbol:vault'}]}}

    _attach_rules_to_enforcers(candidate, model)

    assert candidate['activities']['activity:authorise']['rule_ids'] == ['rule:last4']


def test_claims_about_a_combined_ownership_name_the_one_it_became():
    scope, answer = _regrouping_scope()
    answer['domains'] = {'domain:merged': _domain('domain:merged', 'activity:a', 'activity:b')}
    answer['ownerships'] = {
        name: {'id': name, 'domain_id': 'domain:merged', 'concept_id': 'concept:c', 'kind': kind,
               'activity_ids': [activity], 'information_use_ids': [], 'claim_ids': [],
               'evidence_ids': [], 'unresolved_questions': []}
        for name, kind, activity in (('ownership:x', 'creates', 'activity:a'),
                                     ('ownership:y', 'maintains', 'activity:b'))}
    answer['claims'] = {'claim:y': {'id': 'claim:y', 'subject_id': 'ownership:y',
                                    'kind': 'ownership'}}

    complete = expand_reconciliation(scope, answer)

    assert list(complete['ownerships']) == ['ownership:x']
    assert complete['claims']['claim:y']['subject_id'] == 'ownership:x'


def test_an_ownership_cites_only_its_own_activities_uses_and_creators_create():
    from lib.context.business_domain_work import _keep_writers
    candidate = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    candidate['information_uses'] = {
        use: {'activity_id': activity, 'concept_id': 'concept:entry', 'access': access}
        for use, activity, access in (('use:post', 'activity:post', 'creates'),
                                      ('use:reset', 'activity:reset', 'deletes'),
                                      ('use:authorise', 'activity:authorise', 'creates'))}
    candidate['ownerships'] = {'ownership:entries': {
        'concept_id': 'concept:entry', 'kind': 'creates',
        'activity_ids': ['activity:post', 'activity:reset'],
        'information_use_ids': ['use:post', 'use:reset', 'use:authorise']}}

    _keep_writers(candidate)

    ownership = candidate['ownerships']['ownership:entries']
    assert ownership['activity_ids'] == ['activity:post']
    assert ownership['information_use_ids'] == ['use:post']


def test_a_restated_claim_replaces_the_childs_claim_of_that_kind():
    scope, answer = _regrouping_scope()
    scope['context']['claims']['claim:boundary'] = {
        'id': 'claim:boundary', 'subject_id': 'domain:three', 'kind': 'boundary',
        'text': 'The gateway is not in this scope.'}
    scope['context']['domains']['domain:three']['claim_ids'] = ['claim:boundary']
    answer['claims'] = {'claim:revised': {'id': 'claim:revised', 'subject_id': 'domain:three',
                                          'kind': 'boundary', 'text': 'The gateway calls it.'}}

    complete = expand_reconciliation(scope, answer)

    assert 'claim:boundary' not in complete['claims']
    assert complete['domains']['domain:three']['claim_ids'] == ['claim:revised']


def test_an_ownership_drops_the_uses_of_an_activity_that_only_delegated():
    from lib.context.business_domain_work import _drop_delegating_owners, _keep_writers
    model = {'anchors': {'anchor:gateway': {'symbol_id': 'symbol:gateway'},
                         'anchor:authorise': {'symbol_id': 'symbol:authorise'}},
             'traces': {'trace:gateway': {'symbol_ids': ['symbol:gateway', 'symbol:authorise']},
                        'trace:authorise': {'symbol_ids': ['symbol:authorise']}}}
    candidate = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    candidate['activities'] = {
        name: {'anchor_ids': [f'anchor:{name}'], 'trace_ids': [f'trace:{name}']}
        for name in ('gateway', 'authorise')}
    candidate['activities'] = {f'activity:{name}': value
                               for name, value in candidate['activities'].items()}
    candidate['information_uses'] = {
        f'use:{name}': {'activity_id': f'activity:{name}', 'concept_id': 'concept:payment',
                        'access': 'creates', 'effect_ids': ['effect:store'],
                        'resource_ids': ['resource:payments']}
        for name in ('gateway', 'authorise')}
    candidate['ownerships'] = {'ownership:payment': {
        'concept_id': 'concept:payment', 'domain_id': 'domain:pay', 'kind': 'creates',
        'activity_ids': ['activity:authorise', 'activity:gateway'],
        'information_use_ids': ['use:authorise', 'use:gateway']}}

    _drop_delegating_owners(candidate, model)
    _keep_writers(candidate)

    ownership = candidate['ownerships']['ownership:payment']
    assert ownership['activity_ids'] == ['activity:authorise']
    assert ownership['information_use_ids'] == ['use:authorise']


def test_copies_of_one_rule_from_different_children_become_one():
    from lib.context.business_domain_work import _merge_duplicate_rules
    site = [{'source_id': 'symbol:post', 'activity_ids': [], 'condition': None, 'evidence_ids': []}]
    candidate = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    candidate['rules'] = {
        rule_id: {'name': 'Every ledger posting is a balanced pair', 'observation_ids': [],
                  'enforcement_sites': site, 'evaluation_kind': 'data_constraint',
                  'activity_ids': activities, 'evidence_ids': [f'ev:{rule_id[-1]}']}
        for rule_id, activities in (('rule:a', ['activity:post', 'activity:pay']),
                                    ('rule:b', ['activity:refund']))}
    candidate['activities'] = {'activity:refund': {'rule_ids': ['rule:b']}}
    scope = {'coverage_manifests': [{'child_scope_id': 'scope:1', 'contributed_record_ids': ['rule:a']},
                                    {'child_scope_id': 'scope:2', 'contributed_record_ids': ['rule:b']}]}

    _merge_duplicate_rules(candidate, scope)

    assert list(candidate['rules']) == ['rule:a']
    assert candidate['rules']['rule:a']['activity_ids'] == ['activity:post', 'activity:pay',
                                                           'activity:refund']
    assert candidate['activities']['activity:refund']['rule_ids'] == ['rule:a']


def test_a_direct_call_between_domains_is_recorded_once_and_not_through_a_callee():
    from lib.context.business_domain_work import _link_direct_calls
    model = {'anchors': {f'anchor:{name}': {'symbol_id': f'symbol:{name}'}
                         for name in ('gateway', 'authorise', 'post')},
             'traces': {'trace:gateway': {'symbol_ids': ['symbol:gateway', 'symbol:authorise',
                                                         'symbol:post']},
                        'trace:authorise': {'symbol_ids': ['symbol:authorise', 'symbol:post']},
                        'trace:post': {'symbol_ids': ['symbol:post']}},
             'edges': {
                 'edge:1': {'kind': 'calls', 'from_ref': {'id': 'symbol:gateway', 'kind': 'symbol'},
                            'to_ref': {'id': 'symbol:authorise', 'kind': 'symbol'},
                            'evidence_ids': ['ev:call']},
                 'edge:2': {'kind': 'calls', 'from_ref': {'id': 'symbol:authorise', 'kind': 'symbol'},
                            'to_ref': {'id': 'symbol:post', 'kind': 'symbol'},
                            'evidence_ids': ['ev:post']}}}
    candidate = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    candidate['activities'] = {f'activity:{name}': {'anchor_ids': [f'anchor:{name}'],
                                                    'trace_ids': [f'trace:{name}']}
                               for name in ('gateway', 'authorise', 'post')}
    candidate['domains'] = {
        'domain:risk': {'activity_memberships': [{'activity_id': 'activity:gateway', 'role': 'primary'}]},
        'domain:pay': {'activity_memberships': [{'activity_id': 'activity:authorise', 'role': 'primary'},
                                                {'activity_id': 'activity:post', 'role': 'primary'}]}}

    _link_direct_calls(candidate, model, {'ev:call', 'ev:post'})

    [relationship] = candidate['relationships'].values()
    assert (relationship['from_activity_id'], relationship['to_activity_id']) == (
        'activity:gateway', 'activity:authorise')
    assert relationship['kind'] == 'requests_action_from'


def test_a_reader_of_what_another_domain_writes_is_linked_to_the_writer():
    from lib.context.business_domain_work import _link_information_flow
    candidate = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    candidate['activities'] = {name: {'trace_ids': [f'trace:{name}']}
                               for name in ('activity:total', 'activity:capture')}
    candidate['domains'] = {
        'domain:ledger': {'activity_memberships': [{'activity_id': 'activity:total', 'role': 'primary'}]},
        'domain:pay': {'activity_memberships': [{'activity_id': 'activity:capture', 'role': 'primary'}]}}
    candidate['information_uses'] = {
        'use:read': {'activity_id': 'activity:total', 'access': 'reads',
                     'resource_ids': ['resource:entries'], 'evidence_ids': ['ev:read']},
        'use:write': {'activity_id': 'activity:capture', 'access': 'creates',
                      'resource_ids': ['resource:entries'], 'evidence_ids': ['ev:write']}}

    _link_information_flow(candidate, {'ev:read', 'ev:write'})

    [relationship] = candidate['relationships'].values()
    assert (relationship['from_activity_id'], relationship['to_activity_id'], relationship['kind']) == (
        'activity:total', 'activity:capture', 'uses_information_from')


def test_a_documented_rule_is_replaced_by_the_returned_rule_of_its_name():
    scope, answer = _merging_scope()
    for rule_id in ('rule:one', 'rule:two'):
        scope['context']['rules'][rule_id].update(
            name='Refund within the captured amount', observation_ids=[], enforcement_sites=[])
    answer['activities'] = {}
    answer['rules'] = {'rule:refund': {'id': 'rule:refund', 'name': 'Refund within the captured amount',
                                       'observation_ids': [], 'enforcement_sites': []}}
    answer['dispositions'][0]['incorporated_record_ids'] = ['activity:one', 'activity:two']

    complete = expand_reconciliation(scope, answer)

    assert set(complete['rules']) == {'rule:refund'}


def test_a_returned_record_keeps_only_the_claims_it_lists():
    scope, answer = _regrouping_scope()
    scope['context']['claims']['claim:stale'] = {
        'id': 'claim:stale', 'subject_id': 'domain:three', 'kind': 'scope_note',
        'text': 'Capture is not modelled in this slice.'}
    returned = _domain('domain:three', 'activity:c')
    returned['claim_ids'] = ['claim:three']
    answer['domains'] = {'domain:three': returned}

    complete = expand_reconciliation(scope, answer)

    assert 'claim:stale' not in complete['claims']
    assert complete['domains']['domain:three']['claim_ids'] == ['claim:three']


def test_a_segment_names_only_its_own_traces_on_a_shared_effect():
    from lib.context.business_domain_work import segment_view
    model = {
        'symbols': {'symbol:a': {'evidence_ids': []}, 'symbol:b': {'evidence_ids': []}},
        'edges': {'edge:ab': {'from_ref': {'id': 'symbol:a', 'kind': 'symbol'},
                              'to_ref': {'id': 'symbol:b', 'kind': 'symbol'}, 'evidence_ids': []}},
        'traces': {
            'trace:mine': {'id': 'trace:mine', 'anchor_id': 'anchor:mine', 'symbol_ids': ['symbol:a', 'symbol:b'],
                           'edge_ids': ['edge:ab'], 'frontier_ids': [], 'obligation_ids': []},
            'trace:other': {'id': 'trace:other', 'anchor_id': 'anchor:other', 'symbol_ids': ['symbol:a'],
                            'edge_ids': ['edge:ab'], 'frontier_ids': [], 'obligation_ids': []}},
        'trace_obligations': {},
        'effects': {'effect:write': {'id': 'effect:write', 'edge_id': 'edge:ab',
                                     'trace_ids': ['trace:mine', 'trace:other']}}}

    view, _ = segment_view(model, 'anchor:mine', ['symbol:a', 'symbol:b'])

    assert view['effects']['effect:write']['trace_ids'] == ['trace:mine']
    assert model['effects']['effect:write']['trace_ids'] == ['trace:mine', 'trace:other']


def test_entry_points_sharing_code_are_packed_together():
    from lib.context.business_domain_work import _affinity_pack
    code = {'anchor:1': {'owner'}, 'anchor:2': {'vet'}, 'anchor:3': {'owner'}, 'anchor:4': {'vet'}}

    def build(group):
        return sorted(group)

    groups = [group for group, _ in _affinity_pack(
        code, build, lambda built: len(built) <= 2, lambda anchor: code[anchor])]

    # In canonical order 1 and 2 would share a slice; by shared code, 1 joins 3.
    assert groups == [['anchor:1', 'anchor:3'], ['anchor:2', 'anchor:4']]


def test_one_record_two_slices_word_differently_is_supplied_once():
    # An ID comes from what identifies a record, so slices that reach the same
    # relationship give it the same ID whatever words they explain it in.
    first = {'id': 'rule_relationship:x', 'from_observation_id': 'observation:a',
             'to_observation_id': 'observation:b', 'kind': 'equivalent',
             'explanation': 'Both checks decide insert versus update.',
             'evidence_ids': ['ev:1', 'ev:2'], 'verification': 'inferred'}
    second = {**first, 'explanation': 'isNew() is id == null, so both checks agree.',
              'evidence_ids': ['ev:3', 'ev:1']}

    combined = _combine_records(first, second)

    assert combined['explanation'] == first['explanation']
    assert combined['evidence_ids'] == ['ev:1', 'ev:2', 'ev:3']
    verified = {**second, 'verification': 'verified'}
    assert _combine_records(first, verified)['explanation'] == second['explanation']
    assert _combine_records(first, dict(first)) == first


def test_concepts_naming_one_java_class_are_supplied_as_one():
    # Java names a class by package, the symbol table by source file.
    model = {'symbols': {'symbol:o': {
        'qualified_name': 'src/main/java/org/acme/model/Owner.java::Owner'}}}
    context = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    context['concepts'] = {
        name: {'id': name, 'qualified_type_names': names, 'symbol_ids': [],
               'evidence_ids': [], 'claim_ids': []}
        for name, names in (('concept:1', ['org.acme.model.Owner']),
                            ('concept:2', ['org.acme.model.Owner']),
                            ('concept:3', ['src/main/java/org/acme/model/Owner.java::Owner']),
                            ('concept:4', ['Owner']),
                            ('concept:5', ['org.acme.dto.OwnerDto']))}

    aliases = _merge_concepts(model, context)

    assert aliases == {'concept:2': 'concept:1', 'concept:3': 'concept:1',
                       'concept:4': 'concept:1'}
    assert set(context['concepts']) == {'concept:1', 'concept:5'}


def test_a_concept_named_without_a_type_is_the_typed_concept_of_its_name():
    context = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    context['concepts'] = {
        name: {'id': name, 'name': label, 'qualified_type_names': names, 'symbol_ids': [],
               'evidence_ids': [], 'claim_ids': []}
        for name, label, names in (('concept:1', 'Visit', ['org.acme.Visit']),
                                   ('concept:2', 'Visit', []),
                                   ('concept:3', 'Order', ['a.Order']),
                                   ('concept:4', 'Order', ['b.Order']),
                                   ('concept:5', 'Order', []))}

    # Where two typed concepts share the name, the untyped one could be either.
    assert _merge_concepts({'symbols': {}}, context) == {'concept:2': 'concept:1'}


def test_a_returned_rule_naming_an_activity_is_listed_back_by_it():
    scope, answer = _merging_scope()
    answer['activities']['activity:merged']['rule_ids'] = []
    answer['rules']['rule:merged']['activity_ids'] = ['activity:merged']

    complete = expand_reconciliation(scope, answer)

    assert complete['activities']['activity:merged']['rule_ids'] == ['rule:merged']


def test_a_returned_activity_that_drops_a_carried_rule_is_unlinked_from_it():
    scope, answer = _merging_scope()
    scope['context']['rules']['rule:kept'] = {'id': 'rule:kept', 'activity_ids': ['activity:merged']}
    answer['dispositions'][0]['incorporated_record_ids'] = ['rule:one', 'rule:two']

    complete = expand_reconciliation(scope, answer)

    assert 'rule:kept' not in complete['activities']['activity:merged']['rule_ids']
    if 'rule:kept' in complete['rules']:
        assert complete['rules']['rule:kept']['activity_ids'] == []


def test_a_domain_does_not_gain_a_technical_rule_it_leaves_out():
    scope, answer = _merging_scope()
    answer['rules']['rule:merged']['category'] = 'technical'
    answer['domains'] = {'domain:pay': {**_domain('domain:pay', 'activity:merged'), 'rules': []}}

    complete = expand_reconciliation(scope, answer)

    assert complete['domains']['domain:pay']['rules'] == []


def test_operations_one_contract_documents_are_owned_by_their_implementations():
    from lib.context.business_domain_work import _owner

    def anchor(implementation):
        representations = [{'role': 'contract', 'symbol_id': 'symbol:api'}]
        if implementation:
            representations.append({'role': 'implementation', 'symbol_id': implementation})
        return {'symbol_id': 'symbol:api', 'representations': representations}
    model = {'symbols': {'symbol:api': {'qualified_name': 'src/openapi.yml::addOwner'},
                         'symbol:o': {'qualified_name': 'src/Owners.java::Owners.add(Owner)'},
                         'symbol:v': {'qualified_name': 'src/Vets.java::Vets.add(Vet)'}},
             'anchors': {'anchor:o': anchor('symbol:o'), 'anchor:v': anchor('symbol:v'),
                         'anchor:x': anchor(None)}}

    assert _owner(model, 'anchor:o') == 'src/Owners.java::Owners'
    assert _owner(model, 'anchor:v') == 'src/Vets.java::Vets'
    # A contract alone shows no owner: every documented operation shares it.
    assert _owner(model, 'anchor:x') is None


def _contract_model(expression):
    def binding(binding_id, name, source, text, evidence):
        return {'id': binding_id, 'name': name, 'direction': 'output', 'expression': text,
                'source': {'kind': 'symbol', 'id': source}, 'evidence_ids': [evidence]}
    return {
        'anchors': {'anchor:add': {
            'operation': {'method': 'post', 'path': '/owners'},
            'representations': [{'id': 'rep:api', 'role': 'contract', 'symbol_id': 'symbol:api'},
                                {'id': 'rep:code', 'role': 'implementation', 'symbol_id': 'symbol:code'}],
            'correspondences': [{'state': 'resolved', 'from_representation': 'rep:api',
                                 'to_representations': ['rep:code']}]}},
        'bindings': {
            'binding:200': binding('binding:200', 'response:200', 'symbol:api', 'Created.', 'ev:api'),
            'binding:ret': binding('binding:ret', 'output@1', 'symbol:code', expression, 'ev:code')}}


def _contract_candidate(*claims):
    candidate = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    candidate['activities'] = {'activity:add': {'id': 'activity:add', 'anchor_ids': ['anchor:add'],
                                                'trace_ids': ['trace:add'], 'claim_ids': []}}
    candidate['claims'] = {claim['id']: claim for claim in claims}
    return candidate


def test_a_status_the_code_returns_and_the_contract_omits_is_stated():
    from lib.context.business_domain_work import _contract_status_conflicts
    candidate = _contract_candidate()

    _contract_status_conflicts(candidate, _contract_model(
        'new ResponseEntity<>(dto, headers, HttpStatus.CREATED)'), {'ev:api', 'ev:code'})

    [claim] = candidate['claims'].values()
    assert claim['subject_id'] == 'activity:add' and claim['kind'] == 'conflict'
    assert 'POST /owners' in claim['text'] and '201' in claim['text']
    assert claim['evidence_ids'] == ['ev:api', 'ev:code']


def test_a_status_conflict_a_child_recorded_is_not_stated_again():
    from lib.context.business_domain_work import _contract_status_conflicts
    recorded = {'id': 'claim:child', 'subject_id': 'activity:add', 'kind': 'conflict',
                'text': 'The contract says 200 but the controller returns 201.'}
    candidate = _contract_candidate(recorded)

    _contract_status_conflicts(candidate, _contract_model('ResponseEntity.created(uri)'),
                               {'ev:api', 'ev:code'})

    assert list(candidate['claims']) == ['claim:child']


def test_declared_or_unknown_statuses_and_uncitable_evidence_state_nothing():
    from lib.context.business_domain_work import _contract_status_conflicts
    for expression, citable in (('new ResponseEntity<>(HttpStatus.OK)', {'ev:api', 'ev:code'}),
                                ('new ResponseEntity<>(HttpStatus.NO_SUCH_NAME)', {'ev:api', 'ev:code'}),
                                ('new ResponseEntity<>(HttpStatus.CREATED)', {'ev:code'})):
        candidate = _contract_candidate()
        _contract_status_conflicts(candidate, _contract_model(expression), citable)
        assert candidate['claims'] == {}


def test_child_prose_citing_its_own_request_aliases_reads_by_name(monkeypatch):
    # A child's answer cites records by the aliases of its own request; in the
    # parent request the same alias would name a different record.
    from lib.context import business_domain_synthesis
    from lib.context.business_domain_work import _decode_prose_aliases

    class Projection:
        def __init__(self, scope):
            self.canonical_ids = {'_ref:0': 'trace:add', '_ref:1': 'ev:1', '_ref:2': 'rule:r'}
    monkeypatch.setattr(business_domain_synthesis, 'ProviderProjection', Projection)
    payload = {collection: {} for collection in SEMANTIC_COLLECTIONS}
    payload['activities'] = {'activity:add': {'id': 'activity:add', 'name': 'Add pet',
                                              'trace_ids': ['trace:add']}}
    payload['rules'] = {'rule:r': {'id': 'rule:r', 'name': 'Pet needs an owner',
                                   'description': 'See _ref:2, _ref:1 and trace _ref:0; _ref:7 too.'}}
    scope = {'scope_id': 'scope:child', 'context': {'evidence': {'ev:1': {
        'locator': {'path': 'src/Pets.java', 'start_line': 12}}}}}

    decoded = _decode_prose_aliases(Unit(scope, payload, {}))

    assert decoded.payload['rules']['rule:r']['description'] == (
        'See "Pet needs an owner", src/Pets.java:12 and trace the trace of "Add pet"; '
        'a record of child scope scope:child too.')
    assert decoded.payload['activities'] == payload['activities']
