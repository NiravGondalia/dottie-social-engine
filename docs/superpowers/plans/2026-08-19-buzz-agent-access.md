# Buzz Agent Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Buzz’s Dottie Social agent a stdio MCP over this running MiloAgent so it can scan, list scored signals, generate/revise a reply, and post to Reddit only after a human check reaction.

**Architecture:** Keep Reddit, scoring, and HITL posting inside MiloAgent. Add `AgentService` as the single operator API. Expose it on token-gated FastAPI routes. Ship a stdio MCP process that HTTP-calls those routes (Buzz `mcp_command` spawns that process). Dashboard session auth stays for humans and is not accepted on agent routes.

**Tech Stack:** Python 3.10+, FastAPI, pytest, httpx, existing SQLite `Database`, existing `ContentGenerator` / orchestrator scan, official `mcp` Python SDK (stdio / FastMCP).

## Global Constraints

- MiloAgent stays the scan / score / write / post engine; do not reimplement Reddit posting in Buzz or in the MCP process.
- Do not put Reddit cookies, `MILO_WEB_PASS`, or account passwords in the Buzz persona env.
- Agent routes accept only `MILO_AGENT_TOKEN` as `Authorization: Bearer`; dashboard session tokens must 401.
- `list_opportunities` omits reply bodies. Replies exist only after `generate_reply` / `revise_reply`.
- `approve_post` must refuse when emergency stop is on (same as current HITL).
- Dual clocks: leave the internal APScheduler as-is for the dashboard; Buzz scans are extra `force=True` scans.
- Follow existing code style in `core/` and `dashboard/`; no drive-by refactors of `dashboard/web.py` beyond registering the new router.
- Spec: `docs/superpowers/specs/2026-08-19-buzz-agent-access-design.md`.

## File structure

| File | Responsibility |
|------|----------------|
| `core/agent_auth.py` | Constant-time compare of `MILO_AGENT_TOKEN`. |
| `core/agent_signals.py` | Flatten opportunity rows to signal dicts; strip reply unless asked. |
| `core/agent_service.py` | scan, status, list, get, generate, revise, approve, skip, schedule. |
| `dashboard/agent_routes.py` | FastAPI `/api/agent/*` routes. |
| `agent_mcp/__init__.py` | Package marker. |
| `agent_mcp/__main__.py` | `python -m agent_mcp` entry. |
| `agent_mcp/server.py` | FastMCP tools wrapping HTTP. |
| `tests/conftest.py` | Temp DB + fake orchestrator. |
| `tests/test_agent_auth.py` | Token helper. |
| `tests/test_agent_signals.py` | Digest DTO. |
| `tests/test_agent_service.py` | Service behavior. |
| `tests/test_agent_routes.py` | HTTP auth + contracts. |
| `tests/test_agent_mcp.py` | MCP tool list + HTTP mapping. |
| `AGENTS.md` | Operator rules for Dottie Social. |
| `.agents/skills/milo-social/SKILL.md` | Channel grammar + MCP tools. |
| `docs/buzz/dottie-social-persona.md` | Buzz Desktop paste-in: prompt, `mcp_command`, env. |
| `.env.example` | `MILO_AGENT_TOKEN`, `MILO_AGENT_BASE_URL`. |
| `requirements.txt` | `pytest`, `httpx`, `mcp`. |
| `dashboard/web.py` | Construct `AgentService`, include router. |
| `core/database.py` | `merge_opportunity_metadata`. |

---

### Task 1: Agent token helper

**Files:**
- Create: `core/agent_auth.py`
- Create: `tests/test_agent_auth.py`
- Modify: `requirements.txt` (add `pytest>=8.0` and `httpx>=0.27` at the end)

**Interfaces:**
- Consumes: `os.environ["MILO_AGENT_TOKEN"]`
- Produces: `get_agent_token() -> str`, `agent_token_configured() -> bool`, `verify_agent_token(provided: Optional[str]) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_auth.py
import os

from core.agent_auth import agent_token_configured, get_agent_token, verify_agent_token


def test_unconfigured_when_env_missing(monkeypatch):
    monkeypatch.delenv("MILO_AGENT_TOKEN", raising=False)
    assert agent_token_configured() is False
    assert verify_agent_token("anything") is False


def test_accepts_matching_token(monkeypatch):
    monkeypatch.setenv("MILO_AGENT_TOKEN", "secret-token-value")
    assert agent_token_configured() is True
    assert get_agent_token() == "secret-token-value"
    assert verify_agent_token("secret-token-value") is True
    assert verify_agent_token("wrong") is False
    assert verify_agent_token(None) is False
    assert verify_agent_token("") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_agent_auth.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'core.agent_auth'` (install pytest first if needed: `pip install pytest httpx`).

