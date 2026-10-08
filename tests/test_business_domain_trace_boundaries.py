"""Trace completion: complete, bounded by known boundaries, or incomplete.

Resolution is unchanged; completion says whether what stops a trace is a
catalogued boundary, recorded as an assumption with its evidence, or a gap.
"""
import copy

import pytest

from lib.context.business_domain_cli import trace_blockers
from lib.context.business_domain_extract import Extractor, trace_boundary
from lib.context.business_domain_schema import DEFAULTS, DomainError, validate_references
from lib.context.business_domain_work import _segment_packet, graph_context


def _obligation(kind, status, code='UNRESOLVED_TARGET'):
    return {'kind': kind, 'status': status, 'reason_code': code}


def _edge(kind='calls', to_ref=None):
    return {'id': 'edge:e', 'kind': kind, 'to_ref': to_ref}


RESOURCE = {'kind': 'resource', 'id': 'resource:r'}


# ── Classification ───────────────────────────────────────────────────────

@pytest.mark.parametrize('obligation, edge, codes, resource, expected', [
    # Runtime-generated implementations whose behavior follows from declarations.
    (_obligation('implementation_selection', 'external'), _edge('selects_implementation', RESOURCE),
     {'SPRING_DATA_RUNTIME_IMPLEMENTATION'}, None, 'generated_implementation'),
    (_obligation('data_target', 'unresolved'), _edge('reads_data', RESOURCE),
     {'SPRING_DATA_GENERATED_QUERY'}, None, 'generated_implementation'),
    # Completion decided by the caller or container.
    (_obligation('data_target', 'unresolved'), _edge('writes_data', RESOURCE),
     {'SQL_COMPLETION_UNRESOLVED', 'SQL_TRANSACTION_SCOPE_UNRESOLVED'}, None,
     'transaction_completion'),
    # A real gap beside a boundary keeps the obligation a gap.
    (_obligation('data_target', 'unresolved'), _edge('writes_data', RESOURCE),
     {'SQL_COMPLETION_UNRESOLVED', 'SQL_OPERATION_PARSE_GAP'}, None, None),
    (_obligation('data_target', 'unresolved'), _edge('writes_data', None),
     {'SQL_COMPLETION_UNRESOLVED'}, None, None),
    (_obligation('data_target', 'unresolved'), _edge('writes_data', RESOURCE), set(), None, None),
    # Known library or platform APIs, per language.
    (_obligation('external_boundary', 'external'), _edge('calls', RESOURCE), {'JAVA_EXTERNAL_CALL'},
     {'language': 'java', 'provider': 'type:java.util.List'}, 'library_call'),
    (_obligation('external_boundary', 'external'), _edge('calls', RESOURCE), {'JS_EXTERNAL_CALL'},
     {'language': 'tsx', 'provider': 'module:react-router/lib/browserHistory'}, 'library_call'),
    (_obligation('external_boundary', 'external'), _edge('calls', RESOURCE), {'RULES_AMBIENT_CALL'},
     {'language': 'typescript', 'provider': 'global:console'}, 'library_call'),
    # An unknown library stays a gap, and so does a known name in another language.
    (_obligation('external_boundary', 'external'), _edge('calls', RESOURCE), {'JS_EXTERNAL_CALL'},
     {'language': 'tsx', 'provider': 'module:left-pad'}, None),
    (_obligation('external_boundary', 'external'), _edge('calls', RESOURCE), {'JAVA_EXTERNAL_CALL'},
     {'language': 'java', 'provider': 'type:com.acme.Thing'}, None),
    (_obligation('external_boundary', 'external'), _edge('calls', RESOURCE), {'JAVA_EXTERNAL_CALL'},
     {'language': 'sql', 'provider': 'type:java.util.List'}, None),
    (_obligation('external_boundary', 'external'), _edge('calls', RESOURCE), {'JAVA_EXTERNAL_CALL'},
     {'language': 'java', 'provider': None}, None),
    # Candidate providers: known only when every candidate is catalogued.
    (_obligation('external_boundary', 'external'), _edge('calls', RESOURCE), {'JAVA_EXTERNAL_CALL'},
     {'language': 'java', 'provider': 'type:java.util.Collections|jakarta.persistence.Collections'},
     'library_call'),
    (_obligation('external_boundary', 'external'), _edge('calls', RESOURCE), {'JAVA_EXTERNAL_CALL'},
     {'language': 'java', 'provider': 'type:java.util.Collections|com.acme.Collections'}, None),
    # HTTP: reaching an endpoint anchored here is a boundary; nowhere known is a gap.
    (_obligation('external_boundary', 'external', 'ROUTED_REQUEST'),
     _edge('invokes_endpoint', RESOURCE), set(), None, 'endpoint_in_repo'),
    (_obligation('external_boundary', 'external', 'SAME_ORIGIN_REQUEST'),
     _edge('invokes_endpoint', RESOURCE), set(), None, 'endpoint_in_repo'),
    (_obligation('external_boundary', 'external'), _edge('invokes_endpoint', RESOURCE),
     set(), None, None),
    # Profile- or configuration-selected alternatives.
    (_obligation('implementation_selection', 'conditional', 'CONDITIONAL_IMPLEMENTATION'),
     None, set(), None, 'config_selected'),
    # Real gaps.
    (_obligation('implementation_selection', 'ambiguous', 'IMPLEMENTATION_AMBIGUOUS'),
     _edge('selects_implementation'), set(), None, None),
    (_obligation('call_target', 'unresolved'), _edge(), {'JAVA_CALL_UNRESOLVED'}, None, None),
    (_obligation('call_target', 'ambiguous'), _edge(), {'JAVA_CALL_AMBIGUOUS'}, None, None),
    (_obligation('depth_limit', 'limit_reached', 'DEPTH_LIMIT'), _edge(), set(), None, None),
    (_obligation('implementation_selection', 'unresolved', 'IMPLEMENTATION_NOT_REACHED'),
     None, set(), None, None),
    (_obligation('call_target', 'satisfied', 'ROUTED_REQUEST'), None, set(), None, None),
])
def test_each_obligation_is_a_boundary_or_a_gap(obligation, edge, codes, resource, expected):
    assert trace_boundary(obligation, edge, codes, resource) == expected


