#!/usr/bin/env bash
# deps.sh — Startup dependency checks
#
# Validates that all hard dependencies are present before any command runs.
# Sourced early in the speed entrypoint (after config.sh + log.sh).
#
# Checks: bash version, git, jq, timeout/gtimeout, python3 + core packages,
#          agent provider (claude/codex), platform-native grammars.

# ── Helpers ──────────────────────────────────────────────────────

_deps_os=""
_deps_distro=""

_detect_os() {
    [[ -n "$_deps_os" ]] && return 0
    _deps_os="$(uname -s)"
    if [[ "$_deps_os" == "Linux" && -f /etc/os-release ]]; then
        _deps_distro="$(. /etc/os-release && echo "${ID:-unknown}")"
    fi
}

# Return a platform-specific install command for the given package(s).
# Appends context in parentheses when relevant.
_install_hint() {
    local pkg="$1"
    local note="${2:-}"
    _detect_os

    local cmd=""
    case "$_deps_os" in
        Darwin)
            cmd="brew install ${pkg}"
            ;;
        Linux)
            case "$_deps_distro" in
                ubuntu|debian|pop|linuxmint|elementary|zorin)
                    cmd="sudo apt-get install -y ${pkg}" ;;
                fedora)
                    cmd="sudo dnf install -y ${pkg}" ;;
                rhel|centos|rocky|alma|ol)
                    cmd="sudo yum install -y ${pkg}" ;;
                arch|manjaro|endeavouros)
                    cmd="sudo pacman -S ${pkg}" ;;
                opensuse*|sles)
                    cmd="sudo zypper install ${pkg}" ;;
                alpine)
                    cmd="sudo apk add ${pkg}" ;;
                *)
                    # Best-effort: probe for the binary
                    if command -v apt-get &>/dev/null; then
                        cmd="sudo apt-get install -y ${pkg}"
                    elif command -v dnf &>/dev/null; then
                        cmd="sudo dnf install -y ${pkg}"
                    elif command -v yum &>/dev/null; then
                        cmd="sudo yum install -y ${pkg}"
                    elif command -v pacman &>/dev/null; then
                        cmd="sudo pacman -S ${pkg}"
                    elif command -v zypper &>/dev/null; then
                        cmd="sudo zypper install ${pkg}"
                    elif command -v apk &>/dev/null; then
                        cmd="sudo apk add ${pkg}"
                    else
                        cmd="Install '${pkg}' via your distribution's package manager"
                    fi
                    ;;
            esac
            ;;
        *)
            cmd="Install '${pkg}' for your platform"
            ;;
    esac

    if [[ -n "$note" ]]; then
        echo "${cmd}   (${note})"
    else
        echo "$cmd"
    fi
}

_platform_ext() {
    case "$(uname -s)" in
        Darwin) echo "dylib" ;;
        Linux)  echo "so" ;;
        *)      echo "so" ;;
    esac
}

# ── Shared helpers ───────────────────────────────────────────────

# Resolve the Python binary once. Every check that needs Python calls this.
_deps_python=""

_resolve_python() {
    [[ -n "$_deps_python" ]] && return 0
    if [[ -n "${SPEED_PYTHON:-}" ]]; then
        _deps_python="$SPEED_PYTHON"
    elif [[ -x "${SPEED_DIR}/.venv/bin/python3" ]]; then
        _deps_python="${SPEED_DIR}/.venv/bin/python3"
    elif [[ -x "${PROJECT_ROOT}/.venv/bin/python3" ]]; then
        _deps_python="${PROJECT_ROOT}/.venv/bin/python3"
    elif command -v python3 &>/dev/null; then
        _deps_python="$(command -v python3)"
    fi
}

# Resolve the ast-grep binary once. Avoids /usr/bin/sg (the system
# switch-group setuid tool on Linux) which shadows pip's sg shim.
_deps_ast_grep=""

