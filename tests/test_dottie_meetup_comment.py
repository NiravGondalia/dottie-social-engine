from unittest.mock import MagicMock

from core.content_gen import ContentGenerator


def test_dottie_meetup_comment_skips_host_coaching():
    llm = MagicMock()
    llm.generate.return_value = "Leslieville at 8:30 works — is it a specific film or more of a hang?"
    gen = ContentGenerator(llm)
    gen.generate_reddit_comment(
        post_title="Cozy Cinema Social #3 -August 29 at 8:30 pm",
        post_body="Small public coffee-shop cinema social",
        subreddit="TorontoEvents",
        project={"project": {"name": "Dottie"}},
        meetup_context={
            "meetup_title": "Cozy Cinema Social",
            "why": "Small public coffee-shop cinema social",
            "activity_type": "cinema",
            "urgency": "This Month",
        },
    )
    prompt = llm.generate.call_args.kwargs["prompt"]
    assert "might actually show up" in prompt
    assert "Do NOT coach the organizer" in prompt
    assert "https://dottie.app" in prompt
    assert "ABSOLUTE RULE: Do NOT mention" not in prompt
    assert "Cozy Cinema Social" in prompt
    assert "QUESTION post" not in prompt
    assert "SHOWCASE post" not in prompt
