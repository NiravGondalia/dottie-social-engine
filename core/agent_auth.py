"""Machine token for Buzz / MCP. Separate from dashboard session cookies."""

from __future__ import annotations

import hmac
import os
from typing import Optional


def get_agent_token() -> str:
    return (os.environ.get("MILO_AGENT_TOKEN") or "").strip()


def agent_token_configured() -> bool:
    return bool(get_agent_token())


def verify_agent_token(provided: Optional[str]) -> bool:
    expected = get_agent_token()
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))
