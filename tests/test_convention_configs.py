"""Tests for _extract_config_conventions in lib/learn/convention_configs.py.

Uses pytest's tmp_path fixture for synthetic config files and caplog
for verifying warning behaviour on malformed inputs.
Covers pyproject.toml, .editorconfig, .eslintrc.json, .prettierrc,
tsconfig.json, .flake8, setup.cfg, biome.json, .golangci.yml,
clippy.toml, checkstyle.xml, pmd.xml, .rubocop.yml, .clang-format,
.clang-tidy, stylecop.json, .shellcheckrc, and cross-cutting invariants.
"""

import json
import logging
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.learn.convention_configs import _extract_config_conventions


# ══════════════════════════════════════════════════════════════
# pyproject.toml
# ══════════════════════════════════════════════════════════════


def test_pyproject_ruff_select_I_yields_import_ordering(tmp_path):
    """[tool.ruff] select=['I'] → import ordering convention."""
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\nselect = ["I"]\n', encoding="utf-8"
    )
    entries = _extract_config_conventions(tmp_path)
    assert any("import ordering" in e.convention for e in entries)


def test_pyproject_ruff_select_N_yields_naming(tmp_path):
    """[tool.ruff] select=['N'] → naming convention."""
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\nselect = ["N"]\n', encoding="utf-8"
    )
    entries = _extract_config_conventions(tmp_path)
    assert any("naming" in e.convention.lower() for e in entries)


