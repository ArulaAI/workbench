"""Java Properties: parsing, scope, byte accounting and redaction (F1)."""
import json
from pathlib import Path

import pytest

from lib.context.business_domain_adapters import java_properties
from lib.context.business_domain_adapters.base import Source
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import (
    DEFAULTS, digest, identifier, validate_references, validate_source_warning_coverage)

MAIN = 'src/main/resources/application.properties'


def _source(text, path=MAIN):
    return Source(path, 'properties', text, digest(text.encode()), identifier('resource', path))


def _declarations(text, path=MAIN):
    source = _source(text, path)
    units = java_properties.extract(source)
    return source, [(unit.configuration.key, unit.configuration.value) for unit in units], units


def _extract(root, files):
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)
    facts, units = Extractor(root, DEFAULTS).extract()
    validate_references(facts)
    validate_source_warning_coverage(facts)
    return facts, units


def _persisted(root, facts):
    """Every persisted and provider-ready projection of one extraction, as text."""
    snapshots = ''.join(path.read_text() for path in
        (root / '.speed/context/business-domain-snapshots').glob('*.json'))
    return json.dumps(facts) + snapshots


# ── Grammar ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize('text, expected', [
    ('a=1', [('a', '1')]),
    ('a:1', [('a', '1')]),
    ('a 1', [('a', '1')]),
    ('a\t1', [('a', '1')]),
    ('a\f1', [('a', '1')]),
    ('a = 1', [('a', '1')]),
    ('a  :  1', [('a', '1')]),
    ('a', [('a', '')]),
    ('a=', [('a', '')]),
    ('a==1', [('a', '=1')]),
    (r'a\=b=1', [('a=b', '1')]),
    (r'a\:b:1', [('a:b', '1')]),
    (r'a\ b=1', [('a b', '1')]),
    (r'k=\t\n\r\f\x', [('k', '\t\n\r\fx')]),
])
def test_separators_and_escapes(text, expected):
    assert _declarations(text)[1] == expected


def test_comments_blanks_and_a_comment_ending_in_backslash():
    text = '# comment\n! bang\n\n   # indented\n# continued? \\\nreal=1\n'
    assert _declarations(text)[1] == [('real', '1')]


def test_line_terminators_form_feed_and_continuations():
    text = 'a=1\rb=2\r\nc=3\nd=four\\\n    five\\\r\n six\ne=\f7'
    assert _declarations(text)[1] == [
        ('a', '1'), ('b', '2'), ('c', '3'), ('d', 'fourfivesix'), ('e', '7')]


def test_even_backslashes_do_not_continue_and_eof_continuation_ends_the_value():
    assert _declarations('a=x\\\\\nb=y')[1] == [('a', 'x\\'), ('b', 'y')]
    assert _declarations('a=x\\')[1] == [('a', 'x')]


def test_empty_and_blank_files_have_no_declarations():
    assert _declarations('')[1] == []
    assert _declarations('\n\n  \n')[1] == []


def test_unicode_escapes_and_surrogate_pairs():
    assert _declarations(r'k=caf\u00e9 \ud83d\ude00')[1] == [('k', 'café 😀')]


@pytest.mark.parametrize('text, cause', [
    (r'k=\u00g1', 'invalid_unicode_escape'),
    (r'k=\u12', 'invalid_unicode_escape'),
    (r'k=\ud83d', 'lone_high_surrogate'),
    (r'k=\ude00', 'lone_low_surrogate'),
    (r'k=\ud83d\u0041', 'invalid_surrogate_pair'),
])
def test_bad_escapes_are_diagnosed_and_neighbors_survive(text, cause):
    source, declarations, _ = _declarations(f'before=1\n{text}\nafter=2\n')
    assert declarations == [('before', '1'), ('after', '2')]
    [diagnostic] = java_properties.diagnostics(source)
    assert diagnostic['code'] == 'JAVA_PROPERTIES_SYNTAX_INVALID'
    assert diagnostic['reason'] == cause
    start, end = diagnostic['span']
    assert 0 <= start < end <= len(source.text) and '\\' in source.text[start:end]


def test_byte_order_mark_is_diagnosed_and_only_its_declaration_is_skipped():
    source, declarations, _ = _declarations('\ufeffhidden=1\nshown=2\n')
    assert declarations == [('shown', '2')]
    assert java_properties.diagnostics(source) == [{
        'code': 'JAVA_PROPERTIES_SYNTAX_INVALID',
        'reason': 'byte_order_mark_not_supported', 'span': (0, 1)}]
    source, declarations, _ = _declarations('\ufeff')
    assert declarations == [] and java_properties.diagnostics(source)


