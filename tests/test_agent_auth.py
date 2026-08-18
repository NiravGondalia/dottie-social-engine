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