# ── Extraction ───────────────────────────────────────────────────────────

CONTROLLER = """package com.example.web;
import java.util.List;
import com.acme.vendor.Scorer;
import org.springframework.web.bind.annotation.*;

@RestController
public class NameController {
  @GetMapping("/names/empty")
  public boolean empty(List<String> names) { return names.isEmpty(); }

  @GetMapping("/names/score")
  public int score(Scorer scorer) { return scorer.score(); }

  @GetMapping("/names/count")
  public int count() { return 1; }
}
"""


@pytest.fixture(scope='module')
def facts(tmp_path_factory):
    root = tmp_path_factory.mktemp('boundaries')
    path = root / 'src/main/java/com/example/web/NameController.java'
    path.parent.mkdir(parents=True)
    path.write_text(CONTROLLER)
    facts, _ = Extractor(root, DEFAULTS).extract()
    validate_references(facts)
    return facts


def _trace(facts, path):
    anchor = next(anchor for anchor in facts['anchors'].values()
                  if anchor['operation'].get('path') == path)
    return next(trace for trace in facts['traces'].values() if trace['anchor_id'] == anchor['id'])


def test_a_trace_with_every_obligation_satisfied_is_complete(facts):
    trace = _trace(facts, '/names/count')
    assert (trace['resolution'], trace['completion'], trace['assumptions']) == (
        'resolved', 'complete', [])


def test_a_known_library_call_bounds_the_trace_and_states_its_assumption(facts):
    trace = _trace(facts, '/names/empty')
    # Resolution is never improved by a boundary.
    assert trace['resolution'] == 'unresolved'
    assert trace['completion'] == 'bounded'
    [assumption] = trace['assumptions']
    assert assumption['kind'] == 'library_call'
    assert assumption['statement'].startswith('type:java.util.List behaves as its published API')
    obligation = facts['trace_obligations'][assumption['obligation_id']]
    assert obligation['boundary'] == 'library_call'
    assert assumption['evidence_ids'] == obligation['evidence_ids']
    excerpts = [facts['evidence'][item]['excerpt'] for item in assumption['evidence_ids']]
    assert any('names.isEmpty()' in excerpt for excerpt in excerpts)


