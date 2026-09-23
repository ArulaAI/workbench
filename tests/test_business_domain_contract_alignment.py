"""The runtime contract may not drift farther from the normative contract."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_agent_definitions_match_the_normative_contract():
    for role in ('synthesis', 'verification'):
        runtime = (
            ROOT/'agents'/f'business-domain-{role}.md').read_text()
        normative = (
            ROOT/'specs/tech/contracts/agents'/
            f'business-domain-{role}.md').read_text()

        assert runtime == normative


def test_runtime_limits_and_defaults_match_the_normative_contract():
    normative = json.loads(
        (ROOT/'specs/tech/contracts/business-domain-artifacts.schema.json').read_text())
    runtime = json.loads(
        (ROOT/'lib/context/business_domain_artifacts.schema.json').read_text())
    assert runtime['$defs']['Limits'] == normative['$defs']['Limits']
    assert (runtime['$defs']['ScopeDisposition']
            == normative['$defs']['ScopeDisposition'])

    from lib.context.business_domain_schema import DEFAULTS, limits, validate
    assert DEFAULTS == {
        'max_trace_depth':6,
        'max_symbols_per_activity':200,
        'max_request_input_tokens':2_000_000,
        'max_request_output_tokens':128_000,
        'max_build_input_tokens':8_000_000,
        'max_build_output_tokens':512_000,
        'provider_concurrency':2,
        'deadline_seconds':3_600,
        'max_source_bytes':500_000,
        'max_artifact_bytes':25_000_000,
        'cache_retention_days':30,
        'snapshot_manifest':None,
    }
    counters = limits(DEFAULTS)
    validate(counters, 'Limits')
    assert counters['token_estimator'] == (
        'tiktoken:o200k_base+60-percent-margin+512-framing')
    assert counters['provider_context_tokens'] is None
    assert counters['provider_max_output_tokens'] is None
    assert counters['effective_request_input_tokens'] == 2_000_000
    assert counters['effective_request_output_tokens'] == 128_000
    assert counters['semantic_units_total'] == 0
    assert counters['semantic_units_validated'] == 0
    assert counters['semantic_units_pending'] == 0
    assert counters['completion_input_tokens_reserved'] == 0
    assert counters['completion_output_tokens_reserved'] == 0


@pytest.mark.parametrize('status', ['excluded', 'unresolved'])
def test_nonrepresented_disposition_requires_evidence(status):
    schema = json.loads(
        (ROOT/'lib/context/business_domain_artifacts.schema.json').read_text())
    validator = Draft202012Validator({
        '$schema': schema['$schema'], '$defs': schema['$defs'],
        '$ref': '#/$defs/ScopeDisposition',
    })
    disposition = {
        'id':'disposition:fixture', 'subject_kind':'anchor',
        'subject_id':'anchor:fixture', 'status':status, 'activity_ids':[],
        'incorporated_record_ids':[], 'reason':'Fixture explanation.',
        'evidence_ids':[],
    }

    with pytest.raises(ValidationError):
        validator.validate(disposition)


def test_normative_contract_examples_and_runtime_alignment():
    result = subprocess.run(
        [sys.executable, str(ROOT / 'specs/tech/contracts/check_contracts.py')],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith('PASS: schema, ')


def test_normative_contract_rejects_incomplete_resolved_http_anchor():
    schema = json.loads(
        (ROOT/'specs/tech/contracts/business-domain-artifacts.schema.json').read_text())
    validator = Draft202012Validator({
        '$schema': schema['$schema'], '$defs': schema['$defs'],
        '$ref': '#/$defs/Anchor',
    })
    anchor = {
        'id':'anchor:fixture', 'kind':'http', 'source_id':'resource:fixture',
        'symbol_id':None,
        'operation': {
            'protocol':'http', 'service_resource_id':None, 'name':'fixture',
            'method':None, 'path':None, 'version':None,
        },
        'status':'candidate', 'evidence_ids':[], 'resolution':'resolved',
        'reason':None,
    }

    with pytest.raises(ValidationError):
        validator.validate(anchor)


def test_trace_contract_requires_explicit_traversal_completion():
    schemas = [
        json.loads((ROOT/'lib/context/business_domain_artifacts.schema.json').read_text()),
        json.loads((ROOT/'specs/tech/contracts/business-domain-artifacts.schema.json').read_text()),
    ]
    trace = {
        'id':'trace:fixture', 'anchor_id':'anchor:fixture', 'symbol_ids':[],
        'edge_ids':[], 'obligation_ids':[], 'frontier_ids':[], 'stop_reasons':[],
        'traversal_complete':True, 'ui_interaction':None, 'evidence_ids':[],
        'resolution':'unresolved', 'reason':'A semantic obligation remains open.',
    }
    for schema in schemas:
        definition = schema['$defs']['Trace']
        assert definition['properties']['traversal_complete'] == {'type':'boolean'}
        assert 'traversal_complete' in definition['required']
        validator = Draft202012Validator({
            '$schema':schema['$schema'], '$defs':schema['$defs'], '$ref':'#/$defs/Trace',
        })
        validator.validate(trace)
        incomplete = dict(trace)
        incomplete.pop('traversal_complete')
        with pytest.raises(ValidationError):
            validator.validate(incomplete)

        resolved = dict(trace, resolution='resolved', reason=None)
        validator.validate(resolved)
        validator.validate(dict(trace, traversal_complete=False))
        validator.validate(dict(trace, resolution='ambiguous', reason='Multiple targets remain.'))

        invalid = [
            dict(resolved, traversal_complete=False),
            dict(resolved, reason='Traversal claims a resolved reason.'),
            dict(trace, reason=None),
            dict(trace, resolution='ambiguous', reason=''),
            dict(trace, traversal_complete=False, resolution='ambiguous',
                 reason='Multiple targets remain.'),
        ]
        for contradictory in invalid:
            with pytest.raises(ValidationError):
                validator.validate(contradictory)


def test_graph_input_contract_requires_capability_records():
    contracts = [
        (ROOT/'lib/context/business_domain_artifacts.schema.json', 'PacketContext'),
        (ROOT/'specs/tech/contracts/business-domain-artifacts.schema.json', 'GraphContext'),
    ]
    for path, name in contracts:
        schema = json.loads(path.read_text())
        definition = schema['$defs'][name]
        assert definition['properties']['capabilities']['items'] == {'$ref':'#/$defs/Capability'}
        assert 'capabilities' in definition['required']
        context = {key:[] if key == 'capabilities' else {} for key in definition['required']}
        validator = Draft202012Validator({
            '$schema':schema['$schema'], '$defs':schema['$defs'], '$ref':'#/$defs/'+name,
        })
        validator.validate(context)
        context.pop('capabilities')
        with pytest.raises(ValidationError):
            validator.validate(context)


def test_graphql_trace_read_contract_exposes_traversal_completion():
    from dashboard.backend.schema import schema

    trace = schema._schema.get_type('BusinessTrace')
    assert str(trace.fields['traversalComplete'].type) == 'Boolean!'
