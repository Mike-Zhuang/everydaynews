import json
import socket
from datetime import UTC, datetime

import httpx
import pytest

from daily_frontier_intelligence.collector import collect
from daily_frontier_intelligence.config import load_sources
from daily_frontier_intelligence.normalize import normalize_entry
from daily_frontier_intelligence.security import URLValidator
from daily_frontier_intelligence.state import State


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/feed",
        "https://user:pass@example.com/feed",
        "https://localhost/feed",
        "https://x.localhost/feed",
        "https://169.254.169.254/latest/meta-data",
        "https://metadata.google.internal/",
        "https://[::1]/feed",
        "https://10.0.0.1/feed",
    ],
)
def test_url_validator_rejects_non_public_targets(url):
    with pytest.raises(ValueError):
        URLValidator().validate(url, resolve=False)


def test_url_validator_rejects_mocked_private_dns_and_caches():
    calls = 0

    def resolver(host, port, *, type):
        nonlocal calls
        calls += 1
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.2", port))]

    validator = URLValidator(resolver=resolver)
    for _ in range(2):
        with pytest.raises(ValueError, match="public"):
            validator.validate("https://news.example/feed")
    assert calls == 1


def test_dates_prefer_published_and_updated_requires_opt_in():
    now = datetime(2026, 7, 15, tzinfo=UTC)
    base = {
        "id": "s",
        "name": "S",
        "tier": 1,
        "categories": ["ai"],
        "language": "en",
        "region": "global",
    }
    entry = {"title": "T", "link": "https://example.com/a", "updated": "2026-07-15T00:00:00Z"}
    assert normalize_entry(base, entry, now, {}).published_at is None
    item = normalize_entry({**base, "allow_updated_as_published": True}, entry, now, {})
    assert item.date_confidence == "source_updated"
    published = normalize_entry(
        {**base, "allow_updated_as_published": True},
        {**entry, "published": "2026-07-14T00:00:00Z"},
        now,
        {},
    )
    assert published.published_at == "2026-07-14T00:00:00Z"
    assert published.date_confidence == "source_published"


def test_future_candidate_is_excluded(monkeypatch):
    source = {
        "id": "s",
        "name": "S",
        "url": "https://feed.example/rss",
        "kind": "rss",
        "categories": ["ai"],
        "tier": 1,
        "language": "en",
        "region": "global",
        "enabled": True,
        "notes": "",
    }
    feed = b"<rss><channel><item><title>Future</title><link>https://news.example/a</link><pubDate>Thu, 1 Jan 2099 00:00:00 GMT</pubDate></item></channel></rss>"
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=feed, headers={"content-type": "application/rss+xml"}
            )
        )
    ) as client:
        items, _ = collect(
            {"sources": [source], "interests": {}},
            client=client,
            now=datetime(2026, 7, 15, tzinfo=UTC),
            resolver=lambda *a, **k: [(socket.AF_INET, 1, 6, "", ("93.184.216.34", 443))],
        )
    assert items == []


def test_publication_date_reservation_is_idempotent_and_unique(tmp_path):
    state = State(tmp_path / "state.db")
    state.begin_run("r1")
    state.begin_run("r2")
    assert state.reserve_publication("2026-07-15", "r1") is None
    assert state.reserve_publication("2026-07-15", "r1") is None
    with pytest.raises(ValueError, match="reserved"):
        state.reserve_publication("2026-07-15", "r2")
    state.complete_publication("2026-07-15", "r1", "page")
    assert state.reserve_publication("2026-07-15", "r1") == "page"


def test_source_count_and_types_are_bounded(tmp_path):
    path = tmp_path / "sources.json"
    source = {
        "id": "s",
        "name": "S",
        "url": "https://example.com/feed",
        "kind": "rss",
        "categories": ["ai"],
        "tier": 1,
        "language": "en",
        "region": "global",
        "enabled": True,
        "notes": "",
    }
    path.write_text(
        json.dumps({"sources": [{**source, "id": str(i)} for i in range(101)], "interests": {}})
    )
    with pytest.raises(ValueError, match="100"):
        load_sources(path)
