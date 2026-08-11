"""Resolve credentials exclusively from environment variables.

YAML configs keep non-secret settings (persona, projects, cookie paths, etc.).
Passwords, API keys, tokens, and client secrets must live in .env / process env.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(
    r"^(YOUR_|your_|changeme|password|username|example|xxx)",
    re.IGNORECASE,
)


def env(name: str, default: str = "") -> str:
    """Read a stripped env var."""
    return (os.environ.get(name) or default).strip()


def is_placeholder(value: Optional[str]) -> bool:
    if value is None or not str(value).strip():
        return True
    v = str(value).strip()
    if v.startswith("YOUR_"):
        return True
    return bool(_PLACEHOLDER_RE.match(v))


def _slot(prefix: str, index: int, field: str) -> str:
    """MILO_REDDIT_1_PASSWORD style name (1-based index)."""
    return f"{prefix}_{index}_{field}"


def _first(*names: str) -> str:
    for name in names:
        val = env(name)
        if val:
            return val
    return ""


def resolve_llm_api_key(provider: str) -> str:
    """LLM keys are env-only (ollama may use a non-secret dummy)."""
    mapping = {
        "groq": "MILO_GROQ_API_KEY",
        "gemini": "MILO_GEMINI_API_KEY",
        "claude": "MILO_ANTHROPIC_API_KEY",
        "ollama": "MILO_OLLAMA_API_KEY",
    }
    key = env(mapping.get(provider, f"MILO_{provider.upper()}_API_KEY"))
    if key:
        return key
    if provider == "ollama":
        return "ollama"
    return ""


def hydrate_reddit_accounts(data: Dict[str, Any]) -> Dict[str, Any]:
    accounts = data.get("accounts") or []
    for i, acc in enumerate(accounts, start=1):
        if not isinstance(acc, dict):
            continue
        username = _first(
            _slot("MILO_REDDIT", i, "USERNAME"),
            "MILO_REDDIT_USERNAME" if i == 1 else "",
        )
        password = _first(
            _slot("MILO_REDDIT", i, "PASSWORD"),
            "MILO_REDDIT_PASSWORD" if i == 1 else "",
        )
        client_id = _first(
            _slot("MILO_REDDIT", i, "CLIENT_ID"),
            "MILO_REDDIT_CLIENT_ID" if i == 1 else "",
        )
        client_secret = _first(
            _slot("MILO_REDDIT", i, "CLIENT_SECRET"),
            "MILO_REDDIT_CLIENT_SECRET" if i == 1 else "",
        )
        # Env wins; never keep YAML secrets
        if username:
            acc["username"] = username
        elif is_placeholder(acc.get("username")):
            acc["username"] = ""

        acc["password"] = password
        acc["client_id"] = client_id or ""
        acc["client_secret"] = client_secret or ""
    data["accounts"] = accounts
    return data


def hydrate_twitter_accounts(data: Dict[str, Any]) -> Dict[str, Any]:
    accounts = data.get("accounts") or []
    for i, acc in enumerate(accounts, start=1):
        if not isinstance(acc, dict):
            continue
        username = _first(
            _slot("MILO_TWITTER", i, "USERNAME"),
            "MILO_TWITTER_USERNAME" if i == 1 else "",
        )
        password = _first(
            _slot("MILO_TWITTER", i, "PASSWORD"),
            "MILO_TWITTER_PASSWORD" if i == 1 else "",
        )
        email = _first(
            _slot("MILO_TWITTER", i, "EMAIL"),
            "MILO_TWITTER_EMAIL" if i == 1 else "",
        )
        totp = _first(
            _slot("MILO_TWITTER", i, "TOTP_SECRET"),
            "MILO_TWITTER_TOTP_SECRET" if i == 1 else "",
        )
        if username:
            acc["username"] = username
        elif is_placeholder(acc.get("username")):
            acc["username"] = ""
        acc["password"] = password
        acc["email"] = email or ""
        acc["totp_secret"] = totp or ""
    data["accounts"] = accounts
    return data


def hydrate_telegram_user_accounts(data: Dict[str, Any]) -> Dict[str, Any]:
    accounts = data.get("accounts") or []
    for i, acc in enumerate(accounts, start=1):
        if not isinstance(acc, dict):
            continue
        phone = _first(
            _slot("MILO_TELEGRAM_USER", i, "PHONE"),
            "MILO_TELEGRAM_USER_PHONE" if i == 1 else "",
        )
        api_id = _first(
            _slot("MILO_TELEGRAM_USER", i, "API_ID"),
            "MILO_TELEGRAM_USER_API_ID" if i == 1 else "",
        )
        api_hash = _first(
            _slot("MILO_TELEGRAM_USER", i, "API_HASH"),
            "MILO_TELEGRAM_USER_API_HASH" if i == 1 else "",
        )
        if phone:
            acc["phone"] = phone
        elif is_placeholder(acc.get("phone")):
            acc["phone"] = ""
        acc["api_id"] = api_id or ""
        acc["api_hash"] = api_hash or ""
    data["accounts"] = accounts
    return data


def hydrate_telegram_bot(data: Dict[str, Any]) -> Dict[str, Any]:
    token = env("MILO_TELEGRAM_BOT_TOKEN")
    data["bot_token"] = token
    chat = env("MILO_TELEGRAM_ADMIN_CHAT_ID")
    if chat:
        ids: List[Any] = []
        for part in chat.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except ValueError:
                ids.append(part)
        data["admin_chat_ids"] = ids
    # Drop placeholder chat ids from the YAML template
    ids = data.get("admin_chat_ids") or []
    if ids and all((str(x) in ("0", "000000000") or x == 0) for x in ids):
        data["admin_chat_ids"] = []
    return data


def hydrate_reddit_api(data: Dict[str, Any]) -> Dict[str, Any]:
    data["client_id"] = env("MILO_REDDIT_API_CLIENT_ID")
    data["client_secret"] = env("MILO_REDDIT_API_CLIENT_SECRET")
    redirect = env("MILO_REDDIT_API_REDIRECT_URI")
    if redirect:
        data["redirect_uri"] = redirect
    return data


def hydrate_config(path: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Apply env secrets based on config filename."""
    if not data:
        return data or {}
    name = Path(path).name.replace(".local.yaml", ".yaml")
    if name == "reddit_accounts.yaml":
        return hydrate_reddit_accounts(data)
    if name == "twitter_accounts.yaml":
        return hydrate_twitter_accounts(data)
    if name == "telegram_user_accounts.yaml":
        return hydrate_telegram_user_accounts(data)
    if name == "telegram.yaml":
        return hydrate_telegram_bot(data)
    if name == "reddit_api.yaml":
        return hydrate_reddit_api(data)
    return data


def redact_secrets_for_yaml(platform: str, account: Dict[str, Any]) -> Dict[str, Any]:
    """Return account dict safe to write to YAML (no passwords/secrets)."""
    out = dict(account)
    for key in ("password", "client_secret", "totp_secret", "api_hash", "api_id"):
        if key in out:
            out[key] = ""
    if platform == "reddit":
        out["client_id"] = ""
    return out
