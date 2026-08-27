"""Service operations exposed to authenticated social agents."""

from __future__ import annotations

import threading
import uuid
from typing import Any, Callable, Dict, List, Optional

from core.agent_signals import opportunity_to_signal, parse_metadata


def _reply_post_body(signal: dict, metadata: dict) -> str:
    """Prefer real post text over an empty discovery summary."""
    chunks = []
    for key in ("summary", "meetup_description", "why"):
        val = str(metadata.get(key) or "").strip()
        if val and val not in chunks:
            chunks.append(val)
    if not chunks:
        chunks.append(str(signal.get("title") or "").strip())
    return "\n".join(chunks)


def _dottie_meetup_context(signal: dict, metadata: dict) -> Optional[dict]:
    discovery = str(metadata.get("discovery") or "").lower()
    project = str(signal.get("project") or "").lower()
    if discovery != "dottie_llm" and project != "dottie":
        return None
    return {
        "why": metadata.get("why") or "",
        "meetup_title": metadata.get("meetup_title") or "",
        "activity_type": metadata.get("activity_type") or "",
        "urgency": metadata.get("urgency") or "",
        "url": metadata.get("url") or signal.get("url") or "",
    }


class AgentService:
    """Coordinate scans, opportunity reads, and human-reviewed reply drafts."""

    def __init__(
        self,
        orch: Any,
        *,
        emergency_stopped_fn: Callable[[], bool],
    ) -> None:
        self.orch = orch
        self.emergency_stopped_fn = emergency_stopped_fn

    def scan(self) -> dict:
        """Start a forced discovery scan on a daemon thread."""
        if self.emergency_stopped_fn():
            return {
                "ok": False,
                "already_running": False,
                "job_id": None,
                "error": "Emergency stop active",
                "scan": self.get_scan_status(),
            }

        job_id = uuid.uuid4().hex
        lock = getattr(self.orch, "_state_lock", None)
        if lock is not None:
            with lock:
                already_running, current = self._reserve_scan(job_id)
        else:
            already_running, current = self._reserve_scan(job_id)

        if already_running:
            return {
                "ok": True,
                "already_running": True,
                "job_id": current.get("job_id"),
                "scan": current,
            }

        thread = threading.Thread(
            target=lambda: self.orch._scan_all_safe(force=True),
            daemon=True,
        )
        thread.start()

        scan = self._raw_scan_status()
        return {
            "ok": True,
            "already_running": False,
            "job_id": scan.get("job_id", job_id),
            "scan": scan,
        }

    def get_scan_status(self) -> dict:
        """Return orchestrator scan state with the pending queue size."""
        scan = self._raw_scan_status()
        scan["pending_count"] = len(
            self.orch.db.get_pending_opportunities(limit=500),
        )
        return scan

    def list_opportunities(self, limit: int = 20) -> List[dict]:
        """List scored pending opportunities without private reply drafts."""
        rows = self.orch.db.get_pending_opportunities(limit=limit)
        return [
            opportunity_to_signal(row, include_reply=False)
            for row in rows
        ]

    def get_opportunity(
        self,
        target_id: str,
        include_reply: bool = True,
    ) -> Optional[dict]:
        """Fetch one opportunity as an agent signal."""
        row = self.orch.db.get_opportunity(target_id)
        if row is None:
            return None
        return opportunity_to_signal(row, include_reply=include_reply)

    def generate_reply(self, target_id: str) -> dict:
        """Generate and persist a Reddit reply draft for an opportunity."""
        row = self.orch.db.get_opportunity(target_id)
        if row is None:
            return self._not_found(target_id)

        signal = opportunity_to_signal(row, include_reply=True)
        metadata = parse_metadata(row.get("metadata"))
        post_body = _reply_post_body(signal, metadata)
        meetup_context = _dottie_meetup_context(signal, metadata)
        try:
            text = self.orch.content_gen.generate_reddit_comment(
                post_title=signal["title"],
                post_body=post_body,
                subreddit=signal["subreddit"],
                project=self._project_dict(signal["project"]),
                meetup_context=meetup_context,
            )
            self.orch.db.merge_opportunity_metadata(
                target_id,
                {"reply_draft": text},
            )
        except Exception as exc:
            return {
                "ok": False,
                "target_id": target_id,
                "reply_draft": "",
                "error": str(exc),
            }
        return {
            "ok": True,
            "target_id": target_id,
            "reply_draft": text,
        }

    def revise_reply(
        self,
        target_id: str,
        instruction: str,
        current_draft: str = "",
    ) -> dict:
        """Revise and persist a reply draft according to human direction."""
        row = self.orch.db.get_opportunity(target_id)
        if row is None:
            return self._not_found(target_id)

        draft = current_draft
        if not draft:
            draft = parse_metadata(row.get("metadata")).get("reply_draft") or ""

        system = (
            "You rewrite a Reddit comment. Apply the human instruction. "
            "Return ONLY the new comment text, no quotes or preamble. "
            "If this is a public hang/meetup thread, keep the voice of someone "
            "who might show up — not advice to the organizer."
        )
        user = f"Instruction:\n{instruction}\n\nCurrent comment:\n{draft}"
        try:
            text = self.orch.llm.generate(
                prompt=user,
                system_prompt=system,
                task="creative",
                max_tokens=400,
                temperature=0.5,
            )
            self.orch.db.merge_opportunity_metadata(
                target_id,
                {"reply_draft": text},
            )
        except Exception as exc:
            return {
                "ok": False,
                "target_id": target_id,
                "reply_draft": draft,
                "error": str(exc),
            }
        return {
            "ok": True,
            "target_id": target_id,
            "reply_draft": text,
        }

    def skip(self, target_id: str, reason: str = "human skip") -> dict:
        """Mark a pending opportunity skipped without posting."""
        row = self.orch.db.get_opportunity(target_id)
        if row is None:
            return {
                "ok": False,
                "target_id": target_id,
                "error": "Opportunity not found",
            }
        if row.get("status") != "pending":
            return {
                "ok": False,
                "target_id": target_id,
                "error": (
                    f"Opportunity status is '{row.get('status')}', not pending"
                ),
            }
        skip_reason = (reason or "human skip").strip() or "human skip"
        self.orch.db.skip_opportunity(target_id, reason=skip_reason)
        log_decision = getattr(self.orch.db, "log_decision", None)
        if callable(log_decision):
            log_decision(
                "hitl_skip",
                row.get("platform", "reddit"),
                row.get("project", ""),
                target_id=target_id,
                details=skip_reason,
                outcome="skipped",
            )
        return {"ok": True, "target_id": target_id, "status": "skipped"}

    def approve_post(self, target_id: str, reply_text: str) -> dict:
        """Approve a pending opportunity and post the reply to Reddit."""
        if self.emergency_stopped_fn():
            return {
                "ok": False,
                "target_id": target_id,
                "error": "Emergency stop active — cannot post to Reddit",
            }

        row = self.orch.db.get_opportunity(target_id)
        if row is None:
            return {
                "ok": False,
                "target_id": target_id,
                "error": "Opportunity not found",
            }
        if row.get("status") != "pending":
            return {
                "ok": False,
                "target_id": target_id,
                "error": (
                    f"Opportunity status is '{row.get('status')}', not pending"
                ),
            }

        signal = opportunity_to_signal(row, include_reply=True)
        text = (reply_text or "").strip()
        if not text:
            text = (signal.get("reply_draft") or "").strip()
        if not text:
            return {
                "ok": False,
                "target_id": target_id,
                "error": "No reply text",
            }

        project_name = signal.get("project") or ""
        activity_id = self.orch.db.insert_dottie_activity(
            opportunity_target_id=target_id,
            project=project_name,
            reddit_url=signal.get("url") or "",
            subreddit=signal.get("subreddit") or "",
            meetup_title=signal.get("meetup_title") or "",
            meetup_description=signal.get("meetup_description") or "",
            category=signal.get("category") or "",
            group_size=signal.get("group_size") or "",
            urgency=signal.get("urgency") or "",
            dottie_score=signal.get("dottie_score"),
            final_score=signal.get("final_score") or signal.get("score"),
            why=signal.get("why") or "",
            source_title=signal.get("title") or "",
            reply_text=text,
            reddit_posted=False,
            status="queued",
        )
        self.orch.db.approve_opportunity(target_id)
        log_decision = getattr(self.orch.db, "log_decision", None)
        if callable(log_decision):
            log_decision(
                "hitl_approve",
                row.get("platform", "reddit"),
                project_name,
                target_id=target_id,
                details=f"activity_id={activity_id} post_to_reddit=True",
                outcome="approved",
            )

        reddit_result = self._post_to_reddit(row, signal, text, project_name)
        if reddit_result.get("ok"):
            self.orch.db.update_dottie_activity(
                activity_id,
                reddit_posted=True,
                reddit_comment_id=reddit_result.get("comment_id"),
                status="posted",
            )
            if callable(log_decision):
                log_decision(
                    "hitl_reddit_post",
                    "reddit",
                    project_name,
                    account=reddit_result.get("account", ""),
                    target_id=target_id,
                    details=f"comment_id={reddit_result.get('comment_id')}",
                    outcome="posted",
                )
        elif callable(log_decision):
            log_decision(
                "hitl_reddit_post",
                "reddit",
                project_name,
                account=reddit_result.get("account", ""),
                target_id=target_id,
                details=reddit_result.get("error") or "post failed",
                outcome="failed",
            )

        return {
            "ok": True,
            "target_id": target_id,
            "status": "approved",
            "reddit": reddit_result,
        }

    def _post_to_reddit(
        self,
        row: Dict[str, Any],
        signal: Dict[str, Any],
        reply_text: str,
        project_name: str,
    ) -> Dict[str, Any]:
        """Post via the existing HITL Reddit bot path."""
        account = self.orch.account_mgr.get_next_account(
            "reddit",
            project=project_name,
        )
        if not account:
            return {
                "attempted": True,
                "ok": False,
                "comment_id": None,
                "error": "No available Reddit account",
                "account": "",
            }
        bot = self.orch._get_reddit_bot(account)
        if not hasattr(bot, "post_comment_text"):
            return {
                "attempted": True,
                "ok": False,
                "comment_id": None,
                "error": "Reddit bot does not support HITL post_comment_text",
                "account": account.get("username", ""),
            }
        payload = dict(row)
        payload["subreddit"] = signal.get("subreddit") or payload.get(
            "subreddit_or_query",
            "",
        )
        result = bot.post_comment_text(
            payload,
            reply_text,
            project_name=project_name,
            update_opportunity_status=False,
        )
        out = dict(result) if isinstance(result, dict) else {"ok": bool(result)}
        out["attempted"] = True
        out["account"] = account.get("username", "")
        return out

    def _raw_scan_status(self) -> Dict[str, Any]:
        getter = getattr(self.orch, "get_scan_status", None)
        if callable(getter):
            scan = dict(getter() or {})
        else:
            status = getattr(self.orch, "_scan_status", None)
            scan = dict(status) if isinstance(status, dict) else {}
        if scan.get("state") == "running":
            scan["running"] = True
        return scan

    def _reserve_scan(self, job_id: str) -> tuple[bool, dict]:
        """Atomically inspect and reserve orchestrator scan state."""
        status = getattr(self.orch, "_scan_status", None)
        if not isinstance(status, dict):
            status = {}
            self.orch._scan_status = status

        current = dict(status)
        orchestrator_running = bool(getattr(self.orch, "_scan_running", False))
        already_running = (
            orchestrator_running
            or bool(current.get("running"))
            or current.get("state") == "running"
        )
        current["running"] = already_running
        if orchestrator_running:
            current["state"] = "running"

        if not already_running:
            self._mark_scan_started(status, job_id)
            current = dict(status)
            current["running"] = True
        return already_running, current

    @staticmethod
    def _mark_scan_started(status: dict, job_id: str) -> None:
        status.update(
            {
                "job_id": job_id,
                "state": "running",
                "message": "Scanning…",
            },
        )

    def _project_dict(self, name: str) -> dict:
        name_l = (name or "").strip().lower()
        for project in getattr(self.orch, "projects", None) or []:
            info = project.get("project") or {}
            if (info.get("name") or "").strip().lower() == name_l:
                return project
        return {
            "project": {
                "name": name or "dottie",
                "url": "https://dottie.app",
            },
        }

    @staticmethod
    def _not_found(target_id: str) -> dict:
        return {
            "ok": False,
            "target_id": target_id,
            "reply_draft": "",
            "error": f"Opportunity {target_id!r} not found",
        }
