import json
import subprocess
from pathlib import Path

from core.llm_cli import (
    _message_from_jsonl,
    resolve_cli_binary,
    resolve_schema_path,
    run_codex_exec,
)
from core.llm_provider import LLMProvider


def test_resolve_schema_path():
    path = resolve_schema_path("config/codex_keepers.schema.json")
    assert Path(path).is_file()
    data = json.loads(Path(path).read_text())
    assert "keepers" in data["properties"]


def test_message_from_jsonl_agent_item():
    raw = "\n".join(
        [
            '{"type":"thread.started"}',
            '{"item":{"type":"agent_message","text":"{\\"keepers\\":[]}"}}',
        ]
    )
    assert _message_from_jsonl(raw) == '{"keepers":[]}'


def test_run_codex_exec_reads_last_message(monkeypatch, tmp_path):
    fake_bin = tmp_path / "codex"
    fake_bin.write_text("#!/bin/sh\n")
    fake_bin.chmod(0o755)

    def fake_run(cmd, **kwargs):
        assert cmd[0] == str(fake_bin)
        assert cmd[1] == "exec"
        assert "--output-schema" in cmd
        assert "-o" in cmd
        out = Path(cmd[cmd.index("-o") + 1])
        out.write_text('{"keepers":[{"target_id":"1vnui5a","dottie_score":10}]}')
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("core.llm_cli.subprocess.run", fake_run)
    text = run_codex_exec(
        {
            "command": [str(fake_bin), "exec"],
            "timeout": 5,
            "output_schema": "config/codex_keepers.schema.json",
        },
        prompt="rank these",
        system_prompt="json only",
        use_json_schema=True,
    )
    assert "1vnui5a" in text


def test_llm_provider_cli_routing(monkeypatch, tmp_path):
    cfg = tmp_path / "llm.yaml"
    cfg.write_text(
        """
providers:
  codex:
    enabled: true
    transport: cli
    command: ["codex", "exec"]
    timeout: 5
    output_schema: config/codex_keepers.schema.json
  groq:
    enabled: false
fallback_chain: ["codex"]
routing:
  creative: ["codex"]
  analytical: ["codex"]
"""
    )
    captured = {}

    def fake_exec(provider_cfg, prompt, system_prompt="", use_json_schema=False):
        captured["schema"] = use_json_schema
        captured["prompt"] = prompt
        return '{"keepers":[]}' if use_json_schema else "nice hike, I'm in."

    monkeypatch.setattr("core.llm_provider.run_codex_exec", fake_exec)
    llm = LLMProvider(str(cfg))
    assert llm.get_available_providers() == ["codex"]
    ranked = llm.generate(prompt="rank", task="analytical")
    assert ranked == '{"keepers":[]}'
    assert captured["schema"] is True
    draft = llm.generate(prompt="write comment", task="creative")
    assert "hike" in draft
    assert captured["schema"] is False


def test_resolve_cli_binary_missing(monkeypatch):
    monkeypatch.setattr("core.llm_cli.shutil.which", lambda _: None)
    monkeypatch.setattr("core.llm_cli.os.path.isfile", lambda _: False)
    try:
        resolve_cli_binary(["not-a-real-codex-binary"])
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "not found" in str(e)