_resolve_ast_grep() {
    [[ -n "$_deps_ast_grep" ]] && return 0

    # 1. ast-grep on PATH — unambiguous, no system collision
    if command -v ast-grep &>/dev/null; then
        _deps_ast_grep="$(command -v ast-grep)"
        return 0
    fi

    # 2. Venv bin dir (SPEED runs venv Python without activating it)
    _resolve_python
    if [[ -n "$_deps_python" ]]; then
        local py_bin_dir
        py_bin_dir="$(dirname "$_deps_python")"
        if [[ -x "${py_bin_dir}/ast-grep" ]]; then
            _deps_ast_grep="${py_bin_dir}/ast-grep"
            return 0
        fi
        if [[ -x "${py_bin_dir}/sg" ]]; then
            _deps_ast_grep="${py_bin_dir}/sg"
            return 0
        fi
    fi

    # 3. sg on PATH — only if it's actually ast-grep (has a scan subcommand)
    local sg_candidate
    sg_candidate=$(command -v sg 2>/dev/null) || true
    if [[ -n "$sg_candidate" ]] && "$sg_candidate" scan --help &>/dev/null; then
        _deps_ast_grep="$sg_candidate"
        return 0
    fi

    return 1
}

# ── Individual checks ────────────────────────────────────────────

_check_bash_version() {
    local current="${BASH_VERSION%%(*}"
    current="${current%%-*}"
    local min="4.3"

    local IFS='.'
    local cur=($current) req=($min)
    for ((i = 0; i < ${#req[@]}; i++)); do
        local c="${cur[i]:-0}" r="${req[i]:-0}"
        if ((c > r)); then return 0; fi
        if ((c < r)); then
            _detect_os
            local fix
            case "$_deps_os" in
                Darwin) fix="brew install bash   (then add /opt/homebrew/bin/bash to /etc/shells and restart your terminal)" ;;
                *)      fix="$(_install_hint bash)" ;;
            esac
            log_error_block \
                "bash ${current} is too old (need >= ${min})" \
                "SPEED uses associative arrays and namerefs that require bash 4.3+" \
                "$fix"
            return 1
        fi
    done
}

_check_git() {
    command -v git &>/dev/null && return 0
    _detect_os
    local fix
    case "$_deps_os" in
        Darwin) fix="xcode-select --install   (installs git with Apple Command Line Tools)" ;;
        *)      fix="$(_install_hint git)" ;;
    esac
    log_error_block \
        "git is not installed" \
        "Every SPEED command requires git for worktrees, diffs, and branches" \
        "$fix"
    return 1
}

_check_jq() {
    command -v jq &>/dev/null && return 0
    log_error_block \
        "jq is not installed" \
        "SPEED uses jq for all JSON processing (tasks, gates, events, roster)" \
        "$(_install_hint jq)"
    return 1
}

_check_timeout() {
    command -v timeout &>/dev/null && return 0
    command -v gtimeout &>/dev/null && return 0
    _detect_os
    local fix
    case "$_deps_os" in
        Darwin) fix="$(_install_hint coreutils "provides gtimeout")" ;;
        *)      fix="$(_install_hint coreutils "provides the timeout command")" ;;
    esac
    log_error_block \
        "Cannot find 'timeout' or 'gtimeout'" \
        "SPEED requires GNU timeout to enforce agent time limits" \
        "$fix"
    return 1
}

