import json


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
    meta = json.loads(row["metadata"])
    assert meta["reply_draft"] == "new draft"
    assert meta["why"] == "updated"
    assert meta["url"] == "https://example.com"


def test_merge_missing_returns_false(db):
    assert db.merge_opportunity_metadata("nope", {"reply_draft": "x"}) is False
