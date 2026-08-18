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


def test_zero_final_score_is_kept():
    row = {
        "target_id": "z",
        "title": "t",
        "subreddit_or_query": "toronto",
        "score": 9,
        "project": "dottie",
        "status": "pending",
        "metadata": {"final_score": 0},
    }
    signal = opportunity_to_signal(row)
    assert signal["final_score"] == 0


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
