"""LLM abstraction layer for the spec editor.

Provider-agnostic interface using litellm + instructor.
Model discovery is fully dynamic: API providers via litellm, CLI tiers
from speed.toml, ollama via runtime HTTP discovery.

Usage:
    from dashboard.backend.llm import llm_complete, get_available_models

    models = get_available_models(project_root)
    result = llm_complete(
        messages=[{"role": "user", "content": "Analyze this spec..."}],
        response_model=AmbiguityReport,
        model=models[0]["id"],
        project_root=project_root,
    )
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Type, TypeVar

import instructor
import litellm
from pydantic import BaseModel

log = logging.getLogger("speed.dashboard.llm")

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True

T = TypeVar("T", bound=BaseModel)

# ── Model config and discovery ───────────────────────────────────────────

_model_config_cache: dict[str, dict[str, Any]] = {}


def read_model_config(project_root: Path | None = None) -> dict[str, Any]:
    """Read [agent] model config from speed.toml.

    Returns dict with optional keys:
      provider (str), cli_command (str), ollama_base_url (str),
      cli_models (list[str]), api_providers (list[str]), ceremony_models (list[str]).
    Empty dict if no speed.toml or no [agent] section.
    """
    if project_root is None:
        return {}
    cache_key = str(project_root)
    if cache_key in _model_config_cache:
        return _model_config_cache[cache_key]

    toml_path = project_root / "speed.toml"
    if not toml_path.exists():
        _model_config_cache[cache_key] = {}
        return {}

    try:
        import tomllib
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        agent = data.get("agent", {})
        config: dict[str, Any] = {}
        for key in (
            "provider",
            "cli_command",
            "ollama_base_url",
            "planning_model",
            "support_model",
        ):
            val = agent.get(key)
            if val:
                config[key] = str(val)
        for key in ("cli_models", "api_providers", "ceremony_models"):
            val = agent.get(key)
            if isinstance(val, list):
                config[key] = [str(v) for v in val]
            elif isinstance(val, str) and val:
                config[key] = [val]
        _model_config_cache[cache_key] = config
        return config
    except (OSError, Exception):
        _model_config_cache[cache_key] = {}
        return {}


def get_available_models(project_root: Path | None = None) -> list[dict[str, Any]]:
    """Return models available based on speed.toml config, API keys, and local services."""
    import os
    import shutil

    models: list[dict[str, Any]] = []
    config = read_model_config(project_root)

    # 1. CLI runner — provider + tiers from speed.toml
    provider = config.get("provider")
    command = config.get("cli_command")
    cli_models = config.get("cli_models", [])
    if provider and command and shutil.which(command):
        for tier in cli_models:
            model_id = f"{provider}/{tier}"
            models.append({"id": model_id, "provider": provider, "label": f"{provider}: {tier}"})

    # 2. Ollama — runtime discovery (litellm only has a static entry,
    #    doesn't query the local instance for actually-pulled models)
    ollama_url = os.environ.get("OLLAMA_API_BASE") or config.get("ollama_base_url")
    if ollama_url:
        try:
            import httpx
            resp = httpx.get(f"{ollama_url}/api/tags", timeout=2)
            if resp.status_code == 200:
                for m in resp.json().get("models", []):
                    name = m.get("name", "")
                    models.append({"id": f"ollama/{name}", "provider": "ollama", "label": f"Ollama: {name}"})
        except Exception:
            pass

    # 3. API providers — only check providers listed in speed.toml api_providers
    api_providers = config.get("api_providers", [])
    for provider_key in api_providers:
        provider_models = litellm.models_by_provider.get(provider_key, set())
        if not provider_models:
            continue
        sample = next(iter(provider_models))
        env_check = litellm.validate_environment(sample)
        if not env_check.get("keys_in_environment", False):
            continue
        for model_name in sorted(provider_models):
            try:
                info = litellm.get_model_info(model_name)
                if info.get("mode") != "chat":
                    continue
            except Exception:
                continue
            model_id = model_name if "/" in model_name else f"{provider_key}/{model_name}"
            models.append({
                "id": model_id,
                "provider": provider_key,
                "label": f"{provider_key}: {model_name.split('/')[-1]}",
            })

    # Deduplicate by model ID
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for m in models:
        if m["id"] not in seen:
            seen.add(m["id"])
            unique.append(m)
    return unique


def get_unconfigured_providers(project_root: Path | None = None) -> list[dict[str, str]]:
    """Return API providers from config that have models but missing keys."""
    config = read_model_config(project_root)
    api_providers = config.get("api_providers", [])
    missing: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for provider_key in api_providers:
        provider_models = litellm.models_by_provider.get(provider_key, set())
        if not provider_models:
            continue
        sample = next(iter(provider_models))
        env_check = litellm.validate_environment(sample)
        if env_check.get("keys_in_environment", False):
            continue
        missing_keys = env_check.get("missing_keys", [])
        if not missing_keys:
            continue
        key = missing_keys[0]
        if key in seen_keys:
            continue
        seen_keys.add(key)
        missing.append({"provider": provider_key, "label": provider_key, "env_var": key})
    return missing


def get_ceremony_models(project_root: Path | None = None) -> list[dict[str, Any]]:
    """Return ceremony models configured in speed.toml that are currently available.

    If no config, returns all available non-CLI models.
    Used by ceremony model dropdowns (IntentInput).
    """
    config = read_model_config(project_root)
    configured = config.get("ceremony_models", [])
    available = get_available_models(project_root)

    if not configured:
        cli_provider = config.get("provider", "")
        return [m for m in available if not cli_provider or m["provider"] != cli_provider]

    result = []
    seen: set[str] = set()
    for short_name in configured:
        for m in available:
            if m["id"] not in seen and short_name in m["id"]:
                result.append(m)
                seen.add(m["id"])
                break
    return result


# ── LLM completion with structured output ─────────────────────────────────


def _is_cli_model(model: str, project_root: Path | None = None) -> bool:
    config = read_model_config(project_root)
    provider = config.get("provider", "")
    return bool(provider) and model.startswith(f"{provider}/")


def _is_ollama_model(model: str) -> bool:
    return model.startswith("ollama/")


def _ollama_complete(
    messages: list[dict[str, str]],
    model: str,
    response_model: Type[T],
    temperature: float = 0.2,
    max_tokens: int = 4096,
    project_root: Path | None = None,
    timeout: int = 120,
) -> tuple[T, int]:
    """Call Ollama's /api/chat directly with native tool calling.

    Bypasses litellm, which misroutes models whose Modelfile uses a
    dedicated RENDERER/PARSER instead of inline {{ .Tools }} templates.
    Returns (validated_model, elapsed_ms).
    """
    import httpx
    import os

    base_url = (
        os.environ.get("OLLAMA_API_BASE")
        or (read_model_config(project_root).get("ollama_base_url"))
        or "http://localhost:11434"
    )
    ollama_model = model.removeprefix("ollama/")
    schema = response_model.model_json_schema()

    tool_def = {
        "type": "function",
        "function": {
            "name": response_model.__name__,
            "description": response_model.__doc__ or "",
            "parameters": schema,
        },
    }

    payload: dict[str, Any] = {
        "model": ollama_model,
        "messages": messages,
        "tools": [tool_def],
        "stream": False,
        "think": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }

    start = time.monotonic()
    resp = httpx.post(f"{base_url}/api/chat", json=payload, timeout=timeout)
    resp.raise_for_status()
    elapsed_ms = int((time.monotonic() - start) * 1000)

    data = resp.json()
    msg = data.get("message", {})
    tool_calls = msg.get("tool_calls", [])

    if tool_calls:
        args = tool_calls[0].get("function", {}).get("arguments", {})
        result = response_model.model_validate(args)
    else:
        # Model responded with plain JSON content instead of a tool call
        content = msg.get("content", "")
        result = response_model.model_validate_json(content)

    return result, elapsed_ms


def _cli_complete_text(
    messages: list[dict[str, str]],
    model: str,
    project_root: Path | None = None,
    timeout: int = 300,
) -> str:
    """Run a CLI LLM call for long text output.

    Matches _cli_complete while keeping user content out of argv. Claude uses
    print mode and Codex uses ephemeral non-interactive execution.
    """
    import subprocess

    parts = []
    system_parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            system_parts.append(content)
        else:
            parts.append(content)
    prompt = "\n".join(parts)

    config = read_model_config(project_root)
    command = config.get("cli_command", model.split("/")[0])
    model_tier = model.split("/")[-1]  # e.g. "opus", "sonnet"

    if command == "claude":
        cmd = [command, "-p", "--output-format", "json",
               "--model", model_tier, "--tools", ""]
        if system_parts:
            cmd.extend(["--system-prompt", "\n\n".join(system_parts)])
        last_err = ""
        for attempt in range(3):
            if attempt > 0:
                import time as _time
                _time.sleep(2 ** attempt)  # 2s, 4s backoff
                log.info("Retrying CLI call (attempt %d/3)", attempt + 1)
            result = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, timeout=timeout,
            )
            if result.returncode == 0:
                break
            last_err = _cli_error_detail(result.stdout, result.stderr)
            if "overloaded" not in last_err.lower() and "529" not in last_err:
                raise RuntimeError(f"{command} CLI failed: {last_err}")
        else:
            raise RuntimeError(f"{command} CLI failed after 3 attempts: {last_err}")
        data = json.loads(result.stdout)
        text = data.get("result", "")
        # Guard: CLI errors can leak into the result field
        if text.startswith(("Error:", "API Error:")):
            raise RuntimeError(f"{command} CLI returned error as result: {text[:200]}")
        return text
    elif command == "codex":
        if system_parts:
            prompt = (
                "<system>\n"
                + "\n\n".join(system_parts)
                + "\n</system>\n\n"
                + prompt
            )
        result = subprocess.run(
            [
                command, "exec", "--ephemeral", "--sandbox", "read-only",
                "--color", "never", "--model", model_tier, "-",
            ],
            input=prompt, capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"codex CLI failed: {result.stderr[:300]}")
        return result.stdout.strip()
    else:
        raise ValueError(f"Unknown CLI command: {command}")


def _extract_text_from_stream_json(raw: str) -> str:
    """Extract the final result text from Claude's stream-json output.

    Each line is a JSON event. The full content is in the last assistant
    message's text blocks. The result event's 'result' field may be
    truncated so we prefer the assistant content.
    """
    last_assistant_text = ""
    last_result = ""

    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    text = block.get("text", "")
                    if len(text) > len(last_assistant_text):
                        last_assistant_text = text

        if event.get("type") == "result":
            last_result = event.get("result", "")

    # Prefer the longest source -- assistant text blocks have the full content
    if last_assistant_text and len(last_assistant_text) >= len(last_result):
        return last_assistant_text
    if last_result:
        return last_result

    return raw.strip()


def _cli_error_detail(stdout: str, stderr: str) -> str:
    """Surface structured CLI API errors that are often written to stdout."""
    detail = stderr.strip()
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        payload = None
    if isinstance(payload, dict):
        message = str(payload.get("result") or payload.get("error") or "").strip()
        status = payload.get("api_error_status")
        if message:
            return f"API {status}: {message}" if status else message
        errors = payload.get("errors")
        if isinstance(errors, list):
            messages = [e if isinstance(e, str) else e.get("message", "")
                        for e in errors if isinstance(e, (str, dict))]
            if any(messages):
                return "; ".join(str(m) for m in messages if m)
        if payload.get("is_error"):
            subtype = payload.get("subtype", "")
            if subtype == "error_max_structured_output_retries":
                return "The model could not produce the required document format after repeated attempts. Retry the saved request."
            return detail or f"Model generation failed ({subtype or 'no error detail returned'}). Retry the saved request."
    return detail or stdout.strip()[:300] or "unknown CLI failure"


def _validate_cli_response(text: str, response_model: Type[T]) -> T:
    """Validate the full response first, then scan for a JSON object envelope."""
    try:
        return response_model.model_validate_json(text)
    except Exception as direct_error:
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                payload, _end = decoder.raw_decode(text[index:])
                return response_model.model_validate(payload)
            except Exception:
                continue
        raise direct_error


def _cli_complete(
    messages: list[dict[str, str]],
    model: str,
    project_root: Path | None = None,
    response_schema: Optional[dict] = None,
    max_tokens: int = 4096,
    timeout: int = 120,
) -> tuple[str, float, int]:
    """Run an LLM call through a CLI tool. Returns (text, cost_usd, elapsed_ms)."""
    import subprocess

    # Build prompt from messages
    parts = []
    system_parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            system_parts.append(content)
        else:
            parts.append(content)

    prompt = "\n".join(parts)

    config = read_model_config(project_root)
    command = config.get("cli_command", model.split("/")[0])

    start = time.monotonic()

    if command == "claude":
        model_tier = model.split("/")[-1]
        cli_args = [
            command,
            "-p",
            "--output-format",
            "json",
            "--model",
            model_tier,
            "--effort",
            "high" if max_tokens >= 6000 else "low",
            "--tools",
            "",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--no-session-persistence",
            "--disable-slash-commands",
            "--no-chrome",
            "--permission-mode",
            "dontAsk",
        ]
        if system_parts:
            cli_args.extend(["--system-prompt", "\n\n".join(system_parts)])
        if response_schema:
            cli_args.extend(["--json-schema", json.dumps(response_schema)])
        result = subprocess.run(
            cli_args,
            input=prompt, capture_output=True, text=True, timeout=timeout,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        if result.returncode != 0:
            raise RuntimeError(
                f"claude CLI failed: {_cli_error_detail(result.stdout, result.stderr)[:300]}"
            )
        data = json.loads(result.stdout)
        structured = data.get("structured_output")
        text = json.dumps(structured) if isinstance(structured, dict) else data.get("result", "")
        cost = data.get("total_cost_usd", 0)
    elif command == "codex":
        if system_parts:
            prompt = (
                "<system>\n"
                + "\n\n".join(system_parts)
                + "\n</system>\n\n"
                + prompt
            )
        if response_schema:
            prompt += (
                f"\n\nRespond with ONLY valid JSON matching this schema, no other text:\n"
                f"```json\n{json.dumps(response_schema, indent=2)}\n```"
            )
        result = subprocess.run(
            [
                command, "exec", "--ephemeral", "--sandbox", "read-only",
                "--color", "never", "--model", model.split("/")[-1], "-",
            ],
            input=prompt, capture_output=True, text=True, timeout=timeout,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        if result.returncode != 0:
            raise RuntimeError(f"codex CLI failed: {result.stderr[:200]}")
        text = result.stdout.strip()
        cost = 0
    else:
        raise ValueError(f"Unknown CLI command: {command}")

    return text, cost, elapsed_ms


def llm_complete(
    messages: list[dict[str, str]],
    response_model: Type[T],
    model: str,
    max_retries: int = 2,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    conn: Optional[sqlite3.Connection] = None,
    spec_path: Optional[str] = None,
    purpose: Optional[str] = None,
    project_root: Optional[Path] = None,
    timeout: int = 120,
) -> T:
    """Make an LLM call and return a validated Pydantic model.

    Routes to CLI subprocess for CLI-based models (configured in speed.toml),
    or to litellm+instructor for everything else.
    Caches responses in SQLite by content hash.
    """
    if conn:
        ensure_llm_tables(conn)
    # Check cache first
    schema = response_model.model_json_schema()
    cache_key = _cache_key(model, messages, schema)
    if conn:
        cached = _get_cached(conn, cache_key)
        if cached:
            try:
                log.debug("Cache hit for %s", cache_key[:16])
                return response_model.model_validate_json(cached)
            except Exception:
                log.warning("Discarding incompatible cached LLM response for %s", cache_key[:16])
                conn.execute("DELETE FROM llm_cache WHERE cache_key = ?", (cache_key,))
                conn.commit()

    start = time.monotonic()

    if _is_ollama_model(model):
        # Ollama direct path: native /api/chat with tools
        result, elapsed_ms = _ollama_complete(
            messages, model, response_model,
            temperature=temperature, max_tokens=max_tokens,
            project_root=project_root,
            timeout=timeout,
        )
        result_json = result.model_dump_json()
        if conn:
            _set_cached(conn, cache_key, result_json)
            _log_call(conn, model, messages, result_json, elapsed_ms, spec_path, purpose)
        return result

    elif _is_cli_model(model, project_root):
        # CLI path: include schema in prompt, parse JSON from response
        text, cost, elapsed_ms = _cli_complete(
            messages, model, project_root, response_schema=schema,
            max_tokens=max_tokens,
            timeout=timeout,
        )

        try:
            result = _validate_cli_response(text, response_model)
        except Exception:
            if max_retries <= 0:
                raise ValueError("The model response did not match the required format. Try again.") from None
            # Retry once with a nudge
            retry_msgs = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": "That response was not valid JSON. Please respond with ONLY the JSON object, no other text."},
            ]
            text2, cost2, elapsed2 = _cli_complete(
                retry_msgs, model, project_root, response_schema=schema,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            result = _validate_cli_response(text2, response_model)
            cost += cost2
            elapsed_ms += elapsed2

        result_json = result.model_dump_json()
        if conn:
            _set_cached(conn, cache_key, result_json)
            _log_call(
                conn, model, messages, result_json, elapsed_ms, spec_path, purpose,
                actual_cost_usd=cost,
            )
        return result
    else:
        # litellm + instructor path
        client = instructor.from_litellm(litellm.completion)

        result = client.chat.completions.create(
            model=model,
            messages=messages,
            response_model=response_model,
            max_retries=max_retries,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        result_json = result.model_dump_json()
        if conn:
            _set_cached(conn, cache_key, result_json)
            _log_call(conn, model, messages, result_json, elapsed_ms, spec_path, purpose)

        return result


def cli_run_architect(
    system_prompt: str,
    user_message: str,
    json_schema: str,
    model: str = "opus",
    project_root: Path | None = None,
    timeout: int = 900,
) -> dict:
    """Run the Architect agent via the Claude CLI, matching speed plan's invocation.

    Uses --system-prompt, --json-schema, --output-format stream-json, stdin pipe,
    and --effort medium for large opus inputs. Extracts structured JSON from the
    StructuredOutput tool_use event in the stream.
    """
    import subprocess
    import tempfile

    config = read_model_config(project_root)
    command = config.get("cli_command", "claude")
    model_tier = model.split("/")[-1] if "/" in model else model

    # Build CLI args (mirrors providers/claude-code.sh provider_run_json)
    cli_args = [
        command,
        "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--model", model_tier,
        "--system-prompt", system_prompt,
        "--json-schema", json_schema,
        "--max-turns", "30",
    ]

    # Effort control: opus with large input gets "medium" to prevent thinking spirals
    total_chars = len(system_prompt) + len(user_message)
    if "opus" in model_tier and total_chars > 50000:
        cli_args.extend(["--effort", "medium"])

    # Write user message to temp file for stdin pipe
    prompt_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8",
    )
    prompt_file.write(user_message)
    prompt_file.close()

    try:
        with open(prompt_file.name, "r") as stdin_f:
            result = subprocess.run(
                cli_args,
                stdin=stdin_f,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

        if result.returncode != 0:
            stderr = result.stderr.strip()[:300] if result.stderr else "(no stderr)"
            raise RuntimeError(f"Architect CLI failed (exit {result.returncode}): {stderr}")

        # Extract StructuredOutput from stream-json events
        # Each line is a JSON event; look for tool_use with name=StructuredOutput
        structured = None
        last_result = None
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            # StructuredOutput tool call (primary path with --json-schema)
            if event.get("type") == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if (
                        block.get("type") == "tool_use"
                        and block.get("name") == "StructuredOutput"
                    ):
                        structured = block.get("input")

            # Fallback: result event
            if event.get("type") == "result":
                so = event.get("structured_output")
                if so:
                    last_result = so
                elif event.get("result"):
                    last_result = event.get("result")

        if structured and isinstance(structured, dict):
            return structured
        if isinstance(last_result, dict):
            return last_result

        # Final fallback: try to parse the raw result text as JSON
        if isinstance(last_result, str):
            return json.loads(last_result)

        raise ValueError(
            f"Architect returned no structured output. "
            f"Got {len(result.stdout)} bytes of stream events."
        )

    finally:
        import os
        os.unlink(prompt_file.name)


def llm_complete_text(
    messages: list[dict[str, str]],
    model: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    project_root: Optional[Path] = None,
    timeout: int = 120,
) -> str:
    """Make an LLM call and return raw text (no structured output)."""
    if _is_cli_model(model, project_root):
        text = _cli_complete_text(messages, model, project_root, timeout=timeout)
        return text

    response = litellm.completion(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


# ── Cache ─────────────────────────────────────────────────────────────────

LLM_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key   TEXT PRIMARY KEY,
    response    TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model       TEXT NOT NULL,
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    cost_usd    REAL,
    elapsed_ms  INTEGER,
    purpose     TEXT,
    spec_path   TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
"""