def test_an_unknown_library_call_is_a_gap(facts):
    trace = _trace(facts, '/names/score')
    assert trace['completion'] == 'incomplete'
    assert trace['assumptions'] == []
    [blocking] = [facts['trace_obligations'][oid] for oid in trace['obligation_ids']
                  if facts['trace_obligations'][oid]['status'] != 'satisfied']
    assert blocking['kind'] == 'external_boundary' and blocking['boundary'] is None


def test_the_blocker_report_splits_boundaries_from_gaps(facts):
    report = trace_blockers(facts)
    assert [(item['class'], item['category'], item['traces']) for item in report] == [
        ('boundary', 'library_call', 1), ('gap', 'library_call', 1)]
    assert report[0]['label'] != report[1]['label']


def test_completion_must_agree_with_its_obligations(facts):
    broken = copy.deepcopy(facts)
    _trace(broken, '/names/score')['completion'] = 'bounded'
    with pytest.raises(DomainError, match='completion'):
        validate_references(broken)
    broken = copy.deepcopy(facts)
    _trace(broken, '/names/empty')['assumptions'] = []
    with pytest.raises(DomainError, match='assumption'):
        validate_references(broken)


def test_synthesis_context_carries_the_assumptions(facts):
    context = graph_context(facts)
    trace = _trace(context, '/names/empty')
    assert trace['completion'] == 'bounded'
    assert [item['kind'] for item in trace['assumptions']] == ['library_call']
    # The evidence an assumption cites travels with it.
    assert set(trace['assumptions'][0]['evidence_ids']) <= set(context['evidence'])


def test_a_segment_packet_keeps_only_the_assumptions_it_carries(facts):
    trace = _trace(facts, '/names/empty')
    anchor = facts['anchors'][trace['anchor_id']]
    packet, _ = _segment_packet(facts, anchor['id'], [anchor['symbol_id']],
                                lambda sliced, anchors: sliced)
    sliced = packet['traces'][trace['id']]
    carried = set(sliced['obligation_ids'])
    assert all(item['obligation_id'] in carried for item in sliced['assumptions'])
    blocking = [packet['trace_obligations'][oid] for oid in sliced['obligation_ids']
                if packet['trace_obligations'][oid]['status'] != 'satisfied']
    assert sliced['completion'] == ('complete' if not blocking else
                                    'bounded' if all(item.get('boundary') for item in blocking)
                                    else 'incomplete')


# ── Profile-selected implementations ─────────────────────────────────────

REPOSITORY = {
    'src/main/java/com/example/repo/Owner.java': 'package com.example.repo;\npublic class Owner {}\n',
    'src/main/java/com/example/repo/OwnerRepository.java': (
        'package com.example.repo;\npublic interface OwnerRepository { void save(Owner owner); }\n'),
    'src/main/java/com/example/repo/JdbcOwnerRepository.java': (
        'package com.example.repo;\nimport org.springframework.context.annotation.Profile;\n'
        '@Profile("jdbc")\npublic class JdbcOwnerRepository implements OwnerRepository {\n'
        '  public void save(Owner owner) {}\n}\n'),
    'src/main/java/com/example/repo/JpaOwnerRepository.java': (
        'package com.example.repo;\nimport org.springframework.context.annotation.Profile;\n'
        '@Profile("jpa")\npublic class JpaOwnerRepository implements OwnerRepository {\n'
        '  public void save(Owner owner) {}\n}\n'),
    'src/main/java/com/example/web/OwnerController.java': (
        'package com.example.web;\nimport com.example.repo.*;\n'
        'import org.springframework.web.bind.annotation.*;\n'
        '@RestController\npublic class OwnerController {\n  private OwnerRepository owners;\n'
        '  @PostMapping("/owners")\n  public void add(Owner owner) { owners.save(owner); }\n}\n'),
}


