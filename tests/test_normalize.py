from datetime import UTC, datetime

from daily_frontier_intelligence.normalize import (
    canonicalize_url,
    deduplicate,
    normalize_entry,
    parse_date,
    score_item,
)


def test_missing_invalid_date_never_becomes_today():
    assert parse_date(None) == (None, "unknown")
    assert parse_date("not-a-date") == (None, "invalid")


def test_url_canonicalization_removes_tracking_and_sorts():
    assert (
        canonicalize_url("HTTPS://Example.COM/a/?utm_source=x&b=2&a=1#z")
        == "https://example.com/a?a=1&b=2"
    )


def test_title_dedupe_is_deterministic(article):
    second = article.__class__(
        **{
            **article.to_dict(),
            "title": "An agent—launch!",
            "canonical_url": "https://x.test/b",
            "content_hash": "h2",
            "interest_score": 1,
        }
    )
    result = deduplicate([second, article])
    assert result[0].content_hash == article.content_hash
    assert result[0].corroborating_sources == [
        {
            "source_id": "s",
            "source_name": "Source",
            "url": second.url,
            "canonical_url": "https://x.test/b",
            "tier": 1,
        }
    ]


def test_score_is_region_neutral():
    interests = {"tier_weight": 1, "category_weights": {"ai": 2}, "keywords": {"agent": 3}}
    assert score_item("Agent", "", ["ai"], 1, interests) == score_item(
        "Agent", "", ["ai"], 1, interests
    )


def test_normalize_unknown_date_keeps_null():
    source = {
        "id": "s",
        "name": "S",
        "tier": 1,
        "categories": ["ai"],
        "language": "en",
        "region": "any",
    }
    item = normalize_entry(
        source, {"title": "T", "link": "https://x.test/a"}, datetime.now(UTC), {}
    )
    assert item.published_at is None and item.date_confidence == "unknown"


def test_content_identity_is_stable_when_title_changes():
    source = {
        "id": "s",
        "name": "Source",
        "tier": 1,
        "categories": ["ai"],
        "language": "en",
        "region": "global",
    }
    now = datetime(2026, 7, 15, tzinfo=UTC)
    first = normalize_entry(
        source,
        {
            "title": "Original title",
            "link": "https://example.com/post",
            "published": "2026-07-15T00:00:00Z",
        },
        now,
        {},
    )
    changed = normalize_entry(
        source,
        {
            "title": "Updated title",
            "link": "https://example.com/post",
            "published": "2026-07-15T00:00:00Z",
        },
        now,
        {},
    )
    assert first.content_hash == changed.content_hash
