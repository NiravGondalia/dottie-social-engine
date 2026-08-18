"""Token-gated /api/agent routes for Buzz MCP. Not dashboard session auth."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from core.agent_auth import agent_token_configured, verify_agent_token
from core.agent_service import AgentService

_agent_security = HTTPBearer(auto_error=False)


class ReviseBody(BaseModel):
    instruction: str = Field(..., min_length=1, max_length=4000)
    current_draft: str = ""


class SkipBody(BaseModel):
    reason: str = "human skip"


class ApproveBody(BaseModel):
    reply_text: str = ""


def require_agent_token(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_agent_security),
) -> None:
    if not agent_token_configured():
        raise HTTPException(
            status_code=503,
            detail="MILO_AGENT_TOKEN is not set",
        )
    provided = creds.credentials if creds else None
    if not verify_agent_token(provided):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _scan_interval_minutes(orch: Any) -> int:
    bot_settings = getattr(orch, "_bot_settings", None)
    if isinstance(bot_settings, dict) and "scan_interval_minutes" in bot_settings:
        return int(bot_settings["scan_interval_minutes"])
    settings = getattr(orch, "settings", None) or {}
    bot = settings.get("bot") if isinstance(settings, dict) else None
    if isinstance(bot, dict) and "scan_interval_minutes" in bot:
        return int(bot["scan_interval_minutes"])
    return 12


def register_agent_routes(app: Any, svc: AgentService) -> None:
    router = APIRouter(
        prefix="/api/agent",
        dependencies=[Depends(require_agent_token)],
    )

    @router.post("/scan")
    async def scan() -> dict:
        return svc.scan()

    @router.get("/scan/status")
    async def scan_status() -> dict:
        return svc.get_scan_status()

    @router.get("/opportunities")
    async def list_opportunities(
        limit: int = Query(20, ge=1, le=100),
    ) -> list:
        return svc.list_opportunities(limit=limit)

    @router.get("/opportunities/{target_id}")
    async def get_opportunity(target_id: str) -> dict:
        item = svc.get_opportunity(target_id, include_reply=True)
        if item is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        return item

    @router.post("/opportunities/{target_id}/generate-reply")
    async def generate_reply(target_id: str) -> dict:
        return svc.generate_reply(target_id)

    @router.post("/opportunities/{target_id}/revise-reply")
    async def revise_reply(target_id: str, body: ReviseBody) -> dict:
        return svc.revise_reply(
            target_id,
            body.instruction,
            current_draft=body.current_draft,
        )

    @router.post("/opportunities/{target_id}/skip")
    async def skip(target_id: str, body: SkipBody = SkipBody()) -> dict:
        return svc.skip(target_id, reason=body.reason)

    @router.post("/opportunities/{target_id}/approve-post")
    async def approve_post(target_id: str, body: ApproveBody = ApproveBody()) -> dict:
        return svc.approve_post(target_id, body.reply_text)

    @router.get("/schedule")
    async def schedule() -> dict:
        return {"scan_interval_minutes": _scan_interval_minutes(svc.orch)}

    app.include_router(router)
