from datetime import UTC, datetime

import httpx

from daily_frontier_intelligence.collector import collect


def test_local_fixture_dry_run():
    feed = (
        b"<rss version='2.0'><channel><item><title>Agent release</title>"
        b"<link>https://example.test/a?utm_source=f</link>"
        b"<pubDate>Wed, 15 Jul 2026 00:00:00 GMT</pubDate>"
        b"<description>New model</description></item></channel></rss>"
    )
    source = {
        "id": "fixture",
        "name": "Fixture",
        "url": "https://fixture.test/feed",
        "kind": "rss",
        "categories": ["ai"],
        "tier": 1,
        "language": "en",
        "region": "global",
        "enabled": True,
        "notes": "",
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=feed))
    ) as client:
        items, health = collect(
            {"sources": [source], "interests": {"keywords": {"agent": 2}}},
            48,
            10,
            client,
            datetime(2026, 7, 15, tzinfo=UTC),
        )
    assert len(items) == 1 and health[0]["status"] == "success"
