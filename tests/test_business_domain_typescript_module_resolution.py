"""tsconfig/typings as supporting inputs and the one shared alias resolver (F1)."""
import pytest

from lib.context.business_domain_adapters import typescript_module_resolution
from lib.context.business_domain_adapters.base import Source
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import (
    DEFAULTS, digest, identifier, validate_references, validate_source_warning_coverage)
from lib.context.layer1_domain_clustering import (
    TypeScriptModuleResolutionError, parse_typescript_module_resolution,
    resolve_typescript_path_alias)


def _source(path, text):
    return Source(path, 'json', text, digest(text.encode()), identifier('resource', path))


def _extract(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    facts, units = Extractor(root, DEFAULTS).extract()
    validate_references(facts)
    validate_source_warning_coverage(facts)
    return facts, units


def _aliases(paths):
    return parse_typescript_module_resolution(
        '{"compilerOptions": {"paths": %s}}' % paths, 'tsconfig')['aliases']


# ── Parser and resolver ──────────────────────────────────────────────────

def test_tsconfig_and_typings_normalize():
    parsed = parse_typescript_module_resolution(
        '{"compilerOptions": {"paths": {"@/*": ["src/*", "lib/*"], "cfg": ["config.ts"]}}}',
        'tsconfig')
    assert parsed['aliases'] == (
        {'pattern': '@/*', 'wildcard': True, 'targets': (
            {'pattern': 'src/*', 'wildcard': True}, {'pattern': 'lib/*', 'wildcard': True})},
        {'pattern': 'cfg', 'wildcard': False, 'targets': (
            {'pattern': 'config.ts', 'wildcard': False},)})
    typings = parse_typescript_module_resolution(
        '{"dependencies": {"b": "x"}, "globalDependencies": {"a": "y"}}', 'typings')
    assert typings['declared_external_modules'] == ({'name': 'a'}, {'name': 'b'})


@pytest.mark.parametrize('text, cause', [
    ('{', 'json_syntax_invalid'),
    ('[]', 'top_level_must_be_object'),
    ('{"compilerOptions": []}', 'compiler_options_must_be_object'),
    ('{"compilerOptions": {"paths": {"a": "b"}}}', 'alias_targets_must_be_nonempty_array'),
    ('{"compilerOptions": {"paths": {"a": [1]}}}', 'invalid_alias_pattern'),
    ('{"compilerOptions": {"paths": {"a/**": ["b"]}}}', 'invalid_alias_pattern'),
    ('{"compilerOptions": {"paths": {"exact": ["src/*"]}}}',
     'exact_alias_cannot_capture_wildcard_target'),
])
def test_malformed_configuration_is_rejected(text, cause):
    with pytest.raises(TypeScriptModuleResolutionError) as raised:
        parse_typescript_module_resolution(text, 'tsconfig')
    assert raised.value.cause == cause


def test_resolution_states_and_wildcard_boundaries():
    paths = ('client/src/api.ts', 'client/src/api/index.ts', 'client/lib/util.tsx')
    aliases = _aliases('{"@/*": ["src/*"], "foo": ["lib/util"], "fixed/*": ["lib/util"]}')
    resolve = lambda name: resolve_typescript_path_alias(name, 'client', aliases, paths)
    assert resolve('@/api') == {'state': 'ambiguous',
        'candidates': ('client/src/api.ts', 'client/src/api/index.ts')}
    assert resolve('foo') == {'state': 'resolved', 'candidates': ('client/lib/util.tsx',)}
    # An exact alias matches only an identical import.
    assert resolve('foobar') == {'state': 'unmatched', 'candidates': ()}
    # A wildcard alias with a fixed target ignores its capture.
    assert resolve('fixed/anything') == {'state': 'resolved',
                                         'candidates': ('client/lib/util.tsx',)}
    assert resolve('@/missing') == {'state': 'unresolved', 'candidates': ()}


def test_equal_specificity_aliases_union_their_candidates():
    paths = ('a/x.ts', 'b/x.ts')
    aliases = _aliases('{"p/*": ["a/*"], "*/x": ["b/x"]}')
    assert resolve_typescript_path_alias('p/x', '.', aliases, paths) == {
        'state': 'ambiguous', 'candidates': ('a/x.ts', 'b/x.ts')}


def test_target_escaping_the_repository_is_rejected_by_the_consumer():
    escaping = _source('tsconfig.json', '{"compilerOptions": {"paths": {"@/*": ["../../*"]}}}')
    result = typescript_module_resolution.consume((escaping,), ())
    assert result.consumed_source_ids == ()
    [diagnostic] = result.diagnostics
    assert (diagnostic['code'], diagnostic['reason'], diagnostic['span']) == (
        'TYPESCRIPT_MODULE_RESOLUTION_INVALID', 'target_escapes_repository',
        (0, len(escaping.text)))


# ── Extraction ───────────────────────────────────────────────────────────

API = 'export function send() { return 1; }\n'


def _edges_from(facts, units, name):
    symbol = next(unit.symbol_id for unit in units if unit.name == name)
    return [edge for edge in facts['edges'].values()
            if edge['kind'] == 'calls' and edge['from_ref']['id'] == symbol]


def test_alias_import_resolves_to_its_one_local_target(tmp_path):
    facts, units = _extract(tmp_path, {
        'client/tsconfig.json': '{"compilerOptions": {"paths": {"@/*": ["src/*"]}}}',
        'client/src/api.ts': API,
        'client/src/page.ts': "import { send } from '@/api';\nexport function submit() { send(); }\n",
    })
    page = next(unit.source for unit in units if unit.source.path == 'client/src/page.ts')
    assert page.resolved_module_targets['@/api']['state'] == 'resolved'
    [edge] = _edges_from(facts, units, 'submit')
    target = next(unit for unit in units if unit.symbol_id == edge['to_ref']['id'])
    assert edge['resolution'] == 'resolved' and target.source.path == 'client/src/api.ts'


def test_alias_import_with_two_targets_stays_bounded_ambiguous(tmp_path):
    facts, units = _extract(tmp_path, {
        'tsconfig.json': '{"compilerOptions": {"paths": {"@/*": ["a/*", "b/*"]}}}',
        'a/api.ts': API, 'b/api.ts': API,
        'page.ts': "import { send } from '@/api';\nexport function submit() { send(); }\n",
    })
    [edge] = _edges_from(facts, units, 'submit')
    assert edge['resolution'] == 'ambiguous' and len(edge['candidate_target_ids']) == 2


def test_typings_declared_module_is_an_external_boundary_not_a_local_symbol(tmp_path):
    facts, units = _extract(tmp_path, {
        'typings.json': '{"dependencies": {"vendor": "registry:vendor"}}',
        'local/vendor.ts': API,
        'page.ts': "import { send } from 'vendor';\nexport function submit() { send(); }\n",
    })
    page = next(unit.source for unit in units if unit.source.path == 'page.ts')
    assert page.resolved_module_targets['vendor']['state'] == 'external'
    [edge] = _edges_from(facts, units, 'submit')
    assert edge['to_ref'] is None or edge['to_ref']['kind'] != 'symbol'


def test_same_scope_tsconfig_and_typings_merge(tmp_path):
    _, units = _extract(tmp_path, {
        'client/tsconfig.json': '{"compilerOptions": {"paths": {"@/*": ["src/*"]}}}',
        'client/typings.json': '{"dependencies": {"vendor": "x"}}',
        'client/src/page.ts': 'export function page() { return 1; }\n',
    })
    page = next(unit.source for unit in units if unit.source.path == 'client/src/page.ts')
    selected = page.supporting_inputs['typescript_module_resolution']
    assert set(selected) == {'tsconfig', 'typings'}
    assert selected['tsconfig']['scope_dir'] == 'client'


def test_deepest_configuration_wins(tmp_path):
    _, units = _extract(tmp_path, {
        'tsconfig.json': '{"compilerOptions": {"paths": {"root/*": ["*"]}}}',
        'client/tsconfig.json': '{"compilerOptions": {"paths": {"@/*": ["src/*"]}}}',
        'client/src/page.ts': 'export function page() { return 1; }\n',
        'server/main.ts': 'export function main() { return 1; }\n',
    })
    by_path = {unit.source.path: unit.source for unit in units}
    chosen = lambda path: by_path[path].supporting_inputs[
        'typescript_module_resolution']['tsconfig']['scope_dir']
    assert chosen('client/src/page.ts') == 'client'
    assert chosen('server/main.ts') == '.'


def test_malformed_configuration_is_a_format_diagnostic(tmp_path):
    facts, _ = _extract(tmp_path, {'tsconfig.json': '{"compilerOptions": {"paths": 1}}'})
    resource_id = identifier('resource', 'tsconfig.json')
    [warning] = [w for w in facts['warnings'] if w['subject_ids'] == [resource_id]]
    assert (warning['code'], warning['message']) == (
        'TYPESCRIPT_MODULE_RESOLUTION_INVALID', 'paths_must_be_object')
    assert facts['resources'][resource_id]['resolution'] == 'unresolved'
    assert facts['coverage']['unsupported_source_ids'] == []
