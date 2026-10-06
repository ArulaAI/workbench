"""Where Spring Boot serves a service's endpoints, per configuration and profile.

Bases are read from the main classpath's application configuration. Documents
layer in Spring Boot's precedence order, a profile that moves the port or
context path is a conditioned base, and the default base then applies only
while no such profile is active. A declared ``spring.profiles.active`` is
named, never assumed.
"""
from types import SimpleNamespace

import pytest

from lib.context.business_domain_adapters.spring_semantic import configure, endpoint_bases
from lib.context.business_domain_extract import _route_request


def _bases(files):
    sources = [SimpleNamespace(path='src/main/resources/' + path, service_scope='svc', text=text)
               for path, text in files.items()]
    return endpoint_bases(sources, sources)


def _served(bases):
    return {(base['port'], base['path'], base['condition']) for base in bases}


PROD = 'Spring profile prod is active'


def test_default_configuration_is_one_unconditional_base():
    bases = _bases({'application.properties':
                    'server.port=9966\nserver.servlet.context-path=/petclinic/\n'})
    assert _served(bases) == {(9966, '/petclinic', None)}


def test_without_configuration_spring_boot_serves_8080_at_the_root():
    assert _served(_bases({'logback.xml': '<configuration/>\n'})) == {(8080, '', None)}


def test_profile_that_moves_the_port_conditions_the_default_base():
    bases = _bases({
        'application.properties': 'spring.profiles.active=prod\nserver.port=9966\n',
        'application-prod.properties': 'server.port=9000\n',
    })
    assert _served(bases) == {(9966, '', f'!({PROD})'), (9000, '', PROD)}
    default, prod = bases
    # The declaration is named on both bases but is not proof: a runtime
    # override can still select either.
    assert 'spring.profiles.active=prod' in prod['label']
    assert 'selects this profile' in prod['label']
    assert 'selects an overriding profile' in default['label']
    assert any('spring.profiles.active' in span[0].text[span[1]:span[2]]
               for span in prod['evidence_spans'])


def test_profile_that_repeats_the_default_adds_no_base():
    bases = _bases({'application.properties': 'server.port=9966\n',
                    'application-prod.properties': 'server.port=9966\nspring.jpa.database=HSQL\n'})
    assert _served(bases) == {(9966, '', None)}


def test_profile_that_moves_only_the_context_path():
    bases = _bases({'application.properties': 'server.port=9966\n',
                    'application-prod.properties': 'server.servlet.context-path=/api\n'})
    assert _served(bases) == {(9966, '', f'!({PROD})'), (9966, '/api', PROD)}


def test_properties_take_precedence_over_yaml_in_one_location():
    bases = _bases({'application.properties': 'server.port=9966\n',
                    'application.yml': 'server:\n  port: 7000\n'})
    assert _served(bases) == {(9966, '', None)}


def test_config_directory_takes_precedence_over_the_classpath_root():
    bases = _bases({'application.properties': 'server.port=9966\n',
                    'config/application.properties': 'server.port=7000\n'})
    assert _served(bases) == {(7000, '', None)}


def test_one_profile_declared_in_two_locations_is_one_base():
    bases = _bases({'application.properties': 'server.port=9966\n',
                    'application-prod.properties': 'server.port=9000\n',
                    'config/application-prod.properties': 'server.servlet.context-path=/x\n'})
    assert _served(bases) == {(9966, '', f'!({PROD})'), (9000, '/x', PROD)}


def test_later_yaml_documents_override_and_profile_documents_are_conditioned():
    bases = _bases({'application.yml': '''server:
  port: 9966
---
spring:
  config:
    activate:
      on-profile: prod
server:
  servlet:
    context-path: /prod
---
server:
  port: 7000
'''})
    assert _served(bases) == {(7000, '', f'!({PROD})'), (7000, '/prod', PROD)}


def test_profile_only_yaml_document_is_not_the_default():
    bases = _bases({'application.yml':
                    'spring:\n  config:\n    activate:\n      on-profile: prod\nserver:\n  port: 9000\n'})
    assert _served(bases) == {(8080, '', f'!({PROD})'), (9000, '', PROD)}


def test_properties_documents_are_separated_by_a_marker_line():
    bases = _bases({'application.properties':
                    'server.port=9966\n#---\nspring.config.activate.on-profile=prod\nserver.port=9000\n'})
    assert _served(bases) == {(9966, '', f'!({PROD})'), (9000, '', PROD)}


@pytest.mark.parametrize('expression, condition', [
    ('prod & cloud', 'the active Spring profiles match prod & cloud'),
    ('[prod, cloud]', 'the active Spring profiles match prod,cloud'),
])
def test_profile_expressions_are_stated_not_interpreted(expression, condition):
    bases = _bases({'application.yml': 'server:\n  port: 9966\n---\nspring:\n  config:\n'
                    f'    activate:\n      on-profile: {expression}\nserver:\n  port: 9000\n'})
    assert _served(bases) == {(9966, '', f'!({condition})'), (9000, '', condition)}


def test_profile_with_a_runtime_port_has_no_base_but_still_conditions_the_default():
    bases = _bases({'application.properties': 'spring.profiles.active=prod\nserver.port=9966\n',
                    'application-prod.properties': 'server.port=${PORT:9000}\n'})
    assert _served(bases) == {(9966, '', f'!({PROD})')}


def test_declared_active_profile_reads_only_unconditional_documents():
    sources = [SimpleNamespace(path='src/main/resources/' + path, service_scope='svc', text=text)
               for path, text in {
                   'application.yml': 'spring:\n  profiles:\n    active: jpa\n---\n'
                                      'spring:\n  config:\n    activate:\n      on-profile: jpa\n'
                                      '  profiles:\n    active: jdbc\n',
                   'application-jdbc.properties': 'spring.profiles.active=other\n',
               }.items()]
    configure(sources, sources)
    assert sources[0].spring_declared_profiles[0] == 'jpa'


# ── Routing through several bases ───────────────────────────────────────────

SERVED = [({'operation': {'method': 'GET', 'path': '/api/vets'}, 'role': 'implementation',
            'symbol_id': 'symbol:vets', 'evidence_ids': ['ev:vets'], 'source_id': None}, 'svc')]


def _route(bases, url='http://localhost:9966/api/vets'):
    return _route_request({'method': 'GET', 'url': url}, bases, SERVED)


def _base(path, condition):
    return {'scope': 'svc', 'role': 'implementation', 'source_id': None, 'port': 9966,
            'path': path, 'label': path or '/', 'condition': condition, 'evidence_spans': []}


def test_a_route_any_unconditional_base_answers_is_unconditional():
    outcome = _route([_base('', None), _base('', PROD)])
    assert outcome['resolution'] == 'resolved' and outcome['conditions'] == ()


def test_a_route_several_conditioned_bases_answer_holds_under_either():
    outcome = _route([_base('', f'!({PROD})'), _base('/api', PROD)],
                     url='http://localhost:9966/api/api/vets')
    assert outcome['resolution'] == 'resolved'
    assert outcome['conditions'] == ((PROD, True),)
    outcome = _route([_base('', 'Spring profile a is active'),
                      _base('', 'Spring profile b is active')])
    assert outcome['conditions'] == (
        ('(Spring profile a is active) || (Spring profile b is active)', True),)


def test_a_route_one_conditioned_base_answers_keeps_its_condition():
    outcome = _route([_base('', f'!({PROD})'), _base('/other', PROD)])
    assert outcome['conditions'] == ((f'!({PROD})', True),)