- [ ] **Step 3: Write minimal implementation**

```python
# core/agent_auth.py
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
```

Append to `requirements.txt`:

```
pytest>=8.0
httpx>=0.27
mcp>=1.9
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_agent_auth.py -v`

Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add core/agent_auth.py tests/test_agent_auth.py requirements.txt
git commit -m "$(cat <<'EOF'
Add machine token helper for Buzz agent access.

EOF
)"
```

---

### Task 2: Signal DTO and opportunity metadata merge

**Files:**
- Create: `core/agent_signals.py`
- Modify: `core/database.py` (add `merge_opportunity_metadata` after `get_opportunity` ~line 926)
- Create: `tests/conftest.py`
- Create: `tests/test_agent_signals.py`
- Create: `tests/test_database_opportunity_metadata.py`

**Interfaces:**
- Consumes: opportunity row dict (`target_id`, `title`, `subreddit_or_query`, `score`, `project`, `status`, `metadata` JSON or dict)
- Produces: `parse_metadata(raw) -> dict`, `opportunity_to_signal(row, include_reply: bool = False) -> dict`, `Database.merge_opportunity_metadata(target_id: str, patch: dict) -> bool`

Signal keys (always): `target_id`, `title`, `subreddit`, `url`, `project`, `status`, `score`, `dottie_score`, `final_score`, `why`, `category`, `urgency`, `group_size`, `meetup_title`, `meetup_description`. If `include_reply` is True, also `reply_draft`; otherwise that key must be absent.

- [ ] **Step 1: Write the failing tests**

```python
# tests/conftest.py
import os
import tempfile

import pytest

from core.database import Database


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    instance = Database(path)
    yield instance
    instance.close()
```

```python
# tests/test_agent_signals.py
from core.agent_signals import opportunity_to_signal


def test_list_signal_omits_reply():
    row = {
        "target_id": "abc123",
        "title": "Anyone hiking Saturday?",
        "subreddit_or_query": "toronto",
        "score": 8.2,
        "project": "dottie",
        "status": "pending",
        "metadata": {
            "url": "https://reddit.com/r/toronto/comments/abc123",
            "dottie_score": 10,
            "final_score": 8.2,
            "why": "Public group hike this week",
            "category": "outdoors",
            "urgency": "This Week",
            "group_size": "4-8",
            "meetup_title": "Saturday hike",
            "meetup_description": "Easy trail",
            "reply_draft": "secret draft",
            "reply_text": "also secret",
        },
    }
    signal = opportunity_to_signal(row, include_reply=False)
    assert "reply_draft" not in signal
    assert "reply_text" not in signal
    assert signal["target_id"] == "abc123"
    assert signal["subreddit"] == "toronto"
    assert signal["dottie_score"] == 10
    assert signal["final_score"] == 8.2
    assert signal["why"] == "Public group hike this week"


def test_include_reply_returns_draft():
    row = {
        "target_id": "abc123",
        "title": "t",
        "subreddit_or_query": "toronto",
        "score": 1,
        "project": "dottie",
        "status": "pending",
        "metadata": {"reply_draft": "hello"},
    }
    signal = opportunity_to_signal(row, include_reply=True)
    assert signal["reply_draft"] == "hello"
```

```python
# tests/test_database_opportunity_metadata.py
def test_merge_opportunity_metadata_patches_json(db):
    db.log_opportunity(
        platform="reddit",
        target_id="tid1",
        title="Hello",
        subreddit_or_query="toronto",
        score=7.0,
        project="dottie",
        metadata={"why": "old", "url": "https://example.com"},
    )
    ok = db.merge_opportunity_metadata("tid1", {"reply_draft": "new draft", "why": "updated"})
    assert ok is True
    row = db.get_opportunity("tid1")
    import json
    meta = json.loads(row["metadata"])
    assert meta["reply_draft"] == "new draft"
    assert meta["why"] == "updated"
    assert meta["url"] == "https://example.com"


def test_merge_missing_returns_false(db):
    assert db.merge_opportunity_metadata("nope", {"reply_draft": "x"}) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_agent_signals.py tests/test_database_opportunity_metadata.py -v`

Expected: FAIL — `core.agent_signals` missing; `Database` has no `merge_opportunity_metadata`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/agent_signals.py
"""Flatten opportunity rows for Buzz digest cards."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


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


def opportunity_to_signal(row: Dict[str, Any], include_reply: bool = False) -> Dict[str, Any]:
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
```

Add this method on `Database` immediately after `get_opportunity`:

