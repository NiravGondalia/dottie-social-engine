from unittest.mock import MagicMock, patch

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
