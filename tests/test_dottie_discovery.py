from core.dottie_discovery import (
    SYSTEM_PROMPT,
    DiscoveryResult,
    _extract_json_array,
    filter_opportunities,
    persist_discovery_results,
)


def test_prompt_window_is_three_weeks_not_seven_days():
    assert "next 7 days" not in SYSTEM_PROMPT.lower()
    assert "3 weeks" in SYSTEM_PROMPT
    assert "8–21 days" in SYSTEM_PROMPT or "8-21 days" in SYSTEM_PROMPT
    assert "Do not return only one" in SYSTEM_PROMPT or "only one if several" in SYSTEM_PROMPT


def test_extract_json_strips_qwen_think_block():
    raw = (
        "<think>ignore [ this ] noise</think>\n"
        '{"keepers":[{"target_id": "1vnui5a", "dottie_score": 10}]}'
    )
    items = _extract_json_array(raw)
    assert items is not None
    assert items[0]["target_id"] == "1vnui5a"


def test_extract_keepers_object():
    items = _extract_json_array('{"keepers":[{"target_id":"abc"}]}')
    assert items == [{"target_id": "abc"}]


def test_extract_last_array_not_think_brackets():
    raw = 'scratch [1,2] then keepers [{"target_id":"1vnui5a"}]'
    items = _extract_json_array(raw)
    assert items is not None
    assert items[0]["target_id"] == "1vnui5a"


def test_extract_empty_text_is_unparsed():
    assert _extract_json_array("") is None
    assert _extract_json_array("   ") is None


def test_extract_genuine_empty_array():
    assert _extract_json_array("[]") == []
    assert _extract_json_array('{"keepers":[]}') == []


def test_filter_json_mode_reject_retries_without_format():
    class JsonThenOk:
        def __init__(self):
            self.calls = []

        def generate(self, **kwargs):
            self.calls.append(kwargs.get("response_format"))
            if kwargs.get("response_format"):
                raise RuntimeError("Failed to generate JSON json_validate_failed")
            return '{"keepers":[{"target_id":"1vnui5a","dottie_score":10,"social_potential":4,"community_growth":4}]}'

    llm = JsonThenOk()
    project = {
        "project": {"name": "dottie"},
        "opportunity_discovery": {"enabled": True, "min_dottie_score": 6},
    }
    result = filter_opportunities(
        llm,
        [{"target_id": "1vnui5a", "title": "hike", "relevance_score": 5}],
        project,
    )
    assert llm.calls[0] == {"type": "json_object"}
    assert llm.calls[1] is None
    assert len(result.keepers) == 1
    assert result.skip_rejects is True


