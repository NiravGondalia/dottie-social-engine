"""stdio MCP server that HTTP-calls MiloAgent /api/agent routes."""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional

import requests

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from mcp.server.mcpserver import MCPServer as FastMCP

mcp = FastMCP("milo-agent")

TOOL_SPECS = (
    "scan",
    "get_scan_status",
    "list_opportunities",
    "get_opportunity",
    "generate_reply",
    "revise_reply",
    "approve_post",
    "skip",
    "get_schedule",
)


def _base() -> str:
    return (os.environ.get("MILO_AGENT_BASE_URL") or "http://127.0.0.1:8420").rstrip("/")


def call_agent_api(
    method: str,
    path: str,
    json: Optional[dict] = None,
    params: Optional[dict] = None,
) -> Any:
    token = (os.environ.get("MILO_AGENT_TOKEN") or "").strip()
    try:
        resp = requests.request(
            method=method,
            url=_base() + path,
            json=json,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=120 if path.endswith("/scan") else 30,
        )
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc)}
    if resp.status_code == 401:
        return {"ok": False, "error": "unauthorized"}
    if resp.status_code == 503:
        return {"ok": False, "error": "MILO_AGENT_TOKEN is not set on the server"}
    try:
        return resp.json()
    except ValueError:
        return {"ok": False, "error": resp.text[:300]}


def _scan() -> Any:
    return call_agent_api("POST", "/api/agent/scan")


def _get_scan_status() -> Any:
    return call_agent_api("GET", "/api/agent/scan/status")


def _list_opportunities(limit: int = 20) -> Any:
    return call_agent_api(
        "GET",
        "/api/agent/opportunities",
        params={"limit": limit},
    )


def _get_opportunity(target_id: str) -> Any:
    return call_agent_api("GET", f"/api/agent/opportunities/{target_id}")


def _generate_reply(target_id: str) -> Any:
    return call_agent_api(
        "POST",
        f"/api/agent/opportunities/{target_id}/generate-reply",
    )


def _revise_reply(
    target_id: str,
    instruction: str,
    current_draft: str = "",
) -> Any:
    return call_agent_api(
        "POST",
        f"/api/agent/opportunities/{target_id}/revise-reply",
        json={"instruction": instruction, "current_draft": current_draft},
    )


def _approve_post(target_id: str, reply_text: str = "") -> Any:
    return call_agent_api(
        "POST",
        f"/api/agent/opportunities/{target_id}/approve-post",
        json={"reply_text": reply_text},
    )


def _skip(target_id: str, reason: str = "human skip") -> Any:
    return call_agent_api(
        "POST",
        f"/api/agent/opportunities/{target_id}/skip",
        json={"reason": reason},
    )


def _get_schedule() -> Any:
    return call_agent_api("GET", "/api/agent/schedule")


tool_handlers: Dict[str, Callable[..., Any]] = {
    "scan": _scan,
    "get_scan_status": _get_scan_status,
    "list_opportunities": _list_opportunities,
    "get_opportunity": _get_opportunity,
    "generate_reply": _generate_reply,
    "revise_reply": _revise_reply,
    "approve_post": _approve_post,
    "skip": _skip,
    "get_schedule": _get_schedule,
}


@mcp.tool()
def scan() -> Any:
    return tool_handlers["scan"]()


@mcp.tool()
def get_scan_status() -> Any:
    return tool_handlers["get_scan_status"]()


@mcp.tool()
def list_opportunities(limit: int = 20) -> Any:
    return tool_handlers["list_opportunities"](limit=limit)


@mcp.tool()
def get_opportunity(target_id: str) -> Any:
    return tool_handlers["get_opportunity"](target_id)


@mcp.tool()
def generate_reply(target_id: str) -> Any:
    return tool_handlers["generate_reply"](target_id)


@mcp.tool()
def revise_reply(
    target_id: str,
    instruction: str,
    current_draft: str = "",
) -> Any:
    return tool_handlers["revise_reply"](
        target_id,
        instruction,
        current_draft=current_draft,
    )


@mcp.tool()
def approve_post(target_id: str, reply_text: str = "") -> Any:
    return tool_handlers["approve_post"](target_id, reply_text=reply_text)


@mcp.tool()
def skip(target_id: str, reason: str = "human skip") -> Any:
    return tool_handlers["skip"](target_id, reason=reason)


@mcp.tool()
def get_schedule() -> Any:
    return tool_handlers["get_schedule"]()
