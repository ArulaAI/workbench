"""Installed classification, ownership and source-disposition policy (F1)."""
import shutil
import tomllib
from pathlib import Path

import pytest

from lib.context.language_registry import (
    LanguageRegistry, RegistryConfigurationError, registry)

DATA = Path(__file__).resolve().parents[1] / 'lib/context/data'
DUPLICATES = ('.bas', '.cl', '.fs', '.inc', '.pl', '.sc', '.v')


def _installed_copy(tmp_path, extraction_suffix='', languages=None):
    data = tmp_path / 'installed'
    shutil.copytree(DATA, data)
    if languages is not None:
        (data / 'languages.toml').write_text(languages)
    if extraction_suffix:
        with (data / 'extraction.toml').open('a') as stream:
            stream.write('\n' + extraction_suffix)
    return data


def test_installed_registry_is_valid_and_properties_has_its_configured_owner():
    assert registry.load_error is None
    classification = registry.classify_path('src/main/resources/application.properties')
    assert (classification.category, classification.language, classification.status) == (
        'config', 'properties', 'classified')
    assert classification.language_candidate_ids == ('ini', 'properties')
    assert registry.classify('.properties') == ('config', 'properties')


@pytest.mark.parametrize('extension', DUPLICATES)
def test_other_duplicate_extensions_stay_ambiguous(extension):
    classification = registry.classify_path('file' + extension)
    assert classification.status == 'ambiguous'
    assert classification.language is None
    assert len(classification.language_candidate_ids) > 1
    assert registry.classify(extension)[1] is None


def test_catalog_order_never_chooses_a_duplicate_owner(tmp_path):
    original = (DATA / 'languages.toml').read_text()
    blocks = original.split('[[language]]')
    head, entries = blocks[0], blocks[1:]
    reordered = head + ''.join('[[language]]' + entry for entry in reversed(entries))
    swapped = LanguageRegistry(_installed_copy(tmp_path, languages=reordered))
    assert swapped.load_error is None
    for path in ('a.properties', *('file' + extension for extension in DUPLICATES)):
        assert swapped.classify_path(path) == registry.classify_path(path)


def test_svg_is_an_asset_for_both_project_map_and_business_extraction():
    from lib.context.project_map import _classify_file
    classification = registry.classify_path('client/fonts/icon.svg')
    assert (classification.category, classification.language,
            classification.reason) == ('asset', 'xml', 'visual_asset')
    assert _classify_file('client/fonts/icon.svg', '.svg', {}) == ('asset', 'xml')
    assert registry.classify_path('logo.png').status == 'unrecognized'


@pytest.mark.parametrize('suffix, cause', [
    ('[extension_owners]\npl = "python"\n', 'extension_owner_not_claimant'),
    ('[extension_owners]\npy = "python"\n', 'extension_owner_unused'),
    ('[extension_owners]\nproperites = "properties"\n', 'extension_owner_unused'),
    ('[source_dispositions.bad]\npath_any = ["x"]\ndisposition = "explode"\nowner = "x"\n',
     'source_disposition_invalid'),
    ('[source_dispositions.bad]\npath_any = ["("]\ndisposition = "ignore"\nowner = "x"\n',
     'source_disposition_pattern_invalid'),
    ('[source_dispositions.bad]\npath_any = ["x"]\ndisposition = "ignore"\nowner = "x"\n'
     'required_capabilities = ["parsing"]\n', 'nonexecuting_disposition_has_capabilities'),
    ('[source_dispositions.bad]\npath_any = ["x"]\ndisposition = "analyze"\nowner = "missing"\n'
     'language = "properties"\n', 'source_disposition_owner_invalid'),
    ('[source_dispositions.bad]\npath_any = ["x"]\ndisposition = "ignore"\nowner = "x"\n'
     'surprise = 1\n', 'source_disposition_invalid'),
    ('[supporting_consumers.orphan]\nmodule = "orphan"\nfunction = "consume"\n'
     'version = "1"\ncapabilities = ["type_resolution"]\ncapability_status = "partial"\n'
     'diagnostic_codes = ["ORPHAN_INVALID"]\n', 'supporting_consumer_owner_mismatch'),
    ('[path_classifiers.another]\nextensions = ["svg"]\ncategory = "asset"\n'
     'reason = "duplicate"\n', 'path_classifier_extension_duplicate'),
])
def test_invalid_installed_policy_is_a_visible_load_error(tmp_path, suffix, cause):
    if suffix.startswith('[extension_owners]'):
        data = _installed_copy(tmp_path)
        text = (data / 'extraction.toml').read_text().replace(
            '[extension_owners]\nproperties = "properties"\n', suffix)
        (data / 'extraction.toml').write_text(text)
    else:
        data = _installed_copy(tmp_path, suffix)
    candidate = LanguageRegistry(data)
    assert isinstance(candidate.load_error, RegistryConfigurationError)
    assert str(candidate.load_error) == cause
    # Nothing partially validated is usable.
    for query in (lambda: candidate.classify_path('a.py'), lambda: candidate.classify('.py'),
                  lambda: candidate.source_adapters('python'),
                  lambda: candidate.fence_label_for('a.py')):
        with pytest.raises(RegistryConfigurationError):
            query()


def test_enricher_must_declare_exactly_one_evidence_form(tmp_path):
    data = _installed_copy(tmp_path)
    text = (data / 'extraction.toml').read_text().replace(
        "[source_adapters.react_semantic.evidence]",
        "[[source_adapters.react_semantic.evidence_any]]\nimports_any = ['^react$']\n"
        "[source_adapters.react_semantic.evidence]")
    (data / 'extraction.toml').write_text(text)
    assert str(LanguageRegistry(data).load_error) == 'enricher_evidence_conflict'


def test_decoder_is_allowed_only_for_an_explicitly_routed_analyze_owner(tmp_path):
    data = _installed_copy(tmp_path)
    text = (data / 'extraction.toml').read_text().replace(
        'module = "html_semantic"\n', 'module = "html_semantic"\ndecoder = "decode"\n', 1)
    (data / 'extraction.toml').write_text(text)
    assert str(LanguageRegistry(data).load_error) == 'source_adapter_decoder_invalid'


def test_installed_dispositions_and_consumers_are_immutable_and_exact():
    dispositions = {item['id']: item for item in registry.source_dispositions()}
    assert set(dispositions) == {
        'application_properties', 'message_properties', 'tool_properties',
        'package_manifest', 'typescript_module_resolution',
        'developer_tool_configuration', 'stylesheet', 'visual_asset',
        'ide_launch_configuration', 'logging_configuration', 'ci_configuration',
        'speed_configuration'}
    with pytest.raises(TypeError):
        dispositions['stylesheet']['owner'] = 'other'
    consumer = registry.supporting_consumer_descriptor('package_manifest')
    assert (consumer['id'], consumer['capability_status'],
            tuple(consumer['diagnostic_codes'])) == (
        'package_manifest', 'partial', ('PACKAGE_JSON_INVALID',))
    adapter = registry.source_adapter_descriptor('java_properties')
    assert adapter['decoder'] == 'decode' and adapter['languages'] == ('properties',)
    assert registry.source_adapter_descriptor('missing') is None


def test_installed_extraction_config_stays_parseable():
    with (DATA / 'extraction.toml').open('rb') as stream:
        config = tomllib.load(stream)
    assert config['extension_owners'] == {'properties': 'properties'}
