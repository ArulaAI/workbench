"""Regression checks for structured CLI responses containing Markdown fences."""

from __future__ import annotations

from types import SimpleNamespace
import json
import pytest

from pydantic import BaseModel

from dashboard.backend import llm
from dashboard.backend.llm import _cache_key, _validate_cli_response


class RevisionPayload(BaseModel):
    body: str


def test_cli_zero_retries_does_not_silently_repeat_a_long_generation(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "_is_cli_model", lambda *_: True)
    def complete(*args, **kwargs):
        calls.append(kwargs)
        return '{"wrong_field":"incomplete draft"}', 0, 180000
    monkeypatch.setattr(llm, "_cli_complete", complete)
    with pytest.raises(ValueError, match="required format"):
        llm.llm_complete([{"role":"user","content":"Generate"}], RevisionPayload,
                         "claude-code/sonnet", project_root=tmp_path, max_retries=0, timeout=360)
    assert len(calls) == 1


def test_cli_error_details_prefer_errors_over_usage_envelope() -> None:
    payload = {"is_error": True, "num_turns": 6, "usage": {"output_tokens": 28000},
               "errors": ["Structured output failed validation", {"message": "Missing sections"}]}
    assert llm._cli_error_detail(json.dumps(payload), "") == "Structured output failed validation; Missing sections"
    payload.pop('errors')
    payload['subtype'] = 'error_max_structured_output_retries'
    detail = llm._cli_error_detail(json.dumps(payload), '')
    assert 'required document format' in detail and 'Retry' in detail
    assert 'output_tokens' not in detail


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
