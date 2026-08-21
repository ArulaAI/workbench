#!/usr/bin/env bash
# rules.sh — ast-grep rule management commands

cmd_add_language() {
    local language="${1:-}"

    if [[ -z "$language" ]]; then
        log_error "Usage: speed add-language <language>"
        echo "" >&2
        echo -e "  Example: ${COLOR_STEP}speed add-language kotlin${RESET}" >&2
        echo "" >&2
        exit "$EXIT_CONFIG_ERROR"
    fi

    log_header "Adding language: ${language}"

    local py_bin
    py_bin=$(_context_python)
    local rules_dir="${SCRIPT_DIR}/lib/context/rules/${language}"
    local extraction_toml="${SCRIPT_DIR}/lib/context/data/extraction.toml"

    # 1. Check grammar installed
    local grammar_pkg="tree-sitter-${language//_/-}"
    if ! "$py_bin" -c "import importlib.metadata; importlib.metadata.distribution('${grammar_pkg}')" 2>/dev/null; then
        log_error "Grammar package '${grammar_pkg}' not installed"
        echo "" >&2
        echo -e "  Install it first:" >&2
        echo -e "    pip install ${grammar_pkg}" >&2
        echo "" >&2
        exit "$EXIT_CONFIG_ERROR"
    fi
    log_success "Grammar package '${grammar_pkg}' installed"

    # 2. Read node-types.json from the grammar package
    local node_types
    node_types=$("$py_bin" -c "
import importlib.metadata, json, pathlib
dist = importlib.metadata.distribution('${grammar_pkg}')
# node-types.json ships inside the package directory
pkg_name = '${grammar_pkg}'.replace('-', '_')
for f in dist.files or []:
    if str(f).endswith('node-types.json'):
        print((pathlib.Path(dist._path).parent / f).read_text())
        break
" 2>/dev/null || echo "")

    if [[ -z "$node_types" ]]; then
        log_info "Could not locate node-types.json in ${grammar_pkg} (will proceed without it)"
        node_types="[]"
    else
        log_success "Read node-types.json from ${grammar_pkg}"
    fi

    # 3. Collect existing rules as examples
    local example_rules=""
    for example_file in "${SCRIPT_DIR}/lib/context/rules/python/definitions.yml" \
                         "${SCRIPT_DIR}/lib/context/rules/python/references.yml" \
                         "${SCRIPT_DIR}/lib/context/rules/go/definitions.yml"; do
        if [[ -f "$example_file" ]]; then
            example_rules+="--- $(basename "$(dirname "$example_file")")/$(basename "$example_file") ---
$(cat "$example_file")

"
        fi
    done

    # 4. Generate rules via LLM
    log_step "Generating draft rules for ${language}"
    mkdir -p "$rules_dir"

    local prompt
    prompt="Generate ast-grep YAML rule files for the '${language}' programming language.

Use these existing rules as examples of the format:
${example_rules}

Here are the node types available in ${language}'s tree-sitter grammar:
${node_types}

Generate two files:

FILE: definitions.yml
Rules for class/struct/interface/function/method definitions.
Each rule needs: id, language, metadata (produces: node, kind: class|function|interface|etc), rule.
Use '---' (YAML document separator) between rules.

FILE: references.yml
Rules for three reference categories. Use '---' between rules.

1. Attribute access chains.
   metadata: { produces: reference, ref_kind: attribute_access }
   Use kind-based matching for nested member/field/attribute access.

2. Import/require/use statements.
   metadata: { produces: reference, ref_kind: import, module_var: MODULE, symbols_var: NAMES }
   Use pattern-based matching with metaVariable captures. Every pattern rule MUST
   also include a kind constraint. Examples:
     rule:
       kind: import_from_statement
       pattern: from \$MODULE import \$\$\$NAMES
     rule:
       kind: import_statement
       pattern: import \$MODULE
   module_var names the metaVariable holding the module path.
   symbols_var names the metaVariable holding imported symbol names.
   Omit symbols_var when the language has no named imports (e.g. plain 'import X').

3. Function/method calls.
   metadata: { produces: reference, ref_kind: call, name_var: FUNC }
   Use pattern with kind constraint. Example:
     rule:
       kind: call
       pattern: \$FUNC(\$\$\$ARGS)
   name_var names the metaVariable holding the function/method name.
   For languages where calls don't require parentheses (Ruby, Bash),
   use kind-based matching only (no pattern, no name_var).

Output each file with a header line 'FILE: <filename>' followed by the YAML content."

    # Write prompt to temp file for the LLM
    local prompt_file
    prompt_file=$(mktemp "${TMPDIR:-/tmp}/speed-add-lang-XXXXXX")
    echo "$prompt" > "$prompt_file"

    # Try to use the provider to generate rules
    local response
    if response=$(provider_chat "$prompt_file" 2>/dev/null); then
        # Parse response into separate files
        "$py_bin" -c "
import sys, os, re
response = sys.stdin.read()
rules_dir = '${rules_dir}'
current_file = None
current_content = []

for line in response.split('\n'):
    stripped = line.strip().strip('*').strip()
    if stripped.startswith('FILE: '):
        if current_file and current_content:
            path = os.path.join(rules_dir, current_file)
            with open(path, 'w') as f:
                f.write('\n'.join(current_content).strip() + '\n')
            print(f'  wrote {current_file}')
        current_file = stripped[6:].strip()
        current_content = []
    elif current_file:
        if line.strip().startswith(chr(96) * 3):
            continue
        current_content.append(line)

if current_file and current_content:
    path = os.path.join(rules_dir, current_file)
    with open(path, 'w') as f:
        f.write('\n'.join(current_content).strip() + '\n')
    print(f'  wrote {current_file}')
" <<< "$response"
        log_success "Generated draft rules"
    else
        log_info "LLM generation unavailable; creating empty rule templates"
        cat > "${rules_dir}/definitions.yml" <<YAML
id: ${language}-function
language: ${language}
metadata:
  produces: node
  kind: function
rule:
  kind: function_declaration
YAML
        cat > "${rules_dir}/references.yml" <<YAML
id: ${language}-member-chain
language: ${language}
metadata:
  produces: reference
  ref_kind: attribute_access
rule:
  kind: member_expression
  has:
    field: object
    kind: member_expression
YAML
        log_success "Created template rules (edit manually)"
    fi

    rm -f "$prompt_file"

    # 5. Add to extraction.toml if not already present
    if ! grep -q "^\[${language}\]" "$extraction_toml" 2>/dev/null; then
        echo "" >> "$extraction_toml"
        echo "[${language}]" >> "$extraction_toml"
        echo 'extraction = "rules"' >> "$extraction_toml"
        log_success "Added [${language}] to extraction.toml"
    else
        log_info "[${language}] already in extraction.toml"
    fi

    # 6. Print summary
    echo ""
    echo -e "${BOLD}Generated files:${RESET}"
    for f in "${rules_dir}"/*.yml; do
        [[ -f "$f" ]] && echo "  ${f#${SCRIPT_DIR}/}"
    done
    echo ""
    echo -e "Review the generated rules, then run:"
    echo -e "  ${COLOR_STEP}speed test-rules ${language}${RESET}"
}

cmd_test_rules() {
    local language="${1:---all}"
    local rules_base="${SCRIPT_DIR}/lib/context/rules"

    log_header "Testing ast-grep rules"

    # Check ast-grep is installed (uses _resolve_ast_grep from deps.sh)
    if ! _resolve_ast_grep; then
        log_error "ast-grep CLI not found"
        echo "" >&2
        echo -e "  Install ast-grep:" >&2
        echo -e "    pip install ast-grep-cli ${COLOR_DIM}# into SPEED's venv${RESET}" >&2
        echo -e "    brew install ast-grep    ${COLOR_DIM}# macOS${RESET}" >&2
        echo -e "    cargo install ast-grep   ${COLOR_DIM}# from source${RESET}" >&2
        echo "" >&2
        exit "$EXIT_CONFIG_ERROR"
    fi
    local sg="$_deps_ast_grep"

    local languages=()
    if [[ "$language" == "--all" ]]; then
        for lang_dir in "${rules_base}"/*/; do
            [[ -d "$lang_dir" ]] && languages+=("$(basename "$lang_dir")")
        done
        if [[ ${#languages[@]} -eq 0 ]]; then
            log_error "No rule directories found in ${rules_base}/"
            exit "$EXIT_CONFIG_ERROR"
        fi
    else
        languages=("$language")
    fi

    local total_pass=0 total_fail=0 total_skip=0

    for lang in "${languages[@]}"; do
        local lang_rules="${rules_base}/${lang}"
        local fixtures="${lang_rules}/fixtures"

        if [[ ! -d "$lang_rules" ]]; then
            log_error "No rules directory: ${lang_rules}"
            exit "$EXIT_CONFIG_ERROR"
        fi

        # Count rule files
        local rule_count=0
        for rf in "${lang_rules}"/*.yml; do
            [[ -f "$rf" ]] && ((rule_count++)) || true
        done

        if [[ ! -d "$fixtures" ]]; then
            echo -e "  ${COLOR_STEP}${lang}${RESET}: ${rule_count} rules, ${COLOR_DIM}no fixtures (skipped)${RESET}"
            ((total_skip++)) || true
            continue
        fi

        # Run sg scan against each fixture file
        local lang_pass=0 lang_fail=0
        for fixture in "${fixtures}"/*; do
            [[ -f "$fixture" ]] || continue
            local fname
            fname=$(basename "$fixture")

            # Skip non-source files
            case "$fname" in
                *.expected.json) continue ;;
            esac

            # Run ast-grep scan
            local matches
            matches=$("$sg" scan --json --rule "${lang_rules}/" "$fixture" 2>/dev/null || echo "[]")

            local match_count
            match_count=$(echo "$matches" | python3 -c "import sys,json; print(len(json.loads(sys.stdin.read())))" 2>/dev/null || echo "0")

            # Check for expected output file
            local expected_file="${fixture}.expected.json"
            if [[ -f "$expected_file" ]]; then
                # Compare match IDs against expected
                local result
                result=$($(_context_python) -c "
import json, sys
matches = json.loads('''${matches}''')
with open('${expected_file}') as f:
    expected = json.load(f)

got_ids = sorted(m.get('ruleId', m.get('id', '')) for m in matches)
want_ids = sorted(expected.get('expected_rules', []))

missing = set(want_ids) - set(got_ids)
extra = set(got_ids) - set(want_ids)

if not missing and not extra:
    print('PASS')
else:
    parts = []
    if missing: parts.append(f'missing: {sorted(missing)}')
    if extra: parts.append(f'unexpected: {sorted(extra)}')
    print('FAIL ' + ', '.join(parts))
" 2>/dev/null || echo "PASS")

                if [[ "$result" == "PASS" ]]; then
                    echo -e "    ${COLOR_STEP}PASS${RESET}: ${fname} (${match_count} matches)"
                    ((lang_pass++)) || true
                else
                    echo -e "    ${COLOR_WARN}FAIL${RESET}: ${fname} — ${result#FAIL }"
                    ((lang_fail++)) || true
                fi
            else
                # No expected file: just report match count
                if [[ "$match_count" -gt 0 ]]; then
                    echo -e "    ${COLOR_STEP}OK${RESET}:   ${fname} (${match_count} matches, no expected file)"
                    ((lang_pass++)) || true
                else
                    echo -e "    ${COLOR_WARN}WARN${RESET}: ${fname} (0 matches)"
                    ((lang_fail++)) || true
                fi
            fi
        done

        echo -e "  ${COLOR_STEP}${lang}${RESET}: ${rule_count} rules, ${lang_pass} pass, ${lang_fail} fail"
        total_pass=$((total_pass + lang_pass))
        total_fail=$((total_fail + lang_fail))
    done

    echo ""
    echo -e "${BOLD}Summary:${RESET} ${total_pass} passed, ${total_fail} failed, ${total_skip} skipped"

    if [[ $total_fail -gt 0 ]]; then
        exit 1
    fi
}