```python
    def merge_opportunity_metadata(self, target_id: str, patch: Dict) -> bool:
        """Shallow-merge keys into the opportunity metadata JSON. Returns False if missing."""
        opp = self.get_opportunity(target_id)
        if not opp:
            return False
        meta = {}
        raw = opp.get("metadata")
        if isinstance(raw, dict):
            meta = dict(raw)
        elif isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    meta = parsed
            except (json.JSONDecodeError, TypeError):
                meta = {}
        meta.update(patch)
        self._execute_write(
            "UPDATE opportunities SET metadata = ? WHERE target_id = ?",
            (json.dumps(meta), target_id),
        )
        return True
```

If `Database.close` does not exist, add:

```python
    def close(self) -> None:
        self._closed = True
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None
```

(Only add `close` if tests fail because it is missing. If `close` already exists on the class, do not duplicate it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_agent_signals.py tests/test_database_opportunity_metadata.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/agent_signals.py core/database.py tests/conftest.py tests/test_agent_signals.py tests/test_database_opportunity_metadata.py
git commit -m "$(cat <<'EOF'
Add Buzz signal DTO and opportunity metadata merge.

EOF
)"
```

---

### Task 3: AgentService — scan status, list, generate, revise

**Files:**
- Create: `core/agent_service.py`
- Create: `tests/test_agent_service.py`
- Modify: `tests/conftest.py` (add `fake_orch` fixture)

**Interfaces:**
- Consumes: orchestrator with `db`, `get_scan_status()`, `_scan_all_safe(force=True)`, `_scan_running`, `content_gen.generate_reddit_comment(...)`, `llm.generate(...)`, `projects`, `_emergency_stopped` via dashboard flag passed in, `account_mgr`, `_get_reddit_bot`
- Produces:

```python
class AgentService:
    def __init__(self, orch, *, emergency_stopped_fn) -> None: ...
    def scan(self) -> dict  # {ok, already_running, job_id, scan}
    def get_scan_status(self) -> dict  # {job_id, state, running, message, pending_count}
    def list_opportunities(self, limit: int = 20) -> list[dict]  # signals, no reply
    def get_opportunity(self, target_id: str, include_reply: bool = True) -> Optional[dict]
    def generate_reply(self, target_id: str) -> dict  # {ok, target_id, reply_draft, error?}
    def revise_reply(self, target_id: str, instruction: str, current_draft: str = "") -> dict
```

`scan()` must call `_scan_all_safe(force=True)` on a daemon thread (same as `dashboard/web.py` control_scan). If already running, return `already_running: True` without starting a second thread. Assign `job_id` with `uuid.uuid4().hex` on the orchestrator `_scan_status` dict when starting (set under `_state_lock` if present, else set keys on `_scan_status` then start the thread).

`generate_reply` uses `content_gen.generate_reddit_comment` with `post_title=opp["title"]`, `post_body` from metadata `summary` or `meetup_description` or title, `subreddit` from the signal, `project` looked up by name from `orch.projects` (dict with `project` key) — if no matching project, use `{"project": {"name": opp["project"]}}`. Persist via `db.merge_opportunity_metadata(target_id, {"reply_draft": text})`.

`revise_reply` calls `orch.llm.generate` with a short system prompt: rewrite the Reddit comment per the human instruction; return only the new comment. Persist `reply_draft`. If `current_draft` is empty, read stored `reply_draft`.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/conftest.py
from types import SimpleNamespace
from unittest.mock import MagicMock


@pytest.fixture
def fake_orch(db):
    orch = SimpleNamespace()
    orch.db = db
    orch._scan_running = False
    orch._state_lock = __import__("threading").Lock()
    orch._scan_status = {
        "state": "idle",
        "message": "",
        "started_at": None,
        "finished_at": None,
        "opportunities": 0,
        "job_id": None,
    }
    orch.projects = [{"project": {"name": "dottie", "url": "https://dottie.app"}}]
    orch.get_scan_status = MagicMock(side_effect=lambda: {
        **orch._scan_status,
        "running": orch._scan_running,
    })
    orch._scan_all_safe = MagicMock()
    orch.content_gen = SimpleNamespace(
        generate_reddit_comment=MagicMock(return_value="generated comment")
    )
    orch.llm = SimpleNamespace(
        generate=MagicMock(return_value="revised comment")
    )
    orch.account_mgr = SimpleNamespace(get_next_account=MagicMock(return_value=None))
    orch._get_reddit_bot = MagicMock()
    return orch
```

