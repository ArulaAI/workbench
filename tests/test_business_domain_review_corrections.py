"""Tests for reviewed corrections to rules, use cases and contexts (speed discover domains --review)."""
import copy
import json

from lib.context.business_domain_cli import main
from lib.context.business_domain_review import replay
from lib.context.business_domain_schema import atomic_write, read_json, record, validate, validate_references
from lib.context.business_domains import discover, load, paths
from tests.business_domains.provider_fixture import PassingProvider, write_service


def published(tmp_path):
    """A published model with two rules on its first use case, so rule corrections have something to act on."""
    write_service(tmp_path)
    model, _ = discover(tmp_path, provider=PassingProvider())
    assert model is not None
    activity_id = sorted(model['activities'])[0]
    domain = next(domain for domain in model['domains'].values()
                  if any(item['activity_id'] == activity_id for item in domain['activity_memberships']))
    for number in (1, 2):
        rule_id = f'rule:test{number}'
        model['rules'][rule_id] = record(
            'Rule', id=rule_id, name=f'Rule {number}', description='The owner must exist.',
            category='validation', activity_ids=[activity_id], concept_ids=[], preconditions=[],
            predicate_or_formula='owner == null', outcome='HTTP 404', enforcement_sites=[], evidence_ids=[],
            basis=['source_observed'], enforcement_status='declared_only', support='partial', conflicts=[],
            unresolved_questions=[f'Question {number}'], observation_ids=[], parameter_binding_ids=[],
            dependency_ids=[], evaluation_kind='predicate')
        model['activities'][activity_id]['rule_ids'].append(rule_id)
        domain['rules'].append(rule_id)
    validate(model, 'DomainArtifact')
    validate_references(model)
    atomic_write(paths(tmp_path)['model'], model)
    return model


def run_review(tmp_path, decisions, capsys):
    path = tmp_path / 'review.json'
    path.write_text(json.dumps({'author': 'reviewer@example.com', 'decisions': decisions}))
    code = main(['--root', str(tmp_path), '--review', str(path)])
    return code, json.loads(capsys.readouterr().out)


def test_a_rule_correction_changes_its_text_and_records_who_reviewed_it(tmp_path, capsys):
    model = published(tmp_path)
    rule_id = sorted(model['rules'])[0]
    code, result = run_review(tmp_path, [{
        'explanation': 'The check is in OwnerRestController.java:111.',
        'operation': {'operation': 'correct_rule', 'rule_id': rule_id,
                      'set': {'name': 'Owner must exist', 'outcome': 'HTTP 404 when the owner is missing.'}}}], capsys)
    assert code == 0 and result['applied'] == 1
    corrected, _ = load(tmp_path)
    rule = corrected['rules'][rule_id]
    assert (rule['name'], rule['outcome']) == ('Owner must exist', 'HTTP 404 when the owner is missing.')
    assert 'user_asserted' in rule['basis']
    review_evidence = [corrected['evidence'][eid] for eid in rule['evidence_ids']
                       if corrected['evidence'][eid]['source_kind'] == 'user_review']
    assert review_evidence and 'OwnerRestController.java:111' in review_evidence[0]['excerpt']
    assert corrected['build_id'] != model['build_id']
    validate(corrected, 'DomainArtifact')
    validate_references(corrected)


def test_merged_rules_leave_one_rule_and_no_dangling_references(tmp_path, capsys):
    model = published(tmp_path)
    keep, drop = sorted(model['rules'])[:2]
    code, _ = run_review(tmp_path, [{
        'explanation': 'Both rules describe the same check.',
        'operation': {'operation': 'merge_rules', 'rule_ids': [keep, drop]}}], capsys)
    assert code == 0
    merged, _ = load(tmp_path)
    assert drop not in merged['rules'] and keep in merged['rules']
    text = json.dumps({key: value for key, value in merged.items() if key != 'identity_changes'})
    assert f'"{drop}"' not in text
    validate_references(merged)


def test_use_case_and_context_text_can_be_corrected(tmp_path, capsys):
    model = published(tmp_path)
    activity_id = sorted(model['activities'])[0]
    domain_id = sorted(model['domains'])[0]
    code, _ = run_review(tmp_path, [
        {'explanation': 'Describe the configured Spring Data path.',
         'operation': {'operation': 'correct_activity', 'activity_id': activity_id,
                       'set': {'description': 'Deletes the owner and, by cascade, its pets and their visits.'}}},
        {'explanation': 'Plain wording.',
         'operation': {'operation': 'correct_domain', 'domain_id': domain_id,
                       'set': {'boundary_rationale': 'Owners, pets and visits are created and changed together.'}}}],
        capsys)
    assert code == 0
    corrected, _ = load(tmp_path)
    assert corrected['activities'][activity_id]['description'].startswith('Deletes the owner')
    assert corrected['domains'][domain_id]['boundary_rationale'].startswith('Owners, pets and visits')


