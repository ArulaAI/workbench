"""Regression checks for structured CLI responses containing Markdown fences."""

from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel

from dashboard.backend import llm
from dashboard.backend.llm import _cache_key, _validate_cli_response


class RevisionPayload(BaseModel):
    body: str


def test_valid_json_with_an_embedded_code_fence_is_not_truncated() -> None:
    raw = '{"body":"Diagram:\\n```mermaid\\ngraph TD; A-->B\\n```"}'

    result = _validate_cli_response(raw, RevisionPayload)

    assert "graph TD" in result.body


def test_cache_identity_changes_when_response_schema_changes() -> None:
    messages = [{"role": "user", "content": "Revise the draft."}]

    first = _cache_key("model", messages, {"required": ["body"]})
    second = _cache_key("model", messages, {"required": ["body", "summary"]})

    assert first != second


def test_cli_user_prompt_is_sent_on_stdin_not_argv(tmp_path, monkeypatch) -> None:
    secret_prompt = "full private PRD body with enough text to exceed argv limits"
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["input"] = kwargs.get("input")
        return SimpleNamespace(
            returncode=0,
            stdout='{"result":"revised"}',
            stderr="",
        )

    monkeypatch.setattr(llm, "read_model_config", lambda _root: {"cli_command": "claude"})
    monkeypatch.setattr("subprocess.run", fake_run)

    result = llm._cli_complete_text(
        [{"role": "user", "content": secret_prompt}],
        "claude-code/sonnet",
        tmp_path,
    )

    assert result == "revised"
    assert captured["input"] == secret_prompt
    assert all(secret_prompt not in argument for argument in captured["command"])