def test_decode_is_utf8_first_then_latin1_without_bom_stripping():
    assert java_properties.decode('ü=1'.encode()).encoding == 'utf-8'
    latin = java_properties.decode('ü=1'.encode('iso-8859-1'))
    assert (latin.text, latin.encoding, latin.original_byte_length) == ('ü=1', 'iso-8859-1', 3)
    assert java_properties.decode(b'\xef\xbb\xbfa=1').text.startswith('\ufeff')


def test_exact_spans_and_occurrences():
    text = 'a=1\nlong.key = first\\\n   second\na=2\n'
    source, _, units = _declarations(text)
    assert [(unit.start, unit.end) for unit in units] == [(0, 3), (4, 31), (32, 35)]
    long_key = units[1].configuration
    assert [text[start:end] for start, end in long_key.value_spans] == ['first', 'second']
    assert [unit.configuration.occurrence for unit in units] == [0, 0, 1]
    assert [unit.kind for unit in units] == ['field'] * 3


@pytest.mark.parametrize('path, expected', [
    ('src/main/resources/application.properties', ('main', None, 'application_configuration')),
    ('src/main/resources/application-mysql.properties', ('main', 'mysql', 'application_configuration')),
    ('src/test/resources/application.properties', ('test', None, 'application_configuration')),
    ('svc/orders/src/main/resources/application-prod.properties', ('main', 'prod', 'application_configuration')),
    ('src/main/resources/messages/messages_de.properties', ('main', None, 'message_catalog')),
    ('src/test/resources/messages.properties', ('test', None, 'message_catalog')),
])
def test_configuration_scope(path, expected):
    assert java_properties._configuration_scope(path) == expected


@pytest.mark.parametrize('path', [
    'config/application.properties', 'src/main/resources/other.properties',
    'src/main/resources/src/main/resources/application.properties',
])
def test_impossible_configuration_paths_raise(path):
    with pytest.raises(ValueError):
        java_properties._configuration_scope(path)


# ── Projection ───────────────────────────────────────────────────────────

def test_duplicate_keys_have_distinct_stable_unit_symbol_and_binding_ids(tmp_path):
    facts, units = _extract(tmp_path, {MAIN: 'k=one\nk=two\n'})
    first, second = [unit for unit in units if unit.configuration]
    for occurrence, unit in enumerate((first, second)):
        assert unit.qualified == 'property:' + digest([MAIN, 'k', occurrence])
        assert unit.symbol_id == identifier('symbol', unit.qualified)
        assert unit.kind == 'field'
        assert facts['symbols'][unit.symbol_id]['kind'] == 'field'
        assert identifier('binding', unit.symbol_id, 'k', 'internal') in facts['bindings']
    assert first.symbol_id != second.symbol_id
    assert sorted(binding['expression'] for binding in facts['bindings'].values()) == ['one', 'two']


def test_binding_scope_and_reason_are_complete_and_never_effective(tmp_path):
    facts, _ = _extract(tmp_path, {
        'src/main/resources/application-prod.properties': 'petclinic.security.enable=false\n'})
    [binding] = facts['bindings'].values()
    assert binding['scope'] == {'environment': 'main', 'tenant': None, 'actor': None,
        'profile': 'prod', 'effective_from': None, 'effective_to': None,
        'version': None, 'entrypoint_ids': None}
    assert binding['value_type'] == 'string' and binding['direction'] == 'internal'
    assert binding['resolution'] == 'unresolved'
    assert binding['reason'] == ('Repository declaration retained; effective precedence '
                                 'was not evaluated.')


def test_latin1_source_is_analyzed_and_raw_bytes_are_accounted(tmp_path):
    raw = 'greeting=Grüße\n'.encode('iso-8859-1')
    path = 'src/main/resources/messages/messages_de.properties'
    facts, units = _extract(tmp_path, {path: raw})
    assert not [w for w in facts['warnings'] if w['code'] == 'SOURCE_ENCODING']
    [unit] = [unit for unit in units if unit.configuration]
    assert unit.configuration.value == 'Grüße'
    assert unit.configuration.role == 'message_catalog'
    assert facts['limits']['source_bytes'] == len(raw)
    resource = facts['resources'][identifier('resource', path)]
    assert resource['resolution'] == 'resolved' and resource['language'] == 'properties'