```python
# tests/test_agent_service.py
from core.agent_service import AgentService


def test_list_omits_reply(db, fake_orch):
    db.log_opportunity(
        "reddit", "tid1", "Hike?", "toronto", 8.0, "dottie",
        metadata={"why": "weekend", "reply_draft": "NOPE"},
    )
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)
    items = svc.list_opportunities()
    assert len(items) == 1
    assert "reply_draft" not in items[0]
    assert items[0]["why"] == "weekend"


def test_generate_reply_persists_draft(db, fake_orch):
    db.log_opportunity(
        "reddit", "tid1", "Hike?", "toronto", 8.0, "dottie",
        metadata={"summary": "looking for hikers"},
    )
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)
    result = svc.generate_reply("tid1")
    assert result["ok"] is True
    assert result["reply_draft"] == "generated comment"
    got = svc.get_opportunity("tid1", include_reply=True)
    assert got["reply_draft"] == "generated comment"


def test_generate_reply_missing(fake_orch):
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)
    result = svc.generate_reply("missing")
    assert result["ok"] is False
    assert "not found" in result["error"].lower()


def test_revise_reply_uses_instruction(db, fake_orch):
    db.log_opportunity(
        "reddit", "tid1", "Hike?", "toronto", 8.0, "dottie",
        metadata={"reply_draft": "long draft"},
    )
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)
    result = svc.revise_reply("tid1", "make it shorter")
    assert result["ok"] is True
    assert result["reply_draft"] == "revised comment"
    fake_orch.llm.generate.assert_called()
    kwargs = fake_orch.llm.generate.call_args
    blob = str(kwargs)
    assert "make it shorter" in blob
    assert "long draft" in blob


def test_scan_starts_force_thread(fake_orch):
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)
    out = svc.scan()
    assert out["ok"] is True
    assert out["already_running"] is False
    assert out["job_id"]
    fake_orch._scan_all_safe.assert_called_with(force=True)


def test_scan_already_running(fake_orch):
    fake_orch._scan_running = True
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)
    out = svc.scan()
    assert out["already_running"] is True
    fake_orch._scan_all_safe.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_agent_service.py -v`

Expected: FAIL — `No module named 'core.agent_service'`.

- [ ] **Step 3: Write `core/agent_service.py`**

Implement `AgentService` with the methods above. Import `opportunity_to_signal` from `core.agent_signals`. Use `threading.Thread(..., daemon=True).start()` for scan, matching `dashboard/web.py` `control_scan`. For `generate_reply`, resolve project as:

```python
def _project_dict(self, name: str) -> dict:
    name_l = (name or "").strip().lower()
    for p in getattr(self.orch, "projects", None) or []:
        info = p.get("project") or {}
        if (info.get("name") or "").strip().lower() == name_l:
            return p
    return {"project": {"name": name or "dottie", "url": "https://dottie.app"}}
```

`revise_reply` system prompt (verbatim):

```
You rewrite a Reddit comment. Apply the human instruction. Return ONLY the new comment text, no quotes or preamble.
```

User prompt: `Instruction:\n{instruction}\n\nCurrent comment:\n{draft}`

Call `self.orch.llm.generate(prompt=user, system_prompt=system, task="creative", max_tokens=400, temperature=0.5)` — if `generate` does not accept those kwargs in this codebase, match `LLMProvider.generate`’s real signature in `core/llm_provider.py` (read it; pass only supported args).

`get_scan_status` should add `pending_count` from `len(self.orch.db.get_pending_opportunities(limit=500))`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_agent_service.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/agent_service.py tests/test_agent_service.py tests/conftest.py
git commit -m "$(cat <<'EOF'
Add AgentService for scan, scored list, and reply drafts.

EOF
)"
```

---

### Task 4: AgentService — approve_post and skip

**Files:**
- Modify: `core/agent_service.py`
- Modify: `tests/test_agent_service.py`
- Modify: `tests/conftest.py` (reddit bot mock)

**Interfaces:**
- Consumes: same HITL sequence as `approve_opportunity` in `dashboard/web.py` (~1241–1355) and `_hitl_post_to_reddit` (~518–548): require pending opportunity, persist dottie activity, `approve_opportunity`, then `bot.post_comment_text(...)`.
- Produces:

```python
def skip(self, target_id: str, reason: str = "human skip") -> dict
def approve_post(self, target_id: str, reply_text: str) -> dict
# approve_post result: {ok, target_id, status, reddit: {attempted, ok, comment_id, error, account}, error?}
```

`approve_post` must:
1. If `emergency_stopped_fn()` is True → `{ok: False, error: "Emergency stop active — cannot post to Reddit"}`.
2. If opportunity missing or not `pending` → `{ok: False, error: "..."}`.
3. Use `reply_text` if non-empty, else stored `reply_draft`. If still empty → `{ok: False, error: "No reply text"}`.
4. Insert dottie activity like the dashboard (call `db.insert_dottie_activity` with the same fields the dashboard uses).
5. `db.approve_opportunity(target_id)`.
6. Get next reddit account; call `post_comment_text` with `update_opportunity_status=False`.
7. On reddit success, `db.update_dottie_activity` posted; return comment_id.
8. Do **not** check Buzz reactions here. The MCP/skill layer is responsible for only calling this after a check. Tests should show the service will post if invoked — that is intentional.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_agent_service.py`)

