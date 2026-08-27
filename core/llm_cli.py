"""Subprocess LLM backends (Codex CLI). HTTP providers stay in llm_provider."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_NO_TOOLS = (
    "Do not run shell commands, search the web, or read files. "
    "Reply with the answer only."
)


def resolve_cli_binary(command: List[str]) -> List[str]:
    if not command:
        raise RuntimeError("CLI LLM provider has empty command")
    binary = command[0]
    found = None
    if os.path.isfile(binary):
        found = binary
    else:
        found = shutil.which(binary)
        if not found:
            fallback = Path.home() / ".local" / "bin" / binary
            if fallback.is_file():
                found = str(fallback)
    if not found:
        raise RuntimeError(f"CLI LLM binary not found: {binary}")
    return [found, *command[1:]]


def resolve_schema_path(path: str) -> str:
    p = Path(path)
    if p.is_file():
        return str(p.resolve())
    here = Path(__file__).resolve().parent.parent / path
    if here.is_file():
        return str(here)
    raise RuntimeError(f"Codex output schema not found: {path}")


def _message_from_jsonl(stdout: str) -> str:
    last = ""
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        item = ev.get("item") if isinstance(ev.get("item"), dict) else ev
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            last = text.strip()
            continue
        content = item.get("content")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
            if parts:
                last = "".join(parts).strip()
    return last


def _compose_prompt(prompt: str, system_prompt: str) -> str:
    chunks = [_NO_TOOLS]
    if system_prompt:
        chunks.append("SYSTEM:\n" + system_prompt.strip())
    chunks.append("USER:\n" + (prompt or "").strip())
    return "\n\n".join(chunks)


def run_codex_exec(
    cfg: Dict,
    prompt: str,
    system_prompt: str = "",
    use_json_schema: bool = False,
) -> str:
    """Run `codex exec` and return the agent's last message."""
    base = resolve_cli_binary(list(cfg.get("command") or ["codex", "exec"]))
    timeout = int(cfg.get("timeout", 180))
    sandbox = str(cfg.get("sandbox") or "read-only")
    model = str(cfg.get("model") or "").strip()

    with tempfile.TemporaryDirectory(prefix="milo-codex-") as tmp:
        last_path = Path(tmp) / "last.txt"
        flags = [
            "--skip-git-repo-check",
            "--ephemeral",
            "--color",
            "never",
            "--sandbox",
            sandbox,
            "--cd",
            tmp,
            "-c",
            'approval_policy="never"',
            "--json",
            "-o",
            str(last_path),
        ]
        if model:
            flags = ["-m", model, *flags]
        if use_json_schema:
            schema = cfg.get("output_schema") or "config/codex_keepers.schema.json"
            flags.extend(["--output-schema", resolve_schema_path(schema)])
        cmd = [*base, *flags, "-"]

        full_prompt = _compose_prompt(prompt, system_prompt)
        logger.debug("Codex CLI: %s", " ".join(cmd[:-1] + ["<stdin>"]))
        result = subprocess.run(
            cmd,
            input=full_prompt,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "")[-800:]
            raise RuntimeError(
                f"codex exec failed (exit {result.returncode}): {err}"
            )

        text = ""
        if last_path.is_file():
            text = last_path.read_text(encoding="utf-8").strip()
        if not text:
            text = _message_from_jsonl(result.stdout or "")
        if not text:
            raise RuntimeError("codex exec returned an empty message")
        return text