def test_the_same_review_file_is_applied_only_once(tmp_path, capsys):
    model = published(tmp_path)
    decision = {'explanation': 'Rename for clarity.',
                'operation': {'operation': 'correct_rule', 'rule_id': sorted(model['rules'])[0],
                              'set': {'name': 'Clear name'}}}
    assert run_review(tmp_path, [decision], capsys)[1]['applied'] == 1
    again = run_review(tmp_path, [decision], capsys)[1]
    assert (again['applied'], again['skipped']) == (0, 1)


def test_a_correction_for_an_unknown_rule_is_refused(tmp_path, capsys):
    published(tmp_path)
    code, result = run_review(tmp_path, [{
        'explanation': 'x', 'operation': {'operation': 'correct_rule', 'rule_id': 'rule:missing',
                                          'set': {'name': 'x'}}}], capsys)
    assert code == 1 and result['error']['code'] == 'REVIEW_CONFLICT'


def test_saved_corrections_are_replayed_onto_a_rebuilt_model(tmp_path, capsys):
    model = published(tmp_path)
    rule_id = sorted(model['rules'])[0]
    run_review(tmp_path, [{'explanation': 'Reviewed name.',
                           'operation': {'operation': 'correct_rule', 'rule_id': rule_id,
                                         'set': {'name': 'Reviewed name'}}}], capsys)
    overrides = read_json(paths(tmp_path)['overrides'])
    rebuilt = replay(tmp_path, copy.deepcopy(model), overrides, previous=model)
    assert rebuilt['rules'][rule_id]['name'] == 'Reviewed name'


def test_a_rule_correction_can_cite_source_lines_and_replace_where_it_is_enforced(tmp_path, capsys):
    model = published(tmp_path)
    rule_id = sorted(model['rules'])[0]
    source_id = sorted(model['symbols'])[0]
    span = {'path': 'service.py', 'start_line': 1, 'end_line': 2}
    code, result = run_review(tmp_path, [{
        'explanation': 'The check is on the first two lines of service.py.',
        'operation': {'operation': 'correct_rule', 'rule_id': rule_id,
                      'set': {'enforcement_sites': [{'source_id': source_id, 'condition': 'owner == null',
                                                     'cite': [span]}]}}}], capsys)
    assert code == 0 and result['applied'] == 1
    corrected, _ = load(tmp_path)
    rule = corrected['rules'][rule_id]
    [site] = rule['enforcement_sites']
    [eid] = site['evidence_ids']
    evidence = corrected['evidence'][eid]
    lines = (tmp_path / 'service.py').read_text().splitlines()
    assert evidence['locator']['path'] == 'service.py' and evidence['locator']['start_line'] == 1
    assert evidence['excerpt'] == '\n'.join(lines[:2])
    assert eid in rule['evidence_ids'] and site['source_id'] == source_id
    validate(corrected, 'DomainArtifact')
    validate_references(corrected)


def test_citing_lines_outside_the_file_is_refused(tmp_path, capsys):
    model = published(tmp_path)
    code, result = run_review(tmp_path, [{
        'explanation': 'Cites a line that does not exist.',
        'operation': {'operation': 'correct_rule', 'rule_id': sorted(model['rules'])[0],
                      'cite': [{'path': 'service.py', 'start_line': 1, 'end_line': 9999}]}}], capsys)
    assert code == 1 and result['error']['code'] == 'REVIEW_CONFLICT'
    unchanged, _ = load(tmp_path)
    assert unchanged['build_id'] == model['build_id']


def test_a_context_correction_rewrites_its_questions_and_alternatives(tmp_path, capsys):
    model = published(tmp_path)
    domain_id = sorted(model['domains'])[0]
    model['domains'][domain_id]['alternatives'] = [{'claim_ids': [], 'explanation': 'Old name.', 'subject_ids': []}]
    atomic_write(paths(tmp_path)['model'], model)
    code, _ = run_review(tmp_path, [{
        'explanation': 'The merged context was renamed.',
        'operation': {'operation': 'correct_domain', 'domain_id': domain_id,
                      'set': {'unresolved_questions': [], 'alternatives': ['New name.']}}}], capsys)
    assert code == 0
    corrected, _ = load(tmp_path)
    domain = corrected['domains'][domain_id]
    assert domain['unresolved_questions'] == []
    assert domain['alternatives'] == [{'claim_ids': [], 'explanation': 'New name.', 'subject_ids': []}]