```python
def test_skip_pending(db, fake_orch):
    db.log_opportunity("reddit", "tid1", "Hike?", "toronto", 8.0, "dottie")
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)
    out = svc.skip("tid1", reason="not a fit")
    assert out["ok"] is True
    assert db.get_opportunity("tid1")["status"] == "skipped"


def test_approve_blocked_by_emergency_stop(db, fake_orch):
    db.log_opportunity("reddit", "tid1", "Hike?", "toronto", 8.0, "dottie")
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: True)
    out = svc.approve_post("tid1", "hi")
    assert out["ok"] is False
    assert "emergency" in out["error"].lower()


def test_approve_posts_via_reddit_bot(db, fake_orch):
    db.log_opportunity(
        "reddit", "tid1", "Hike?", "toronto", 8.0, "dottie",
        metadata={"url": "https://reddit.com/r/toronto/comments/tid1"},
    )
    account = {"username": "poster"}
    fake_orch.account_mgr.get_next_account.return_value = account
    bot = type("B", (), {})()
    bot.post_comment_text = lambda *a, **k: {"ok": True, "comment_id": "c1"}
    fake_orch._get_reddit_bot.return_value = bot
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)
    out = svc.approve_post("tid1", "final copy")
    assert out["ok"] is True
    assert out["reddit"]["ok"] is True
    assert out["reddit"]["comment_id"] == "c1"
    assert db.get_opportunity("tid1")["status"] == "approved"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python3 -m pytest tests/test_agent_service.py::test_approve_posts_via_reddit_bot tests/test_agent_service.py::test_approve_blocked_by_emergency_stop tests/test_agent_service.py::test_skip_pending -v`

Expected: FAIL — methods missing.

- [ ] **Step 3: Implement `skip` and `approve_post`**

Copy field mapping from `dashboard/web.py` `approve_opportunity` / `_hitl_post_to_reddit`. Reuse `opportunity_to_signal(..., include_reply=True)` for meetup fields. Do not import `WebDashboard`. If `insert_dottie_activity` requires many kwargs, pass the same defaults the dashboard uses (`reddit_posted=False`, `status="queued"` then update on success).

- [ ] **Step 4: Run the full service tests**

Run: `python3 -m pytest tests/test_agent_service.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/agent_service.py tests/test_agent_service.py tests/conftest.py
git commit -m "$(cat <<'EOF'
Add AgentService skip and HITL Reddit approve_post.

EOF
)"
```

---

### Task 5: Token-gated `/api/agent` HTTP routes

**Files:**
- Create: `dashboard/agent_routes.py`
- Create: `tests/test_agent_routes.py`
- Modify: `dashboard/web.py` — in `WebDashboard.__init__` after `self.orch = orchestrator`, construct `self.agent_service = AgentService(orchestrator, emergency_stopped_fn=lambda: self._emergency_stopped)` **after** `self._emergency_stopped = False` is set (~line 426). In `_setup_routes`, after `app = self.app`, call `register_agent_routes(app, self.agent_service)`.

**Interfaces:**
- Consumes: `AgentService`, `verify_agent_token`
- Produces: routes (all JSON):

| Method | Path | Body / query | Service call |
|--------|------|--------------|--------------|
| POST | `/api/agent/scan` | — | `scan()` |
| GET | `/api/agent/scan/status` | — | `get_scan_status()` |
| GET | `/api/agent/opportunities` | `limit` default 20 max 100 | `list_opportunities(limit)` |
| GET | `/api/agent/opportunities/{target_id}` | — | `get_opportunity(id, include_reply=True)` 404 if missing |
| POST | `/api/agent/opportunities/{target_id}/generate-reply` | — | `generate_reply` |
| POST | `/api/agent/opportunities/{target_id}/revise-reply` | `{instruction, current_draft?}` | `revise_reply` |
| POST | `/api/agent/opportunities/{target_id}/skip` | `{reason?}` | `skip` |
| POST | `/api/agent/opportunities/{target_id}/approve-post` | `{reply_text?}` | `approve_post` |
| GET | `/api/agent/schedule` | — | `{scan_interval_minutes}` from `orch._bot_settings` or `orch.settings["bot"]["scan_interval_minutes"]` (read whichever exists; default 12) |

Auth: FastAPI dependency. If token not configured → 503 `{"detail": "MILO_AGENT_TOKEN is not set"}`. If Bearer missing/wrong → 401. A dashboard session token (random hex that is not the agent token) must 401.

- [ ] **Step 1: Write the failing HTTP tests**