def test_empty_file_is_resolved_with_empty_source_evidence(tmp_path):
    facts, _ = _extract(tmp_path, {MAIN: ''})
    resource = facts['resources'][identifier('resource', MAIN)]
    assert resource['resolution'] == 'resolved'
    [evidence_id] = resource['evidence_ids']
    locator = facts['evidence'][evidence_id]
    assert locator['excerpt'] == ''


def test_malformed_neighbor_keeps_valid_facts_and_leaves_the_file_unresolved(tmp_path):
    facts, _ = _extract(tmp_path, {MAIN: 'good=1\nbad=\\u12\n'})
    resource = facts['resources'][identifier('resource', MAIN)]
    assert resource['resolution'] == 'unresolved'
    assert [b['name'] for b in facts['bindings'].values()] == ['good']
    [warning] = [w for w in facts['warnings'] if w['code'] == 'JAVA_PROPERTIES_SYNTAX_INVALID']
    assert warning['subject_ids'] == [resource['id']] and warning['evidence_ids']
    # A format diagnostic is not a blocking capability failure.
    assert facts['coverage']['unsupported_source_ids'] == []


# ── Redaction ────────────────────────────────────────────────────────────

def test_secret_literals_never_persist(tmp_path):
    text = ('spring.datasource.password = alpha beta\n'
            'app.credential=gamma delta\n'
            'user.passwd: epsilon\n'
            'service.token=zeta eta\\\n   theta\n'
            'oauth.access_token="iota kappa"\n'
            'author=visible-author\n'
            'tokenizer=visible-tokenizer\n')
    facts, _ = _extract(tmp_path, {MAIN: text})
    persisted = _persisted(tmp_path, facts)
    for secret in ('alpha beta', 'gamma delta', 'epsilon', 'zeta eta', 'theta', 'iota kappa'):
        assert secret not in persisted
    assert 'visible-author' in persisted and 'visible-tokenizer' in persisted
    bindings = {b['name']: b['expression'] for b in facts['bindings'].values()}
    assert bindings['spring.datasource.password'] == '[REDACTED]'
    assert bindings['author'] == 'visible-author'


def test_nested_json_secrets_never_persist_in_evidence(tmp_path):
    from lib.context.business_domain_extract import redacted
    text = '{"password":"secret","nested":{"token":"nested-secret"}}'
    assert 'secret"' not in redacted(text).replace('"[REDACTED]"', '')
    assert 'nested-secret' not in redacted(text)


def test_inline_and_line_tail_credentials_are_redacted():
    from lib.context.business_domain_extract import redacted
    assert 'alpha beta' not in redacted("connect(password='alpha beta')")
    assert 'alpha beta' not in redacted('db.password: alpha beta\n')
    assert redacted('tokenizer=keep') == 'tokenizer=keep'


def test_decoder_failure_is_unsupported_with_redacted_evidence(tmp_path, monkeypatch):
    def broken(raw):
        raise RuntimeError('repository content must never reach a message')
    monkeypatch.setattr(java_properties, 'decode', broken)
    facts, _ = _extract(tmp_path, {MAIN: 'db.password=alpha beta\n'})
    resource_id = identifier('resource', MAIN)
    [warning] = [w for w in facts['warnings'] if w['subject_ids'] == [resource_id]]
    assert warning['code'] == 'ADAPTER_UNAVAILABLE'
    assert 'cause=owner_execution_failed' in warning['message']
    assert facts['evidence'][warning['evidence_ids'][0]]['excerpt'] == '[REDACTED]'
    assert facts['coverage']['unsupported_source_ids'] == [resource_id]
    assert not facts['bindings']
    assert 'alpha beta' not in _persisted(tmp_path, facts)
    assert 'repository content' not in json.dumps(facts)


def test_owner_extract_failure_redacts_failure_evidence(tmp_path, monkeypatch):
    def broken(source):
        raise RuntimeError('boom')
    monkeypatch.setattr(java_properties, 'extract', broken)
    facts, _ = _extract(tmp_path, {MAIN: 'db.password=alpha beta\n'})
    [warning] = [w for w in facts['warnings'] if w['code'] == 'ADAPTER_UNAVAILABLE']
    assert facts['evidence'][warning['evidence_ids'][0]]['excerpt'] == '[REDACTED]'
    assert 'alpha beta' not in _persisted(tmp_path, facts)
    assert Path(tmp_path / MAIN).exists()
