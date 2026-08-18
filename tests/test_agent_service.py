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