```python
# tests/test_agent_routes.py
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.agent_routes import register_agent_routes


@pytest.fixture
def client(fake_orch, db, monkeypatch):
    monkeypatch.setenv("MILO_AGENT_TOKEN", "agent-secret")
    from core.agent_service import AgentService
    app = FastAPI()
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)
    register_agent_routes(app, svc)
    return TestClient(app)


def test_agent_route_requires_bearer(client):
    r = client.get("/api/agent/opportunities")
    assert r.status_code == 401


def test_agent_route_rejects_wrong_token(client):
    r = client.get(
        "/api/agent/opportunities",
        headers={"Authorization": "Bearer nope"},
    )
    assert r.status_code == 401


def test_list_opportunities_ok(client, db):
    db.log_opportunity(
        "reddit", "tid1", "Hike?", "toronto", 8.0, "dottie",
        metadata={"why": "weekend", "reply_draft": "HIDDEN"},
    )
    r = client.get(
        "/api/agent/opportunities",
        headers={"Authorization": "Bearer agent-secret"},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert "reply_draft" not in body[0]


def test_scan_ok(client, fake_orch):
    r = client.post(
        "/api/agent/scan",
        headers={"Authorization": "Bearer agent-secret"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    fake_orch._scan_all_safe.assert_called_with(force=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_agent_routes.py -v`

Expected: FAIL — `dashboard.agent_routes` missing.

- [ ] **Step 3: Implement `dashboard/agent_routes.py` and wire `web.py`**

Use `HTTPBearer(auto_error=False)` locally in this module (do not reuse dashboard session `_verify_token`). Pydantic models:

```python
class ReviseBody(BaseModel):
    instruction: str = Field(..., min_length=1, max_length=4000)
    current_draft: str = ""

class SkipBody(BaseModel):
    reason: str = "human skip"

class ApproveBody(BaseModel):
    reply_text: str = ""
```

Service errors (`ok: False`) return HTTP 200 with the service JSON **except** missing opportunity on GET → 404. Keep POST generate/approve as 200 + `{ok: false}` to match existing dashboard control endpoints.

In `web.py`, add imports at the **top of the file** (not inline):

```python
from core.agent_service import AgentService
from dashboard.agent_routes import register_agent_routes
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_agent_routes.py tests/test_agent_service.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/agent_routes.py dashboard/web.py tests/test_agent_routes.py
git commit -m "$(cat <<'EOF'
Expose token-gated /api/agent routes for Buzz MCP.

EOF
)"
```

---

### Task 6: stdio MCP server

**Files:**
- Create: `agent_mcp/__init__.py` (empty)
- Create: `agent_mcp/server.py`
- Create: `agent_mcp/__main__.py`
- Create: `tests/test_agent_mcp.py`

**Interfaces:**
- Consumes: env `MILO_AGENT_BASE_URL` (default `http://127.0.0.1:8420`), `MILO_AGENT_TOKEN`; HTTP routes from Task 5
- Produces: MCP tools named exactly: `scan`, `get_scan_status`, `list_opportunities`, `get_opportunity`, `generate_reply`, `revise_reply`, `approve_post`, `skip`, `get_schedule`

Each tool returns a JSON string (or dict if FastMCP allows) of the HTTP JSON body. HTTP 401/503 become `{ok: false, error: "..."}`. Use `requests` (already in requirements) with timeout 120 for scan, 30 otherwise.

Tool arguments:

- `list_opportunities(limit: int = 20)`
- `get_opportunity(target_id: str)`
- `generate_reply(target_id: str)`
- `revise_reply(target_id: str, instruction: str, current_draft: str = "")`
- `approve_post(target_id: str, reply_text: str = "")`
- `skip(target_id: str, reason: str = "human skip")`
- `scan()`, `get_scan_status()`, `get_schedule()` — no args

Do **not** add a tool that posts without going through `approve_post`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_mcp.py
from unittest.mock import patch, MagicMock

from agent_mcp.server import TOOL_SPECS, call_agent_api, tool_handlers


def test_tool_names_match_spec():
    assert set(TOOL_SPECS) == {
        "scan",
        "get_scan_status",
        "list_opportunities",
        "get_opportunity",
        "generate_reply",
        "revise_reply",
        "approve_post",
        "skip",
        "get_schedule",
    }


def test_list_opportunities_hits_http(monkeypatch):
    monkeypatch.setenv("MILO_AGENT_TOKEN", "t")
    monkeypatch.setenv("MILO_AGENT_BASE_URL", "http://127.0.0.1:8420")
    fake = MagicMock()
    fake.json.return_value = [{"target_id": "x"}]
    fake.status_code = 200
    with patch("agent_mcp.server.requests.request", return_value=fake) as req:
        out = tool_handlers["list_opportunities"](limit=5)
    assert out == [{"target_id": "x"}]
    args, kwargs = req.call_args
    assert kwargs["method"] == "GET"
    assert kwargs["url"].endswith("/api/agent/opportunities")
    assert kwargs["headers"]["Authorization"] == "Bearer t"
    assert kwargs["params"]["limit"] == 5