def test_profile_alternatives_are_conditional_paths_not_an_ambiguous_choice(tmp_path):
    for name, text in REPOSITORY.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)
    trace = _trace(facts, '/owners')
    names = {facts['symbols'][sid]['qualified_name'].split('::')[-1] for sid in trace['symbol_ids']}
    # Every alternative is followed.
    assert {'JdbcOwnerRepository.save(Owner)', 'JpaOwnerRepository.save(Owner)'} <= names
    [choice] = [facts['trace_obligations'][oid] for oid in trace['obligation_ids']
                if facts['trace_obligations'][oid]['reason_code'] == 'CONDITIONAL_IMPLEMENTATION']
    assert choice['status'] == 'conditional' and choice['boundary'] == 'config_selected'
    assert '@Profile("jdbc") on JdbcOwnerRepository' in choice['reason']
    assert '@Profile("jpa") on JpaOwnerRepository' in choice['reason']
    # Nothing is chosen: the trace is bounded, never resolved.
    # Not ambiguous, and not resolved either: which condition holds is runtime.
    assert (trace['resolution'], trace['completion']) == ('unresolved', 'bounded')
    assert not [oid for oid in trace['obligation_ids']
                if facts['trace_obligations'][oid]['status'] == 'ambiguous']
    [assumption] = trace['assumptions']
    assert assumption['kind'] == 'config_selected'
    excerpts = {facts['evidence'][item]['excerpt'] for edge_id in trace['edge_ids']
                for item in facts['edges'][edge_id]['evidence_ids']}
    assert {'@Profile("jdbc")', '@Profile("jpa")'} <= excerpts


ENTRY_POINT_PROFILES = {
    'src/main/java/com/example/api/OrdersApi.java': (
        'package com.example.api;\nimport org.springframework.web.bind.annotation.*;\n'
        'public interface OrdersApi {\n  @GetMapping("/orders")\n  String list();\n}\n'),
    'src/main/java/com/example/web/MockOrders.java': (
        'package com.example.web;\nimport com.example.api.OrdersApi;\n'
        'import org.springframework.context.annotation.Profile;\n'
        'import org.springframework.web.bind.annotation.RestController;\n'
        '@Profile("mock")\n@RestController\npublic class MockOrders implements OrdersApi {\n'
        '  public String list() { return "mock"; }\n}\n'),
    'src/main/java/com/example/web/ProdOrders.java': (
        'package com.example.web;\nimport com.example.api.OrdersApi;\n'
        'import org.springframework.context.annotation.Profile;\n'
        'import org.springframework.web.bind.annotation.RestController;\n'
        '@Profile("prod")\n@RestController\npublic class ProdOrders implements OrdersApi {\n'
        '  public String list() { return "prod"; }\n}\n'),
}


def test_a_profile_choice_at_the_entry_point_is_conditional_not_ambiguous(tmp_path):
    for name, text in ENTRY_POINT_PROFILES.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    facts, _ = Extractor(tmp_path, DEFAULTS).extract()
    validate_references(facts)
    # The interface's registration is the entry point that must choose.
    anchor = next(anchor for anchor in facts['anchors'].values()
                  if anchor['operation'].get('path') == '/orders'
                  and any(item['role'] == 'registration' for item in anchor['representations']))
    trace = next(trace for trace in facts['traces'].values() if trace['anchor_id'] == anchor['id'])
    obligations = [facts['trace_obligations'][oid] for oid in trace['obligation_ids']]
    assert not [item for item in obligations if item['kind'] == 'implementation_selection'
                and item['status'] == 'ambiguous']
    [choice] = [item for item in obligations if item['reason_code'] == 'CONDITIONAL_IMPLEMENTATION']
    assert choice['status'] == 'conditional' and choice['boundary'] == 'config_selected'
    assert '@Profile("mock") on MockOrders' in choice['reason']
    assert '@Profile("prod") on ProdOrders' in choice['reason']
    # Both alternatives are followed.
    names = {facts['symbols'][sid]['qualified_name'].split('::')[-1] for sid in trace['symbol_ids']}
    assert {'MockOrders.list()', 'ProdOrders.list()'} <= names
