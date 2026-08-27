import threading

from core.agent_service import AgentService


def test_list_omits_reply(db, fake_orch):
    db.log_opportunity(
        "reddit",
        "tid1",
        "Hike?",
        "toronto",
        8.0,
        "dottie",
        metadata={"why": "weekend", "reply_draft": "NOPE"},
    )
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)
    items = svc.list_opportunities()
    assert len(items) == 1
    assert "reply_draft" not in items[0]
    assert items[0]["why"] == "weekend"


def test_generate_reply_persists_draft(db, fake_orch):
    db.log_opportunity(
        "reddit",
        "tid1",
        "Hike?",
        "toronto",
        8.0,
        "dottie",
        metadata={"summary": "looking for hikers"},
    )
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)
    result = svc.generate_reply("tid1")
    assert result["ok"] is True
    assert result["reply_draft"] == "generated comment"
    got = svc.get_opportunity("tid1", include_reply=True)
    assert got["reply_draft"] == "generated comment"
    kwargs = fake_orch.content_gen.generate_reddit_comment.call_args.kwargs
    assert kwargs["meetup_context"] is not None
    assert kwargs["post_body"] == "looking for hikers"


def test_generate_reply_dottie_passes_hang_context(db, fake_orch):
    db.log_opportunity(
        "reddit",
        "1vr85w8",
        "Cozy Cinema Social #3 -August 29 at 8:30 pm (in-person; Leslieville)",
        "TorontoEvents",
        9.4,
        "dottie",
        metadata={
            "discovery": "dottie_llm",
            "why": "Small public coffee-shop cinema social",
            "meetup_title": "Cozy Cinema Social",
            "activity_type": "cinema",
            "urgency": "This Month",
            "summary": "",
            "url": "https://www.reddit.com/r/TorontoEvents/comments/1vr85w8/",
        },
    )
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)
    result = svc.generate_reply("1vr85w8")
    assert result["ok"] is True
    kwargs = fake_orch.content_gen.generate_reddit_comment.call_args.kwargs
    ctx = kwargs["meetup_context"]
    assert ctx["meetup_title"] == "Cozy Cinema Social"
    assert "cinema social" in ctx["why"]
    assert kwargs["post_body"] == "Small public coffee-shop cinema social"


def test_generate_reply_missing(fake_orch):
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)
    result = svc.generate_reply("missing")
    assert result["ok"] is False
    assert "not found" in result["error"].lower()


def test_revise_reply_uses_instruction(db, fake_orch):
    db.log_opportunity(
        "reddit",
        "tid1",
        "Hike?",
        "toronto",
        8.0,
        "dottie",
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


def test_get_scan_status_running_state_normalizes_running(fake_orch):
    fake_orch._scan_status["state"] = "running"
    fake_orch._scan_running = False
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)
    status = svc.get_scan_status()
    assert status["state"] == "running"
    assert status["running"] is True


def test_scan_running_true_before_orchestrator_sets_flag(fake_orch):
    """scan() must not return state=running with running=False."""
    scan_started = threading.Event()
    release_scan = threading.Event()

    def blocked_scan(**_):
        scan_started.set()
        assert release_scan.wait(timeout=5)

    fake_orch._scan_all_safe.side_effect = blocked_scan
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)

    out = svc.scan()

    assert scan_started.wait(timeout=5)
    assert out["scan"]["state"] == "running"
    assert out["scan"]["running"] is True
    assert fake_orch._scan_running is False

    release_scan.set()


def test_scan_starts_force_thread(fake_orch):
    scan_called = threading.Event()
    fake_orch._scan_all_safe.side_effect = lambda **_: scan_called.set()
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)
    out = svc.scan()
    assert out["ok"] is True
    assert out["already_running"] is False
    assert out["job_id"]
    assert scan_called.wait(timeout=1)
    fake_orch._scan_all_safe.assert_called_with(force=True)


def test_scan_preserves_completed_status_after_start(fake_orch, monkeypatch):
    class ImmediateThread:
        def __init__(self, *, target, daemon):
            self.target = target
            self.daemon = daemon

        def start(self):
            self.target()

    def complete_scan(**_):
        fake_orch._scan_status.update(
            {
                "state": "completed",
                "message": "Done",
                "finished_at": "now",
            },
        )

    fake_orch._scan_all_safe.side_effect = complete_scan
    monkeypatch.setattr("core.agent_service.threading.Thread", ImmediateThread)
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)

    out = svc.scan()

    assert out["scan"]["state"] == "completed"
    assert out["scan"]["running"] is False


def test_scan_already_running(fake_orch):
    fake_orch._scan_running = True
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)
    out = svc.scan()
    assert out["already_running"] is True
    fake_orch._scan_all_safe.assert_not_called()


def test_concurrent_scan_calls_start_only_one_scan(fake_orch):
    class BarrierLock:
        def __init__(self):
            self.barrier = threading.Barrier(2)
            self.lock = threading.Lock()

        def __enter__(self):
            self.barrier.wait(timeout=5)
            self.lock.acquire()
            return self

        def __exit__(self, *_):
            self.lock.release()

    scan_started = threading.Event()
    release_scan = threading.Event()

    def blocked_scan(**_):
        scan_started.set()
        assert release_scan.wait(timeout=5)

    fake_orch._state_lock = BarrierLock()
    fake_orch._scan_all_safe.side_effect = blocked_scan
    svc = AgentService(fake_orch, emergency_stopped_fn=lambda: False)
    results = []

    callers = [
        threading.Thread(target=lambda: results.append(svc.scan()))
        for _ in range(2)
    ]
    for caller in callers:
        caller.start()
    assert scan_started.wait(timeout=5)
    for caller in callers:
        caller.join(timeout=5)
    release_scan.set()

    assert len(results) == 2
    started = next(result for result in results if not result["already_running"])
    duplicate = next(result for result in results if result["already_running"])
    assert duplicate["job_id"] == started["job_id"]
    assert duplicate["scan"]["running"] is True
    assert fake_orch._scan_all_safe.call_count == 1


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