```

Factor the HTTP client as `call_agent_api(method, path, json=None, params=None)` so tests can patch `requests.request`. `TOOL_SPECS` is a tuple/list of tool name strings. `tool_handlers` maps name → callable used by FastMCP wrappers.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_agent_mcp.py -v`

Expected: FAIL — `agent_mcp.server` missing.

- [ ] **Step 3: Implement MCP**

`agent_mcp/server.py` outline:

```python
import os
import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("milo-agent")
TOOL_SPECS = (...)

def _base() -> str:
    return (os.environ.get("MILO_AGENT_BASE_URL") or "http://127.0.0.1:8420").rstrip("/")

def call_agent_api(method, path, json=None, params=None):
    token = (os.environ.get("MILO_AGENT_TOKEN") or "").strip()
    try:
        resp = requests.request(
            method,
            _base() + path,
            json=json,
            params=params,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=120 if path.endswith("/scan") else 30,
        )
    except requests.RequestException as e:
        return {"ok": False, "error": str(e)}
    if resp.status_code == 401:
        return {"ok": False, "error": "unauthorized"}
    if resp.status_code == 503:
        return {"ok": False, "error": "MILO_AGENT_TOKEN is not set on the server"}
    try:
        return resp.json()
    except ValueError:
        return {"ok": False, "error": resp.text[:300]}

# define tool_handlers then @mcp.tool() wrappers that call them
```

`agent_mcp/__main__.py`:

```python
from agent_mcp.server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

If FastMCP’s import path differs in the installed `mcp` version, use whatever `python3 -c "import mcp; print(mcp.__file__)"` shows — prefer `from mcp.server.fastmcp import FastMCP`. Do not invent HTTP MCP.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_agent_mcp.py -v`

Expected: PASS. Also: `python3 -m pytest tests/ -v` green.

- [ ] **Step 5: Commit**

```bash
git add agent_mcp tests/test_agent_mcp.py requirements.txt
git commit -m "$(cat <<'EOF'
Add stdio MCP server that calls /api/agent.

EOF
)"
```

---

### Task 7: Orientation files and env

**Files:**
- Create: `AGENTS.md`
- Create: `.agents/skills/milo-social/SKILL.md`
- Create: `docs/buzz/dottie-social-persona.md`
- Modify: `.env.example`
- Modify: `docs/superpowers/specs/2026-08-19-buzz-agent-access-design.md` (set Status to `approved`)

**Interfaces:**
- Consumes: settled decisions D1–D8 in the spec
- Produces: files a Buzz operator can copy into Desktop / nest

- [ ] **Step 1: Write `AGENTS.md` at repo root** with these rules (do not weaken them):

