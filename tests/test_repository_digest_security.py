"""Unit tests for lib/context/repository_digest_security.py — Phase 5A
Security. Heavy focus on secret redaction and false-positive resistance.

Secret-shaped test values below are well-known public *example* values
(AWS's own documented example key, RFC/example-style tokens) — never a
real credential — used specifically to test that the redaction pipeline
strips them regardless.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from lib.context.repository_digest_security import (
    derive_secret_indicators,
    derive_sensitive_configuration,
    derive_authentication_indicators,
    derive_security_tooling,
    MAX_FILE_BYTES,
)


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _project_map(files: list[dict]) -> dict:
    return {"files": files}


# ── Secret indicators: declared-name tier (reused Phase 4 data) ────


class TestSecretIndicatorsDeclaredName:
    def test_sensitive_env_var_becomes_a_declared_name_indicator(self):
        env_vars = [{"name": "OPENAI_API_KEY", "source_file": ".env", "looks_sensitive": True, "evidence": []}]
        indicators, warnings = derive_secret_indicators(Path("."), _project_map([]), env_vars)
        assert indicators[0]["category"] == "declared_name"
        assert indicators[0]["name"] == "OPENAI_API_KEY"
        assert indicators[0]["redacted"] is True

    def test_non_sensitive_env_var_is_not_an_indicator(self):
        env_vars = [{"name": "DATABASE_URL", "source_file": ".env", "looks_sensitive": False, "evidence": []}]
        indicators, _ = derive_secret_indicators(Path("."), _project_map([]), env_vars)
        assert indicators == []

    def test_no_env_vars_returns_no_declared_name_indicators(self):
        indicators, _ = derive_secret_indicators(Path("."), _project_map([]), [])
        assert indicators == []


# ── Secret indicators: hardcoded value pattern tier ────────────────


class TestSecretIndicatorsHardcodedValue:
    def test_aws_access_key_detected_without_leaking_value(self, tmp_path):
        _write(tmp_path, "config.py", 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
        pm = _project_map([{"path": "config.py", "category": "source", "language": "python"}])
        indicators, _ = derive_secret_indicators(tmp_path, pm, [])
        assert len(indicators) == 1
        assert indicators[0]["category"] == "hardcoded_value_pattern"
        assert indicators[0]["pattern_type"] == "aws_access_key_id"
        assert indicators[0]["name"] == "AWS_KEY"
        blob = json.dumps(indicators)
        assert "AKIAIOSFODNN7EXAMPLE" not in blob

    def test_openai_key_detected(self, tmp_path):
        _write(tmp_path, "config.py", 'OPENAI_API_KEY = "sk-abc123def456ghi789jkl012mno345"\n')
        pm = _project_map([{"path": "config.py", "category": "source", "language": "python"}])
        indicators, _ = derive_secret_indicators(tmp_path, pm, [])
        assert indicators[0]["pattern_type"] == "openai_api_key"
        blob = json.dumps(indicators)
        assert "sk-abc123def456ghi789jkl012mno345" not in blob

    def test_private_key_block_detected(self, tmp_path):
        _write(tmp_path, "id_rsa.txt", "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA1234567890\n-----END RSA PRIVATE KEY-----\n")
        pm = _project_map([{"path": "id_rsa.txt", "category": "config", "language": None}])
        indicators, _ = derive_secret_indicators(tmp_path, pm, [])
        assert indicators[0]["pattern_type"] == "private_key_block"
        blob = json.dumps(indicators)
        assert "MIIEpAIBAAKCAQEA1234567890" not in blob

    def test_github_token_detected(self, tmp_path):
        _write(tmp_path, "config.py", 'TOKEN = "ghp_' + "A" * 36 + '"\n')
        pm = _project_map([{"path": "config.py", "category": "source", "language": "python"}])
        indicators, _ = derive_secret_indicators(tmp_path, pm, [])
        assert indicators[0]["pattern_type"] == "github_token"

    def test_oversized_file_is_skipped_with_a_warning_not_silently(self, tmp_path):
        # Code-review finding: a file over MAX_FILE_BYTES was silently
        # excluded from secret scanning with no trace anywhere in the
        # digest — a committed source file that happens to cross this
        # size (a bundled/generated JS file, say) containing a real
        # hardcoded secret would report zero indicators and zero
        # warnings, indistinguishable from "nothing to find here."
        oversized_content = 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n' + ("#" * (MAX_FILE_BYTES + 1))
        _write(tmp_path, "bundle.py", oversized_content)
        pm = _project_map([{"path": "bundle.py", "category": "source", "language": "python"}])
        indicators, warnings = derive_secret_indicators(tmp_path, pm, [])
        assert indicators == []
        assert any("bundle.py" in w and "exceeds" in w for w in warnings), f"warnings={warnings!r}"

    def test_normal_sized_file_produces_no_size_warning(self, tmp_path):
        _write(tmp_path, "config.py", 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
        pm = _project_map([{"path": "config.py", "category": "source", "language": "python"}])
        indicators, warnings = derive_secret_indicators(tmp_path, pm, [])
        assert len(indicators) == 1
        assert warnings == []

    def test_database_url_with_embedded_credentials_detected(self, tmp_path):
        _write(tmp_path, "config.py", 'DB_URL = "postgres://myuser:supersecretpw@dbhost.example.com/mydb"\n')
        pm = _project_map([{"path": "config.py", "category": "source", "language": "python"}])
        indicators, _ = derive_secret_indicators(tmp_path, pm, [])
        assert indicators[0]["pattern_type"] == "database_url_credentials"
        blob = json.dumps(indicators)
        assert "supersecretpw" not in blob
        assert "myuser" not in blob

    def test_password_required_variable_name_is_not_a_false_positive(self, tmp_path):
        # The exact example from the task spec: a variable named
        # PASSWORD_REQUIRED is not itself proof of an exposed secret.
        _write(tmp_path, "config.py", "PASSWORD_REQUIRED = True\n")
        pm = _project_map([{"path": "config.py", "category": "source", "language": "python"}])
        indicators, _ = derive_secret_indicators(tmp_path, pm, [])
        assert indicators == []

    def test_ordinary_source_code_yields_no_indicators(self, tmp_path):
        _write(tmp_path, "app.py", "def add(a, b):\n    return a + b\n")
        pm = _project_map([{"path": "app.py", "category": "source", "language": "python"}])
        indicators, _ = derive_secret_indicators(tmp_path, pm, [])
        assert indicators == []

    def test_generated_lockfiles_are_not_scanned(self, tmp_path):
        # Performance: package-lock.json etc. are machine-generated and
        # structurally cannot contain a hand-written credential — skipped
        # rather than scanned, per profiling on the real repository.
        _write(tmp_path, "package-lock.json", '{"AWS_KEY": "AKIAIOSFODNN7EXAMPLE"}\n')
        pm = _project_map([{"path": "package-lock.json", "category": "config", "language": None}])
        indicators, _ = derive_secret_indicators(tmp_path, pm, [])
        assert indicators == []

    def test_asset_and_doc_category_files_are_not_scanned(self, tmp_path):
        _write(tmp_path, "README.md", "See AKIAIOSFODNN7EXAMPLE in the AWS docs.\n")
        pm = _project_map([{"path": "README.md", "category": "doc", "language": None}])
        indicators, _ = derive_secret_indicators(tmp_path, pm, [])
        assert indicators == []

    def test_line_number_evidence_is_correct(self, tmp_path):
        _write(tmp_path, "config.py", "# line 1\n# line 2\nAWS_KEY = \"AKIAIOSFODNN7EXAMPLE\"\n")
        pm = _project_map([{"path": "config.py", "category": "source", "language": "python"}])
        indicators, _ = derive_secret_indicators(tmp_path, pm, [])
        assert indicators[0]["line"] == 3
        assert indicators[0]["file"] == "config.py"

    def test_missing_file_on_disk_does_not_crash(self, tmp_path):
        pm = _project_map([{"path": "ghost.py", "category": "source", "language": "python"}])
        indicators, _ = derive_secret_indicators(tmp_path, pm, [])
        assert indicators == []


# ── Secret indicators: committed key file tier ─────────────────────


class TestSecretIndicatorsCommittedKeyFile:
    def test_pem_file_in_project_map_is_flagged(self):
        pm = _project_map([{"path": "certs/server.pem", "category": "asset", "language": None}])
        indicators, _ = derive_secret_indicators(Path("."), pm, [])
        assert indicators[0]["category"] == "committed_key_file"
        assert indicators[0]["pattern_type"] == "pem"
        assert indicators[0]["name"] == "server.pem"

    def test_ordinary_file_extension_is_not_flagged(self):
        pm = _project_map([{"path": "app.py", "category": "source", "language": "python"}])
        indicators, _ = derive_secret_indicators(Path("."), pm, [])
        assert indicators == []

    def test_key_file_not_in_project_map_is_not_flagged(self, tmp_path):
        # project_map is .gitignore-aware — a gitignored .pem never
        # appears here, and must not be flagged (it isn't committed).
        _write(tmp_path, "secrets/local.pem", "not a real key\n")
        indicators, _ = derive_secret_indicators(tmp_path, _project_map([]), [])
        assert indicators == []


class TestSecretIndicatorsMalformedInput:
    def test_malformed_env_var_entries_do_not_crash(self):
        indicators, _ = derive_secret_indicators(Path("."), _project_map([]), [{"garbage": True}])
        assert indicators == []

    def test_empty_project_map_does_not_crash(self):
        indicators, warnings = derive_secret_indicators(Path("."), {}, [])
        assert indicators == []
        assert warnings == []


# ── Sensitive configuration ─────────────────────────────────────────


class TestSensitiveConfiguration:
    def test_dockerfile_without_user_is_flagged_low_severity(self, tmp_path):
        _write(tmp_path, "Dockerfile", "FROM python:3.12\nCOPY . /app\n")
        findings = derive_sensitive_configuration(tmp_path, _project_map([]))
        assert findings[0]["category"] == "container_runs_as_root"
        assert findings[0]["severity"] == "low"

    def test_dockerfile_with_user_is_not_flagged(self, tmp_path):
        _write(tmp_path, "Dockerfile", "FROM python:3.12\nUSER appuser\n")
        findings = derive_sensitive_configuration(tmp_path, _project_map([]))
        assert not any(f["category"] == "container_runs_as_root" for f in findings)

    def test_cors_wildcard_detected(self, tmp_path):
        _write(tmp_path, "app.py", 'CORS_ORIGIN_ALLOW_ALL = True\n')
        pm = _project_map([{"path": "app.py", "category": "source", "language": "python"}])
        findings = derive_sensitive_configuration(tmp_path, pm)
        assert findings[0]["category"] == "cors_wildcard_origin"
        assert findings[0]["severity"] == "medium"

    def test_tls_verification_disabled_detected_high_severity(self, tmp_path):
        _write(tmp_path, "client.py", "requests.get(url, verify=False)\n")
        pm = _project_map([{"path": "client.py", "category": "source", "language": "python"}])
        findings = derive_sensitive_configuration(tmp_path, pm)
        assert findings[0]["category"] == "tls_verification_disabled"
        assert findings[0]["severity"] == "high"

    def test_debug_true_detected(self, tmp_path):
        _write(tmp_path, "settings.py", "DEBUG = True\n")
        pm = _project_map([{"path": "settings.py", "category": "source", "language": "python"}])
        findings = derive_sensitive_configuration(tmp_path, pm)
        assert any(f["category"] == "debug_enabled" for f in findings)

    def test_clean_repo_yields_no_findings(self, tmp_path):
        _write(tmp_path, "app.py", "def main():\n    pass\n")
        pm = _project_map([{"path": "app.py", "category": "source", "language": "python"}])
        assert derive_sensitive_configuration(tmp_path, pm) == []

    def test_empty_repo_does_not_crash(self, tmp_path):
        assert derive_sensitive_configuration(tmp_path, _project_map([])) == []


# ── Authentication indicators ───────────────────────────────────────


class TestAuthenticationIndicators:
    def test_known_python_auth_dependency_detected(self, tmp_path):
        _write(tmp_path, "requirements.txt", "flask-login==0.6.0\nrequests\n")
        indicators = derive_authentication_indicators(tmp_path, _project_map([]))
        names = {i["name"] for i in indicators}
        assert "flask-login" in names
        assert "requests" not in names

    def test_known_js_auth_dependency_detected(self, tmp_path):
        _write(tmp_path, "package.json", json.dumps({"dependencies": {"next-auth": "^4.0.0", "lodash": "^4.0.0"}}))
        indicators = derive_authentication_indicators(tmp_path, _project_map([]))
        names = {i["name"] for i in indicators}
        assert "next-auth" in names
        assert "lodash" not in names

    def test_auth_guard_decorator_pattern_detected(self, tmp_path):
        _write(tmp_path, "views.py", "@login_required\ndef dashboard():\n    pass\n")
        pm = _project_map([{"path": "views.py", "category": "source", "language": "python"}])
        indicators = derive_authentication_indicators(tmp_path, pm)
        assert any(i["type"] == "pattern" and i["name"] == "@login_required" for i in indicators)

    def test_no_auth_signals_returns_empty(self, tmp_path):
        _write(tmp_path, "app.py", "def main():\n    pass\n")
        pm = _project_map([{"path": "app.py", "category": "source", "language": "python"}])
        assert derive_authentication_indicators(tmp_path, pm) == []


# ── Security tooling detected ───────────────────────────────────────


class TestSecurityToolingDetected:
    def test_security_md_detected(self, tmp_path):
        _write(tmp_path, "SECURITY.md", "# Security Policy\n")
        detected = derive_security_tooling(tmp_path)
        assert detected[0]["name"] == "SECURITY.md"

    def test_dependabot_config_detected(self, tmp_path):
        _write(tmp_path, ".github/dependabot.yml", "version: 2\n")
        detected = derive_security_tooling(tmp_path)
        assert any(d["name"] == ".github/dependabot.yml" for d in detected)

    def test_eslint_security_plugin_detected(self, tmp_path):
        _write(tmp_path, "package.json", json.dumps({"devDependencies": {"eslint-plugin-security": "^1.0.0"}}))
        detected = derive_security_tooling(tmp_path)
        assert any(d["name"] == "eslint-plugin-security" for d in detected)

    def test_no_tooling_returns_empty(self, tmp_path):
        assert derive_security_tooling(tmp_path) == []


class TestRootContainment:
    """Max-effort code review finding: every file read in this module used
    raw Path.read_text() with no root-containment/symlink-safety check,
    the same gap already fixed for command_discovery.py in an earlier
    pass. A path built from a project_map entry is not automatically
    trustworthy just because project_map said so.
    """

    def _project_map(self, *paths: str) -> dict:
        return {"files": [{"path": p, "category": "source"} for p in paths]}

    def test_secret_scan_does_not_follow_symlink_escaping_root(self, tmp_path):
        outside = tmp_path.parent / f"outside-secret-{tmp_path.name}.py"
        outside.write_text('AWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n')
        root = tmp_path / "project"
        root.mkdir()
        try:
            (root / "leak.py").symlink_to(outside)
        except OSError:
            pytest.skip("symlinks not supported in this environment")
        try:
            indicators, warnings = derive_secret_indicators(
                root, self._project_map("leak.py"), environment_variables=[]
            )
            assert not any(i["pattern_type"] == "aws_access_key_id" for i in indicators)
        finally:
            outside.unlink(missing_ok=True)

    def test_sensitive_config_scan_does_not_follow_symlink_escaping_root(self, tmp_path):
        outside = tmp_path.parent / f"outside-config-{tmp_path.name}.py"
        outside.write_text("DEBUG = True\n")
        root = tmp_path / "project"
        root.mkdir()
        try:
            (root / "settings.py").symlink_to(outside)
        except OSError:
            pytest.skip("symlinks not supported in this environment")
        try:
            findings = derive_sensitive_configuration(root, self._project_map("settings.py"))
            assert not any(f["category"] == "debug_enabled" for f in findings)
        finally:
            outside.unlink(missing_ok=True)

    def test_dockerfile_symlink_escaping_root_is_not_read(self, tmp_path):
        outside = tmp_path.parent / f"outside-dockerfile-{tmp_path.name}"
        outside.write_text("FROM scratch\n")  # no USER — would otherwise flag as root
        root = tmp_path / "project"
        root.mkdir()
        try:
            (root / "Dockerfile").symlink_to(outside)
        except OSError:
            pytest.skip("symlinks not supported in this environment")
        try:
            findings = derive_sensitive_configuration(root, self._project_map())
            assert not any(f["category"] == "container_runs_as_root" for f in findings)
        finally:
            outside.unlink(missing_ok=True)

    def test_secret_scan_still_reads_dot_env_files(self, tmp_path):
        """Guards against a naive fix: routing these reads through
        repository_digest_schema.safe_read_text's credential denylist
        (.env, .key, .pem, credentials.*) would silently blind the
        scanner to exactly the files most likely to hold a real secret.
        The fix here must add containment safety without losing this.
        """
        _write(tmp_path, ".env", 'STRIPE_KEY=sk_live_ABCDEFGHIJKLMNOPQRST\n')
        indicators, _ = derive_secret_indicators(
            tmp_path, {"files": [{"path": ".env", "category": "config"}]}, environment_variables=[]
        )
        assert any(i["pattern_type"] == "stripe_key" for i in indicators)

    def test_auth_indicators_scan_does_not_follow_symlink_escaping_root(self, tmp_path):
        outside = tmp_path.parent / f"outside-auth-{tmp_path.name}.py"
        outside.write_text("@login_required\ndef view(): pass\n")
        root = tmp_path / "project"
        root.mkdir()
        try:
            (root / "views.py").symlink_to(outside)
        except OSError:
            pytest.skip("symlinks not supported in this environment")
        try:
            indicators = derive_authentication_indicators(root, self._project_map("views.py"))
            assert not any(i["file"] == "views.py" for i in indicators)
        finally:
            outside.unlink(missing_ok=True)
