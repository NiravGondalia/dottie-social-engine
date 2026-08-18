"""Service operations exposed to authenticated social agents."""

from __future__ import annotations

import threading
import uuid
from typing import Any, Callable, Dict, List, Optional

from core.agent_signals import opportunity_to_signal, parse_metadata


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
        if scan.get("state") == "running":
            scan["running"] = True
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
        post_body = (
            metadata.get("summary")
            or metadata.get("meetup_description")
            or signal["title"]
        )
        try:
            text = self.orch.content_gen.generate_reddit_comment(
                post_title=signal["title"],
                post_body=post_body,
                subreddit=signal["subreddit"],
                project=self._project_dict(signal["project"]),
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
            "Return ONLY the new comment text, no quotes or preamble."
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

    def _raw_scan_status(self) -> Dict[str, Any]:
        getter = getattr(self.orch, "get_scan_status", None)
        if callable(getter):
            return dict(getter() or {})
        status = getattr(self.orch, "_scan_status", None)
        return dict(status) if isinstance(status, dict) else {}

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