```markdown
# MiloAgent — agent notes

This process is the Reddit engine. Buzz Dottie Social is the operator.

## You may
- Call MCP tools (or `/api/agent/*` with `MILO_AGENT_TOKEN`) to scan, list scored signals, generate/revise replies, skip, and approve_post.
- Post numbered digests in Buzz. Explore only after a human picks a signal.

## You may not
- Put Reddit cookies or passwords in Buzz env.
- Call `approve_post` unless you observed a check reaction on the **latest draft** in that signal’s thread.
- Treat a check on the scan digest as publish.
- Generate replies for every signal at scan time.

## Loop
1. scan → wait get_scan_status until not running → list_opportunities
2. Numbered digest + one card per signal
3. `explore N` or thread reply → generate_reply
4. Human edits → revise_reply
5. Check on latest draft → approve_post → report comment URL
```

- [ ] **Step 2: Write `.agents/skills/milo-social/SKILL.md`**

Include: skill name `milo-social`; digest field list from the spec; explore grammar (`explore 3`, `explore 3 and 7`, thread reply); check-reaction rules; MCP tool table matching Task 6 names; `python -m agent_mcp` as the stdio command.

- [ ] **Step 3: Write `docs/buzz/dottie-social-persona.md`**

Include: display name `Dottie Social`; system prompt summarizing the loop; `mcp_command`: `python -m agent_mcp` (absolute python + `cwd` this repo); env `MILO_AGENT_BASE_URL=http://127.0.0.1:8420` and `MILO_AGENT_TOKEN` (set in the wrapper, not in the prompt); Alfred may @mention this agent; this persona must not receive Reddit credentials; how to create a Buzz `schedule` workflow that @mentions Dottie Social (YAML `trigger.on: schedule` + `action: send_message` text that says `scan`).

- [ ] **Step 4: Update `.env.example`**

Add after the dashboard auth block:

```
# ── Buzz / MCP machine token (not the dashboard login) ──
# MILO_AGENT_TOKEN=
# MILO_AGENT_BASE_URL=http://127.0.0.1:8420
```

Set spec status line to `approved`.

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md .agents/skills/milo-social/SKILL.md docs/buzz/dottie-social-persona.md .env.example docs/superpowers/specs/2026-08-19-buzz-agent-access-design.md
git commit -m "$(cat <<'EOF'
Document Dottie Social HITL loop and Buzz persona setup.

EOF
)"
```

---

### Task 8: Smoke the HTTP surface with TestClient against WebDashboard wiring

**Files:**
- Create: `tests/test_web_agent_wiring.py`

**Interfaces:**
- Consumes: `WebDashboard` constructor
- Produces: proof `register_agent_routes` is mounted on the real app

WebDashboard needs a real orchestrator. If constructing `WebDashboard(fake_orch)` runs too much middleware, skip full init and instead assert the source contains the register call **and** add a test that instantiates `WebDashboard` with `fake_orch` if `__init__` only needs `orch` (it does). Patch env `MILO_WEB_PASS=testdash` (min 6 chars) so startup does not generate a random password.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_web_agent_wiring.py
from fastapi.testclient import TestClient


def test_webdashboard_mounts_agent_routes(fake_orch, monkeypatch):
    monkeypatch.setenv("MILO_WEB_PASS", "testdash")
    monkeypatch.setenv("MILO_AGENT_TOKEN", "agent-secret")
    from dashboard.web import WebDashboard
    dash = WebDashboard(fake_orch)
    client = TestClient(dash.app)
    r = client.get(
        "/api/agent/opportunities",
        headers={"Authorization": "Bearer agent-secret"},
    )
    assert r.status_code == 200
    r401 = client.get("/api/agent/opportunities")
    assert r401.status_code == 401
    # session-style token is not the agent token
    r_wrong = client.get(
        "/api/agent/opportunities",
        headers={"Authorization": "Bearer testdash"},
    )
    assert r_wrong.status_code == 401
```

- [ ] **Step 2: Run it**

Run: `python3 -m pytest tests/test_web_agent_wiring.py -v`

Expected: FAIL until Task 5 wired `register_agent_routes`. If Task 5 is done, this should PASS. If `__init__` crashes because `fake_orch` lacks attributes, add only the attributes `WebDashboard.__init__` touches (read the constructor; stub `SimpleNamespace` fields). Do not mock FastAPI.

- [ ] **Step 3: Fix wiring or fake_orch until PASS**

Run: `python3 -m pytest tests/ -v`

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_web_agent_wiring.py dashboard/web.py tests/conftest.py
git commit -m "$(cat <<'EOF'
Verify WebDashboard mounts Buzz agent routes.

EOF
)"
```

---

## Manual verification (after code)

1. `python3 miloagent.py run --web` with `MILO_AGENT_TOKEN` set.
2. `curl -H "Authorization: Bearer $MILO_AGENT_TOKEN" http://127.0.0.1:8420/api/agent/opportunities`
3. `MILO_AGENT_TOKEN=... python3 -m agent_mcp` — Buzz Desktop `mcp_command` pointed at that.
4. In Buzz: create Dottie Social from `docs/buzz/dottie-social-persona.md`, @mention scan, explore, revise, check-react, confirm Reddit via existing HITL post.

## Out of plan (matches spec)

- Rewriting the dashboard HITL UI
- Twitter/Telegram MCP tools
- Pausing the 12-minute APScheduler
- HTTP MCP (Buzz is stdio-only)

---

## Self-review

**Spec coverage**

| Spec item | Task |
|-----------|------|
| Machine auth `MILO_AGENT_TOKEN` | 1, 5 |
| Waitable scan / job handle | 3 (`job_id` + `get_scan_status`) |
| list without reply bodies | 2, 3, 5 |
| generate_reply / revise_reply | 3 |
| approve_post existing HITL path | 4 |
| skip | 4 |
| stdio MCP tools | 6 |
| AGENTS.md + milo-social skill | 7 |
| Buzz persona + schedule docs | 7 |
| Emergency stop blocks post | 4 |
| Session token not valid on agent routes | 5, 8 |
| Dual-clock default (internal scheduler stays) | Global constraints + persona doc |
| Check reaction not implemented as a Reddit-side gate | 4 comment + AGENTS.md / skill (Dottie Social must observe the check before calling the tool) |

**Placeholders:** none remaining.

**Types:** `AgentService` method names are identical in Tasks 3–6. MCP tool names match the spec table.