_check_python() {
    _resolve_python
    local py="$_deps_python"

    if [[ -z "$py" ]]; then
        _detect_os
        local fix
        local uv_install="curl -LsSf https://astral.sh/uv/install.sh | sh && uv python install 3.12"
        case "$_deps_os" in
            Darwin)
                fix="brew install python@3.12   OR   ${uv_install}" ;;
            Linux)
                case "$_deps_distro" in
                    ubuntu|debian|pop|linuxmint)
                        fix="sudo apt-get install -y python3 python3-venv python3-pip   OR   ${uv_install}" ;;
                    fedora)
                        fix="sudo dnf install -y python3 python3-pip   OR   ${uv_install}" ;;
                    rhel|centos|rocky|alma|ol)
                        fix="sudo yum install -y python3 python3-pip   OR   ${uv_install}" ;;
                    arch|manjaro|endeavouros)
                        fix="sudo pacman -S python python-pip   OR   ${uv_install}" ;;
                    opensuse*|sles)
                        fix="sudo zypper install python3 python3-pip   OR   ${uv_install}" ;;
                    alpine)
                        fix="sudo apk add python3 py3-pip   OR   ${uv_install}" ;;
                    *)
                        fix="${uv_install}" ;;
                esac
                ;;
            *)
                fix="${uv_install}" ;;
        esac
        log_error_block \
            "python3 not found" \
            "SPEED needs Python 3.12+ for context extraction, grounding, and gates" \
            "$fix"
        return 1
    fi

    if [[ ! -x "$py" ]]; then
        log_error_block \
            "SPEED_PYTHON=${py} does not exist or is not executable" \
            "The configured Python binary is missing. The venv may need rebuilding" \
            "Re-run ./install.sh   OR   uv venv --python 3.12 .venv && uv pip install -r requirements.txt"
        return 1
    fi

    # Verify core packages are importable (catches broken venvs, missing installs,
    # bad dylibs from wrong OS/arch). One subprocess call, ~300ms.
    local import_check
    import_check=$("$py" -c "
import sys, importlib
failed = []
for mod in ['tree_sitter', 'sklearn', 'networkx']:
    try:
        importlib.import_module(mod)
    except ImportError:
        failed.append(mod)
if failed:
    print(','.join(failed))
    sys.exit(1)
" 2>&1) || {
        local missing="${import_check:-unknown}"
        log_error_block \
            "Python packages missing or broken: ${missing}" \
            "Core packages failed to import. The venv may be incomplete or built for a different platform" \
            "${py} -m pip install -r ${SPEED_DIR}/requirements.txt"
        return 1
    }
}

_check_provider() {
    # Provider binary validation moved to lib/provider.sh (after provider
    # file is sourced and PROVIDER_BIN is resolved). Retained as no-op
    # for backward compatibility with scripts that call speed_check_deps().
    return 0
}

_check_agent_files() {
    local agents_dir="${SPEED_DIR}/agents"
    if [[ ! -d "$agents_dir" ]]; then
        log_error_block \
            "Agent definitions directory missing: ${agents_dir}" \
            "SPEED's installation is incomplete — the agents/ directory contains prompt files for every agent role" \
            "Re-clone or re-install SPEED from the repository"
        return 1
    fi

    # Core agents required by speed run / speed plan
    local required=(developer.md architect.md reviewer.md debugger.md supervisor.md)
    local missing=()
    local f
    for f in "${required[@]}"; do
        if [[ ! -f "${agents_dir}/${f}" ]]; then
            missing+=("$f")
        elif [[ ! -r "${agents_dir}/${f}" ]]; then
            log_error_block \
                "Agent file not readable: ${agents_dir}/${f}" \
                "The file exists but cannot be read — check file permissions" \
                "chmod 644 ${agents_dir}/${f}"
            return 1
        fi
    done

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error_block \
            "Missing agent files in ${agents_dir}: ${missing[*]}" \
            "These prompt files are required for speed plan and speed run" \
            "Re-clone or re-install SPEED from the repository"
        return 1
    fi
}