def test_filter_retries_then_parses():
    class Flaky:
        calls = 0

        def generate(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return "not json"
            return '{"keepers":[{"target_id":"1vnui5a","dottie_score":10,"social_potential":4,"community_growth":4}]}'

    llm = Flaky()
    project = {
        "project": {"name": "dottie"},
        "opportunity_discovery": {"enabled": True, "min_dottie_score": 6},
    }
    result = filter_opportunities(
        llm,
        [{"target_id": "1vnui5a", "title": "hike", "relevance_score": 5}],
        project,
    )
    assert llm.calls == 2
    assert len(result.keepers) == 1
    assert result.skip_rejects is True


def test_filter_llm_failure_does_not_skip_rejects():
    class Boom:
        def generate(self, **kwargs):
            raise RuntimeError("rate limit")

    project = {
        "project": {"name": "dottie"},
        "opportunity_discovery": {"enabled": True, "min_dottie_score": 6},
    }
    opps = [{"target_id": "1vnui5a", "title": "hike", "relevance_score": 5}]
    result = filter_opportunities(Boom(), opps, project)
    assert result.keepers == []
    assert result.skip_rejects is False
    assert result.evaluated_ids == ["1vnui5a"]


def test_filter_empty_output_untrusted():
    class Empty:
        def generate(self, **kwargs):
            return ""

    project = {
        "project": {"name": "dottie"},
        "opportunity_discovery": {"enabled": True, "min_dottie_score": 6},
    }
    result = filter_opportunities(
        Empty(),
        [{"target_id": "1vnui5a", "title": "hike", "relevance_score": 5}],
        project,
    )
    assert result.skip_rejects is True
    assert result.keepers == []


def test_filter_parses_keepers():
    class Ok:
        def generate(self, **kwargs):
            return (
                '{"keepers":[{"target_id": "1vnui5a", "dottie_score": 10, '
                '"social_potential": 4, "community_growth": 4, '
                '"recurring_potential": 3, "final_score": 8.1, '
                '"why": "public hike"}]}'
            )

    project = {
        "project": {"name": "dottie"},
        "opportunity_discovery": {"enabled": True, "min_dottie_score": 6},
    }
    opps = [
        {
            "target_id": "1vnui5a",
            "title": "Bring Your Own Cup Hike",
            "subreddit": "TorontoEvents",
            "relevance_score": 5.6,
        }
    ]
    result = filter_opportunities(Ok(), opps, project)
    assert result.skip_rejects is True
    assert len(result.keepers) == 1
    assert result.keepers[0]["dottie_score"] == 10


def test_filter_thinking_raises_token_budget():
    captured = {}

    class Capture:
        def generate(self, **kwargs):
            captured.update(kwargs)
            return "[]"

    project = {
        "project": {"name": "dottie"},
        "opportunity_discovery": {
            "enabled": True,
            "thinking": True,
            "max_tokens": 1200,
            "min_dottie_score": 6,
        },
    }
    filter_opportunities(
        Capture(),
        [{"target_id": "1vnui5a", "title": "hike", "relevance_score": 5}],
        project,
    )
    assert captured["max_tokens"] == 2500
    assert captured["extra_body"]["reasoning_effort"] == "default"
    assert captured["extra_body"]["reasoning_format"] == "hidden"
    assert captured.get("response_format") is None


def test_filter_thinking_off_keeps_none_effort():
    captured = {}

    class Capture:
        def generate(self, **kwargs):
            captured.update(kwargs)
            return "[]"

    project = {
        "project": {"name": "dottie"},
        "opportunity_discovery": {
            "enabled": True,
            "thinking": False,
            "max_tokens": 1200,
            "min_dottie_score": 6,
        },
    }
    filter_opportunities(
        Capture(),
        [{"target_id": "1vnui5a", "title": "hike", "relevance_score": 5}],
        project,
    )
    assert captured["max_tokens"] == 1200
    assert captured["extra_body"]["reasoning_effort"] == "none"
    assert captured["response_format"] == {"type": "json_object"}


def test_persist_untrusted_does_not_skip(db):
    db.log_opportunity(
        platform="reddit",
        target_id="1vnui5a",
        title="hike",
        subreddit_or_query="TorontoEvents",
        score=5.6,
        project="dottie",
        status="pending",
    )
    persist_discovery_results(
        db,
        [{"target_id": "1vnui5a", "title": "hike", "subreddit": "TorontoEvents"}],
        DiscoveryResult(keepers=[], evaluated_ids=["1vnui5a"], skip_rejects=False),
        "dottie",
    )
    row = db.get_opportunity("1vnui5a")
    assert row["status"] == "pending"


def test_persist_trusted_empty_skips_evaluated(db):
    db.log_opportunity(
        platform="reddit",
        target_id="1vnui5a",
        title="hike",
        subreddit_or_query="TorontoEvents",
        score=5.6,
        project="dottie",
        status="pending",
    )
    persist_discovery_results(
        db,
        [{"target_id": "1vnui5a", "title": "hike", "subreddit": "TorontoEvents"}],
        DiscoveryResult(keepers=[], evaluated_ids=["1vnui5a"], skip_rejects=True),
        "dottie",
    )
    row = db.get_opportunity("1vnui5a")
    assert row["status"] == "skipped"
