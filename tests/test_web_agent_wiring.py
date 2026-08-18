from fastapi.testclient import TestClient

from dashboard.web import WebDashboard


def test_webdashboard_mounts_agent_routes(fake_orch, monkeypatch):
    monkeypatch.setenv("MILO_WEB_PASS", "testdash")
    monkeypatch.setenv("MILO_AGENT_TOKEN", "agent-secret")
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