def ensure_llm_tables(conn: sqlite3.Connection) -> None:
    """Create LLM cache and call log tables if they don't exist."""
    conn.executescript(LLM_CACHE_DDL)


def _cache_key(model: str, messages: list[dict], response_schema: dict) -> str:
    raw = json.dumps(
        {"model": model, "messages": messages, "schema": response_schema},
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_cached(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute(
        """SELECT response FROM llm_cache
           WHERE cache_key = ?
             AND created_at >= strftime('%Y-%m-%dT%H:%M:%SZ','now','-30 days')""",
        (key,),
    ).fetchone()
    return row["response"] if row else None


def _set_cached(conn: sqlite3.Connection, key: str, response: str) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO llm_cache (cache_key, response, created_at)
           VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))""",
        (key, response),
    )
    conn.execute(
        """DELETE FROM llm_cache WHERE cache_key NOT IN (
               SELECT cache_key FROM llm_cache ORDER BY created_at DESC LIMIT 1000
           )"""
    )
    conn.commit()


def _log_call(
    conn: sqlite3.Connection, model: str, messages: list[dict],
    response: str, elapsed_ms: int, spec_path: Optional[str], purpose: Optional[str],
    actual_cost_usd: Optional[float] = None,
) -> None:
    # Estimate tokens (rough: 4 chars per token)
    input_chars = sum(len(m.get("content", "")) for m in messages)
    tokens_in = input_chars // 4
    tokens_out = len(response) // 4
    cost = float(actual_cost_usd) if actual_cost_usd is not None else 0.0

    conn.execute(
        """INSERT INTO llm_calls (
               model, tokens_in, tokens_out, cost_usd, elapsed_ms,
               purpose, spec_path, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))""",
        (model, tokens_in, tokens_out, cost, elapsed_ms, purpose, spec_path),
    )
    conn.commit()
