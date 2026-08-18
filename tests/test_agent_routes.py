import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.agent_service import AgentService
from dashboard.agent_routes import register_agent_routes


@pytest.fixture
def client(fake_orch, db, monkeypatch):
    monkeypatch.setenv("MILO_AGENT_TOKEN", "agent-secret")
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
