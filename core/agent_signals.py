"""Flatten opportunity rows for Buzz digest cards."""

from __future__ import annotations

import json
from typing import Any, Dict


def parse_metadata(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def opportunity_to_signal(
    row: Dict[str, Any], include_reply: bool = False,
) -> Dict[str, Any]:
    meta = parse_metadata(row.get("metadata"))
    sub = row.get("subreddit_or_query") or meta.get("subreddit") or ""
    tid = str(row.get("target_id") or "")
    url = meta.get("url") or ""
    if not url and row.get("platform") == "reddit" and tid:
        url = (
            f"https://www.reddit.com/r/{sub}/comments/{tid}/"
            if sub
            else f"https://redd.it/{tid}"
        )
    signal = {
        "target_id": tid,
        "title": row.get("title") or "",
        "subreddit": sub,
        "url": url,
        "project": row.get("project") or "",
        "status": row.get("status") or "",
        "score": row.get("score"),
        "dottie_score": meta.get("dottie_score"),
        "final_score": meta.get("final_score") or row.get("score"),
        "why": meta.get("why") or meta.get("summary") or "",
        "category": meta.get("category") or "",
        "urgency": meta.get("urgency") or "",
        "group_size": meta.get("group_size") or "",
        "meetup_title": meta.get("meetup_title") or "",
        "meetup_description": meta.get("meetup_description") or "",
    }
    if include_reply:
        signal["reply_draft"] = meta.get("reply_draft") or meta.get("reply_text") or ""
    return signal