def test_pyproject_black_line_length(tmp_path):
    """[tool.black] line-length=88 → line length convention."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.black]\nline-length = 88\n", encoding="utf-8"
    )
    entries = _extract_config_conventions(tmp_path)
    assert any("88" in e.convention for e in entries)


def test_pyproject_malformed_toml_warns_empty(tmp_path, caplog):
    """Malformed TOML → warning logged, empty result."""
    (tmp_path / "pyproject.toml").write_text(
        "[invalid toml\nno closing bracket", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING):
        entries = _extract_config_conventions(tmp_path)
    assert entries == []
    assert any("pyproject.toml" in msg for msg in caplog.messages)


def test_pyproject_empty_returns_empty(tmp_path):
    """Empty pyproject.toml → no entries, no error."""
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert entries == []


# ══════════════════════════════════════════════════════════════
# .editorconfig
# ══════════════════════════════════════════════════════════════


def test_editorconfig_indent_style_space(tmp_path):
    """indent_style=space → spaces indentation convention."""
    (tmp_path / ".editorconfig").write_text(
        "[*]\nindent_style = space\n", encoding="utf-8"
    )
    entries = _extract_config_conventions(tmp_path)
    assert any("spaces" in e.convention.lower() for e in entries)


def test_editorconfig_indent_size_4(tmp_path):
    """indent_size=4 → indent-with-4-spaces convention."""
    (tmp_path / ".editorconfig").write_text(
        "[*]\nindent_size = 4\n", encoding="utf-8"
    )
    entries = _extract_config_conventions(tmp_path)
    assert any("4" in e.convention for e in entries)


def test_editorconfig_multiple_sections_produce_separate_entries(tmp_path):
    """Multiple file-glob sections → distinct convention entries per section."""
    (tmp_path / ".editorconfig").write_text(
        "[*.py]\nindent_style = space\n\n[*.js]\nindent_style = tab\n",
        encoding="utf-8",
    )
    entries = _extract_config_conventions(tmp_path)
    scopes = [e.scope for e in entries]
    assert any("*.py" in s for s in scopes), "expected *.py scope"
    assert any("*.js" in s for s in scopes), "expected *.js scope"
    assert len(entries) >= 2


# ══════════════════════════════════════════════════════════════
# .eslintrc.json
# ══════════════════════════════════════════════════════════════


def test_eslintrc_naming_convention_rule(tmp_path):
    """naming-convention rule → naming convention entry."""
    config = {"rules": {"naming-convention": "error"}}
    (tmp_path / ".eslintrc.json").write_text(json.dumps(config), encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert any("naming" in e.convention.lower() for e in entries)


def test_eslintrc_malformed_json_warns_empty(tmp_path, caplog):
    """Malformed JSON in .eslintrc.json → warning logged, no entries."""
    (tmp_path / ".eslintrc.json").write_text("{broken json{{", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        entries = _extract_config_conventions(tmp_path)
    assert entries == []
    assert any(".eslintrc.json" in msg for msg in caplog.messages)


# ══════════════════════════════════════════════════════════════
# .prettierrc
# ══════════════════════════════════════════════════════════════


def test_prettierrc_single_quote_true(tmp_path):
    """singleQuote: true → single-quotes formatting convention."""
    (tmp_path / ".prettierrc").write_text(
        json.dumps({"singleQuote": True}), encoding="utf-8"
    )
    entries = _extract_config_conventions(tmp_path)
    assert any("single" in e.convention.lower() for e in entries)


def test_prettierrc_semi_false(tmp_path):
    """semi: false → omit-semicolons convention."""
    (tmp_path / ".prettierrc").write_text(
        json.dumps({"semi": False}), encoding="utf-8"
    )
    entries = _extract_config_conventions(tmp_path)
    assert any(
        "semi" in e.convention.lower() or "semicolon" in e.convention.lower()
        for e in entries
    )


# ══════════════════════════════════════════════════════════════
# tsconfig.json
# ══════════════════════════════════════════════════════════════


def test_tsconfig_strict_true(tmp_path):
    """compilerOptions.strict: true → strict mode convention."""
    config = {"compilerOptions": {"strict": True}}
    (tmp_path / "tsconfig.json").write_text(json.dumps(config), encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert any("strict" in e.convention.lower() for e in entries)


def test_tsconfig_path_aliases(tmp_path):
    """compilerOptions.paths → path alias convention listing alias count."""
    config = {
        "compilerOptions": {
            "paths": {
                "@app/*": ["src/*"],
                "@lib/*": ["lib/*"],
            }
        }
    }
    (tmp_path / "tsconfig.json").write_text(json.dumps(config), encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert any("alias" in e.convention.lower() for e in entries)


# ══════════════════════════════════════════════════════════════
# Cross-cutting invariants
# ══════════════════════════════════════════════════════════════


def test_no_config_files_returns_empty_no_error(tmp_path):
    """Empty project directory → empty list, no exception."""
    entries = _extract_config_conventions(tmp_path)
    assert entries == []


def test_all_entries_source_is_config(tmp_path):
    """Every returned entry has source='config'."""
    (tmp_path / ".editorconfig").write_text(
        "[*]\nindent_style = space\n", encoding="utf-8"
    )
    entries = _extract_config_conventions(tmp_path)
    assert entries
    assert all(e.source == "config" for e in entries)


def test_all_entries_confidence_is_established(tmp_path):
    """Every returned entry has confidence='established'."""
    (tmp_path / ".editorconfig").write_text(
        "[*]\nindent_size = 2\n", encoding="utf-8"
    )
    entries = _extract_config_conventions(tmp_path)
    assert entries
    assert all(e.confidence == "established" for e in entries)


def test_all_entries_canonical_example_is_config_file_path(tmp_path):
    """canonical_example equals the string path of the config file that produced it."""
    config_file = tmp_path / ".prettierrc"
    config_file.write_text(json.dumps({"tabWidth": 2}), encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert entries
    assert all(e.canonical_example == str(config_file) for e in entries)


def test_all_entry_ids_start_with_conv(tmp_path):
    """All entry IDs start with 'conv-'."""
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\nselect = ["I", "N"]\n', encoding="utf-8"
    )
    entries = _extract_config_conventions(tmp_path)
    assert entries
    assert all(e.id.startswith("conv-") for e in entries)


# ══════════════════════════════════════════════════════════════
# .flake8
# ══════════════════════════════════════════════════════════════


def test_flake8_max_line_length(tmp_path):
    """[flake8] max-line-length=120 → line length convention."""
    (tmp_path / ".flake8").write_text(
        "[flake8]\nmax-line-length = 120\n", encoding="utf-8"
    )
    entries = _extract_config_conventions(tmp_path)
    assert any("120" in e.convention for e in entries)
    assert all(e.source == "config" for e in entries)
    assert all(e.confidence == "established" for e in entries)


def test_flake8_malformed_ini_warns_empty(tmp_path, caplog):
    """Malformed INI in .flake8 → warning logged, no entries."""
    (tmp_path / ".flake8").write_text(
        "[flake8\nno closing bracket\n\x00\x01binary junk", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING):
        entries = _extract_config_conventions(tmp_path)
    assert entries == []
    assert any(".flake8" in msg for msg in caplog.messages)


def test_flake8_empty_returns_empty(tmp_path):
    """Empty .flake8 → no entries, no error."""
    (tmp_path / ".flake8").write_text("", encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert entries == []


# ══════════════════════════════════════════════════════════════
# setup.cfg
# ══════════════════════════════════════════════════════════════


def test_setup_cfg_flake8_ignore_rules(tmp_path):
    """[flake8] ignore=E501,W503 in setup.cfg → ignored rules convention."""
    (tmp_path / "setup.cfg").write_text(
        "[flake8]\nignore = E501,W503\n", encoding="utf-8"
    )
    entries = _extract_config_conventions(tmp_path)
    assert any("E501" in e.convention for e in entries)
    assert all(e.source == "config" for e in entries)
    assert all(e.confidence == "established" for e in entries)


def test_setup_cfg_malformed_ini_warns_empty(tmp_path, caplog):
    """Malformed INI in setup.cfg → warning logged, no entries."""
    (tmp_path / "setup.cfg").write_text(
        "[flake8\nno closing bracket\n\x00\x01binary junk", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING):
        entries = _extract_config_conventions(tmp_path)
    assert entries == []
    assert any("setup.cfg" in msg for msg in caplog.messages)


def test_setup_cfg_empty_returns_empty(tmp_path):
    """Empty setup.cfg → no entries, no error."""
    (tmp_path / "setup.cfg").write_text("", encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert entries == []


# ══════════════════════════════════════════════════════════════
# biome.json
# ══════════════════════════════════════════════════════════════


def test_biome_json_indent_style(tmp_path):
    """biome.json formatter.indentStyle=space → spaces indentation convention."""
    config = {"formatter": {"indentStyle": "space", "indentWidth": 2}}
    (tmp_path / "biome.json").write_text(json.dumps(config), encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert any("spaces" in e.convention.lower() for e in entries)
    assert all(e.source == "config" for e in entries)
    assert all(e.confidence == "established" for e in entries)


def test_biome_json_malformed_warns_empty(tmp_path, caplog):
    """Malformed JSON in biome.json → warning logged, no entries."""
    (tmp_path / "biome.json").write_text("{broken json{{", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        entries = _extract_config_conventions(tmp_path)
    assert entries == []
    assert any("biome.json" in msg for msg in caplog.messages)


def test_biome_json_empty_returns_empty(tmp_path):
    """Empty biome.json → no entries, no error."""
    (tmp_path / "biome.json").write_text("", encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert entries == []


# ══════════════════════════════════════════════════════════════
# .golangci.yml
# ══════════════════════════════════════════════════════════════


def test_golangci_yml_enabled_linters(tmp_path):
    """.golangci.yml with enabled linters → linting convention."""
    (tmp_path / ".golangci.yml").write_text(
        "linters:\n  enable:\n    - govet\n    - errcheck\n", encoding="utf-8"
    )
    entries = _extract_config_conventions(tmp_path)
    assert any("govet" in e.convention for e in entries)
    assert all(e.source == "config" for e in entries)
    assert all(e.confidence == "established" for e in entries)


def test_golangci_yml_malformed_warns_empty(tmp_path, caplog):
    """Malformed YAML in .golangci.yml → warning logged, no entries."""
    (tmp_path / ".golangci.yml").write_text(
        "linters:\n  enable:\n- broken\n  : bad: yaml: {{{\n", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING):
        entries = _extract_config_conventions(tmp_path)
    assert entries == []
    assert any(".golangci.yml" in msg for msg in caplog.messages)


def test_golangci_yml_empty_returns_empty(tmp_path):
    """Empty .golangci.yml → no entries, no error."""
    (tmp_path / ".golangci.yml").write_text("", encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert entries == []


# ══════════════════════════════════════════════════════════════
# clippy.toml
# ══════════════════════════════════════════════════════════════


def test_clippy_toml_msrv(tmp_path):
    """clippy.toml with msrv → minimum Rust version convention."""
    (tmp_path / "clippy.toml").write_text(
        'msrv = "1.70.0"\n', encoding="utf-8"
    )
    entries = _extract_config_conventions(tmp_path)
    assert any("1.70.0" in e.convention for e in entries)
    assert all(e.source == "config" for e in entries)
    assert all(e.confidence == "established" for e in entries)


def test_clippy_toml_malformed_warns_empty(tmp_path, caplog):
    """Malformed TOML in clippy.toml → warning logged, no entries."""
    (tmp_path / "clippy.toml").write_text(
        "[invalid toml\nno closing bracket", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING):
        entries = _extract_config_conventions(tmp_path)
    assert entries == []
    assert any("clippy.toml" in msg for msg in caplog.messages)


def test_clippy_toml_empty_returns_empty(tmp_path):
    """Empty clippy.toml → no entries, no error."""
    (tmp_path / "clippy.toml").write_text("", encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert entries == []


# ══════════════════════════════════════════════════════════════
# checkstyle.xml
# ══════════════════════════════════════════════════════════════


def test_checkstyle_xml_naming_module(tmp_path):
    """checkstyle.xml with NamingConventions module → naming convention."""
    (tmp_path / "checkstyle.xml").write_text(
        '<?xml version="1.0"?>\n'
        '<module name="Checker">\n'
        '  <module name="TreeWalker">\n'
        '    <module name="LocalVariableNaming">\n'
        '      <property name="format" value="^[a-z][a-zA-Z0-9]*$"/>\n'
        '    </module>\n'
        '  </module>\n'
        '</module>\n',
        encoding="utf-8",
    )
    entries = _extract_config_conventions(tmp_path)
    assert any("naming" in e.convention.lower() for e in entries)
    assert all(e.source == "config" for e in entries)
    assert all(e.confidence == "established" for e in entries)


def test_checkstyle_xml_malformed_warns_empty(tmp_path, caplog):
    """Malformed XML in checkstyle.xml → warning logged, no entries."""
    (tmp_path / "checkstyle.xml").write_text(
        "<module name='Checker'><unclosed", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING):
        entries = _extract_config_conventions(tmp_path)
    assert entries == []
    assert any("checkstyle.xml" in msg for msg in caplog.messages)


def test_checkstyle_xml_empty_returns_empty(tmp_path):
    """Empty checkstyle.xml → no entries, no error."""
    (tmp_path / "checkstyle.xml").write_text("", encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert entries == []


# ══════════════════════════════════════════════════════════════
# pmd.xml
# ══════════════════════════════════════════════════════════════


def test_pmd_xml_naming_rule(tmp_path):
    """pmd.xml with naming rule reference → naming convention."""
    (tmp_path / "pmd.xml").write_text(
        '<?xml version="1.0"?>\n'
        '<ruleset name="Custom">\n'
        '  <rule ref="category/java/codestyle/naming/ShortClassName"/>\n'
        '</ruleset>\n',
        encoding="utf-8",
    )
    entries = _extract_config_conventions(tmp_path)
    assert any("naming" in e.convention.lower() for e in entries)
    assert all(e.source == "config" for e in entries)
    assert all(e.confidence == "established" for e in entries)


def test_pmd_xml_malformed_warns_empty(tmp_path, caplog):
    """Malformed XML in pmd.xml → warning logged, no entries."""
    (tmp_path / "pmd.xml").write_text(
        "<ruleset><unclosed rule", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING):
        entries = _extract_config_conventions(tmp_path)
    assert entries == []
    assert any("pmd.xml" in msg for msg in caplog.messages)


def test_pmd_xml_empty_returns_empty(tmp_path):
    """Empty pmd.xml → no entries, no error."""
    (tmp_path / "pmd.xml").write_text("", encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert entries == []


# ══════════════════════════════════════════════════════════════
# .rubocop.yml
# ══════════════════════════════════════════════════════════════


def test_rubocop_yml_naming_cop(tmp_path):
    """.rubocop.yml with Naming/ cop → naming convention."""
    (tmp_path / ".rubocop.yml").write_text(
        "Naming/MethodName:\n  Enabled: true\n", encoding="utf-8"
    )
    entries = _extract_config_conventions(tmp_path)
    assert any("Naming/MethodName" in e.convention for e in entries)
    assert all(e.source == "config" for e in entries)
    assert all(e.confidence == "established" for e in entries)


def test_rubocop_yml_malformed_warns_empty(tmp_path, caplog):
    """Malformed YAML in .rubocop.yml → warning logged, no entries."""
    (tmp_path / ".rubocop.yml").write_text(
        "Naming/MethodName:\n  Enabled: true\n- broken\n  : bad: yaml: {{{\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING):
        entries = _extract_config_conventions(tmp_path)
    assert entries == []
    assert any(".rubocop.yml" in msg for msg in caplog.messages)


def test_rubocop_yml_empty_returns_empty(tmp_path):
    """Empty .rubocop.yml → no entries, no error."""
    (tmp_path / ".rubocop.yml").write_text("", encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert entries == []


# ══════════════════════════════════════════════════════════════
# .clang-format
# ══════════════════════════════════════════════════════════════


def test_clang_format_base_style(tmp_path):
    """.clang-format with BasedOnStyle → base style convention."""
    (tmp_path / ".clang-format").write_text(
        "BasedOnStyle: LLVM\nIndentWidth: 4\n", encoding="utf-8"
    )
    entries = _extract_config_conventions(tmp_path)
    assert any("LLVM" in e.convention for e in entries)
    assert all(e.source == "config" for e in entries)
    assert all(e.confidence == "established" for e in entries)


def test_clang_format_malformed_warns_empty(tmp_path, caplog):
    """Malformed YAML in .clang-format → warning logged, no entries."""
    (tmp_path / ".clang-format").write_text(
        "BasedOnStyle: LLVM\n- broken\n  : bad: yaml: {{{\n", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING):
        entries = _extract_config_conventions(tmp_path)
    assert entries == []
    assert any(".clang-format" in msg for msg in caplog.messages)


def test_clang_format_empty_returns_empty(tmp_path):
    """Empty .clang-format → no entries, no error."""
    (tmp_path / ".clang-format").write_text("", encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert entries == []


# ══════════════════════════════════════════════════════════════
# .clang-tidy
# ══════════════════════════════════════════════════════════════


def test_clang_tidy_checks(tmp_path):
    """.clang-tidy with Checks → linting convention."""
    (tmp_path / ".clang-tidy").write_text(
        "Checks: 'modernize-*,readability-*'\n", encoding="utf-8"
    )
    entries = _extract_config_conventions(tmp_path)
    assert any("modernize" in e.convention for e in entries)
    assert all(e.source == "config" for e in entries)
    assert all(e.confidence == "established" for e in entries)


def test_clang_tidy_malformed_warns_empty(tmp_path, caplog):
    """Malformed YAML in .clang-tidy → warning logged, no entries."""
    (tmp_path / ".clang-tidy").write_text(
        "Checks: 'modernize-*'\n- broken\n  : bad: yaml: {{{\n", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING):
        entries = _extract_config_conventions(tmp_path)
    assert entries == []
    assert any(".clang-tidy" in msg for msg in caplog.messages)


def test_clang_tidy_empty_returns_empty(tmp_path):
    """Empty .clang-tidy → no entries, no error."""
    (tmp_path / ".clang-tidy").write_text("", encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert entries == []


# ══════════════════════════════════════════════════════════════
# stylecop.json
# ══════════════════════════════════════════════════════════════


def test_stylecop_json_naming_rules(tmp_path):
    """stylecop.json with naming rules → naming convention."""
    config = {"settings": {"namingRules": {"allowCommonHungarianPrefixes": True}}}
    (tmp_path / "stylecop.json").write_text(json.dumps(config), encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert any("naming" in e.convention.lower() for e in entries)
    assert all(e.source == "config" for e in entries)
    assert all(e.confidence == "established" for e in entries)


def test_stylecop_json_malformed_warns_empty(tmp_path, caplog):
    """Malformed JSON in stylecop.json → warning logged, no entries."""
    (tmp_path / "stylecop.json").write_text("{broken json{{", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        entries = _extract_config_conventions(tmp_path)
    assert entries == []
    assert any("stylecop.json" in msg for msg in caplog.messages)


def test_stylecop_json_empty_returns_empty(tmp_path):
    """Empty stylecop.json → no entries, no error."""
    (tmp_path / "stylecop.json").write_text("", encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert entries == []


# ══════════════════════════════════════════════════════════════
# .shellcheckrc
# ══════════════════════════════════════════════════════════════


def test_shellcheckrc_disable_rules(tmp_path):
    """.shellcheckrc with disable= → disabled rules convention."""
    (tmp_path / ".shellcheckrc").write_text(
        "disable=SC2034,SC2086\n", encoding="utf-8"
    )
    entries = _extract_config_conventions(tmp_path)
    assert any("SC2034" in e.convention for e in entries)
    assert all(e.source == "config" for e in entries)
    assert all(e.confidence == "established" for e in entries)


def test_shellcheckrc_malformed_returns_empty(tmp_path):
    """Unrecognized lines in .shellcheckrc → no entries, no crash.

    The shellcheckrc parser is line-based and silently skips
    unrecognized directives, so no warning is logged.
    """
    (tmp_path / ".shellcheckrc").write_text(
        "not_a_real_directive = something\n"
        "another garbage line\n"
        "{{{{ totally broken\n",
        encoding="utf-8",
    )
    entries = _extract_config_conventions(tmp_path)
    assert entries == []


def test_shellcheckrc_empty_returns_empty(tmp_path):
    """Empty .shellcheckrc → no entries, no error."""
    (tmp_path / ".shellcheckrc").write_text("", encoding="utf-8")
    entries = _extract_config_conventions(tmp_path)
    assert entries == []