_check_worktree_symlinks() {
    # TOML_WORKTREE_SYMLINKS is set by speed.toml via config.sh eval
    [[ -n "${TOML_WORKTREE_SYMLINKS:-}" ]] || return 0

    local pair bad=()
    for pair in $TOML_WORKTREE_SYMLINKS; do
        local src_rel="${pair##*:}"
        local src_path="${PROJECT_ROOT}/${src_rel}"
        if [[ ! -d "$src_path" ]]; then
            bad+=("$src_rel")
        fi
    done

    if [[ ${#bad[@]} -gt 0 ]]; then
        log_error_block \
            "Worktree symlink sources missing: ${bad[*]}" \
            "speed.toml [worktree.symlinks] references directories that don't exist — ln -s will fail during speed run" \
            "Fix the paths in speed.toml or create the missing directories"
        return 1
    fi
}

_check_python_version() {
    _resolve_python
    local py="$_deps_python"
    [[ -z "$py" ]] && return 0  # _check_python already catches this

    local version
    version=$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1) || return 0

    local major minor
    IFS='.' read -r major minor <<< "$version"

    if (( major < 3 || (major == 3 && minor < 11) )); then
        log_error_block \
            "Python ${version} is too old (need >= 3.11)" \
            "SPEED requires tomllib (3.11+) for config parsing. The language registry crashes without it." \
            "uv python install 3.12 && uv venv .venv && uv pip install -r requirements.txt"
        return 1
    fi
}

_check_data_files() {
    local data_dir="${SPEED_DIR}/lib/context/data"
    local missing=()

    [[ -f "${data_dir}/languages.toml" ]]  || missing+=("languages.toml")
    [[ -f "${data_dir}/extraction.toml" ]] || missing+=("extraction.toml")

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error_block \
            "Missing data files: ${missing[*]}" \
            "The language registry needs these to classify files and determine extraction levels. Without them every file is treated as an asset and nothing gets parsed." \
            "Re-clone or re-install SPEED from the repository"
        return 1
    fi
}

_check_ast_grep() {
    _resolve_ast_grep && return 0

    log_error_block \
        "ast-grep CLI not found" \
        "ast-grep extracts definitions and references from source code. Without it the CSG is empty and context construction produces no symbols." \
        "pip install ast-grep-cli   OR   npm install -g @ast-grep/cli"
    return 1
}

_check_sgconfig() {
    local config="${SPEED_DIR}/sgconfig.yml"
    local ext
    ext=$(_platform_ext)

    if [[ ! -f "$config" ]]; then
        log_error_block \
            "sgconfig.yml not found" \
            "ast-grep needs this file to locate rule directories and custom language grammars" \
            "Re-clone or re-install SPEED from the repository"
        return 1
    fi

    # Validate YAML parses and check structure
    _resolve_python
    local py="$_deps_python"
    [[ -z "$py" ]] && return 0

    local check_result
    check_result=$("$py" -c "
import sys, pathlib
try:
    import yaml
except ImportError:
    # PyYAML not installed; skip deep validation
    sys.exit(0)

config_path = pathlib.Path('${config}')
speed_dir = pathlib.Path('${SPEED_DIR}')
platform_ext = '${ext}'

try:
    config = yaml.safe_load(config_path.read_text())
except Exception as e:
    print(f'YAML parse error: {e}')
    sys.exit(1)

errors = []

# Check ruleDirs
for rd in config.get('ruleDirs', []):
    rd_path = speed_dir / rd
    if not rd_path.is_dir():
        errors.append(f'ruleDirs entry not found: {rd}')

# Check customLanguages grammar files
for lang, spec in config.get('customLanguages', {}).items():
    lib_paths = spec.get('libraryPath', {})
    if not lib_paths:
        continue
    # Find the path for current platform
    found = False
    for platform_key, lib_path in lib_paths.items():
        if lib_path.endswith(f'.{platform_ext}'):
            full = speed_dir / lib_path
            if full.is_file():
                found = True
            else:
                errors.append(f'{lang}: grammar library missing: {lib_path}')
            break
    if not found and not errors:
        errors.append(f'{lang}: no grammar library for .{platform_ext} platform')

if errors:
    print('; '.join(errors))
    sys.exit(1)
" 2>&1) || {
        log_error_block \
            "sgconfig.yml validation failed" \
            "${check_result}" \
            "Check sgconfig.yml and rebuild grammars: ./scripts/build-grammars.sh --clean"
        return 1
    }
}

_check_ast_grep_rules() {
    _resolve_ast_grep || return 0  # _check_ast_grep catches missing binary
    local sg="$_deps_ast_grep"

    local rules_dir="${SPEED_DIR}/lib/context/rules"
    [[ -d "$rules_dir" ]] || return 0

    local broken=()
    local lang_dir

    for lang_dir in "$rules_dir"/*/; do
        [[ -d "$lang_dir" ]] || continue
        # Skip directories with no .yml files
        local has_yml=false
        for f in "$lang_dir"*.yml; do
            [[ -f "$f" ]] && has_yml=true && break
        done
        $has_yml || continue

        local lang
        lang=$(basename "$lang_dir")

        local rule_file
        local config="${SPEED_DIR}/sgconfig.yml"
        for rule_file in "$lang_dir"*.yml; do
            [[ -f "$rule_file" ]] || continue
            local probe_output
            # --config needed so ast-grep can resolve custom language grammars
            # (prisma, graphql, protobuf, zig) regardless of working directory
            if [[ -f "$config" ]]; then
                probe_output=$("$sg" scan --config "$config" --rule "$rule_file" --json /dev/null 2>&1)
            else
                probe_output=$("$sg" scan --rule "$rule_file" --json /dev/null 2>&1)
            fi
            local rc=$?
            if (( rc != 0 )); then
                local err_line
                err_line=$(echo "$probe_output" | head -1)
                broken+=("${lang}/$(basename "$rule_file"): ${err_line}")
                break  # one broken file is enough to report the language
            fi
        done
    done

    if [[ ${#broken[@]} -gt 0 ]]; then
        local details
        details=$(printf '  %s\n' "${broken[@]}")
        log_error_block \
            "${#broken[@]} language(s) have broken ast-grep rules" \
            "ast-grep cannot load these rules. Extraction for ALL languages fails when any rule is broken:
${details}" \
            "Fix the rule YAML files in ${rules_dir}/ or remove the broken language directories"
        return 1
    fi
}

_check_tree_sitter_grammars() {
    _resolve_python
    local py="$_deps_python"
    [[ -z "$py" ]] && return 0

    local check_result
    check_result=$("$py" -c "
import sys, importlib, pathlib
try:
    import tomllib
except ImportError:
    sys.exit(0)  # _check_python_version catches this
try:
    import yaml
except ImportError:
    yaml = None

extraction_path = pathlib.Path('${SPEED_DIR}/lib/context/data/extraction.toml')
if not extraction_path.exists():
    sys.exit(0)  # _check_data_files catches this

config = tomllib.loads(extraction_path.read_text())

# Languages registered as customLanguages in sgconfig.yml use ast-grep's
# bundled grammars, not Python tree-sitter packages. Skip them.
custom_langs = set()
sgconfig_path = pathlib.Path('${SPEED_DIR}/sgconfig.yml')
if yaml and sgconfig_path.exists():
    try:
        sg = yaml.safe_load(sgconfig_path.read_text())
        custom_langs = set(sg.get('customLanguages', {}).keys())
    except Exception:
        pass

# Default grammar module: tree_sitter_{language}
# Some languages override via grammar_module key
missing = []
for lang, spec in config.items():
    if not isinstance(spec, dict):
        continue
    if lang in custom_langs:
        continue
    level = spec.get('extraction', 'none')
    if level not in ('rules', 'skeleton'):
        continue
    mod_name = spec.get('grammar_module', f'tree_sitter_{lang}')
    try:
        importlib.import_module(mod_name)
    except ImportError:
        missing.append(f'{lang} ({mod_name})')

if missing:
    print(','.join(missing))
    sys.exit(1)
" 2>&1) || {
        log_error_block \
            "tree-sitter grammars missing: ${check_result}" \
            "These languages cannot be parsed for skeletons or definitions. Files in these languages will be silently skipped." \
            "${_deps_python} -m pip install ${check_result//,/ }"
        return 1
    }
}

# ── Main gate ────────────────────────────────────────────────────

speed_check_deps() {
    local fail=0

    _check_bash_version          || fail=1
    _check_git                   || fail=1
    _check_jq                    || fail=1
    _check_timeout               || fail=1
    _check_python                || fail=1
    _check_python_version        || fail=1
    _check_provider              || fail=1
    _check_agent_files           || fail=1
    _check_worktree_symlinks     || fail=1
    _check_data_files            || fail=1
    _check_ast_grep              || fail=1
    _check_sgconfig              || fail=1
    _check_ast_grep_rules        || fail=1
    _check_tree_sitter_grammars  || fail=1

    if (( fail )); then
        exit "$EXIT_CONFIG_ERROR"
    fi
}

speed_check_deps
