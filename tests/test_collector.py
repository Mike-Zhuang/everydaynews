from datetime import UTC, datetime

import httpx

import threading
import time

import pytest

from daily_frontier_intelligence.collector import MAX_RESPONSE_BYTES, _fetch, collect


def source(source_id):
    return {
        "id": source_id,
        "name": source_id,
        "url": f"https://{source_id}.test/feed",
        "kind": "rss",
        "categories": ["ai"],
        "tier": 1,
        "language": "en",
        "region": "global",
        "enabled": True,
        "notes": "",
    }


class OversizedStream(httpx.SyncByteStream):
    def __init__(self):
        self.bytes_yielded = 0

    def __iter__(self):
        while True:
            self.bytes_yielded += 1_000_000
            yield b"x" * 1_000_000


def test_fetch_rejects_oversized_stream_before_reading_unbounded_body():
    stream = OversizedStream()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(ValueError, match="5 MB"):
            _fetch(client, "https://large.test/feed")
    assert stream.bytes_yielded == 6_000_000
    assert stream.bytes_yielded <= MAX_RESPONSE_BYTES + 1_000_000


def test_fetch_rejects_html_and_elapsed_slow_drip():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=b"<html/>", headers={"content-type": "text/html"}
            )
        )
    ) as client:
        with pytest.raises(ValueError, match="content type"):
            _fetch(client, "https://feed.test/rss")

    ticks = iter([0.0, 31.0])
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"<rss/>")
        )
    ) as client:
        with pytest.raises(httpx.ReadTimeout, match="elapsed deadline"):
            _fetch(client, "https://feed.test/rss", monotonic=lambda: next(ticks))


def test_collection_inspects_500_entries_and_accepts_100_per_source():
    entries = "".join(
        f"<item><title>T{i}</title><link>https://news.test/{i}</link>"
        "<pubDate>Wed, 15 Jul 2026 00:00:00 GMT</pubDate></item>"
        for i in range(600)
    )
    feed = f"<rss><channel>{entries}</channel></rss>".encode()
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=feed))
    ) as client:
        items, health = collect(
            {"sources": [source("bounded")], "interests": {}},
            client=client,
            now=datetime(2026, 7, 15, 1, tzinfo=UTC),
            max_items=1000,
        )
    assert len(items) == 100
    assert health[0]["item_count"] == 100


def test_source_failure_tolerated_and_unknown_dates_excluded():
    feed = b"""<rss version='2.0'><channel><item><title>Old unknown</title><link>https://x.test/u</link></item></channel></rss>"""

    def handler(request):
        if "bad" in str(request.url):
            return httpx.Response(500)
        return httpx.Response(200, content=feed)

    sources = [source(x) for x in ("good", "bad")]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        items, health = collect(
            {"sources": sources, "interests": {}}, client=client, now=datetime.now(UTC)
        )
    assert items == []
    assert [x["status"] for x in health] == ["success-empty", "http-error"]


def test_concurrent_collection_keeps_deterministic_order_and_isolates_failures():
    active = 0
    peak = 0
    lock = threading.Lock()

    def handler(request):
        nonlocal active, peak
        source_id = request.url.host.split(".")[0]
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep({"one": 0.04, "two": 0.01, "three": 0.02}[source_id])
        with lock:
            active -= 1
        if source_id == "two":
            raise httpx.ConnectError("isolated", request=request)
        feed = (
            f"<rss><channel><item><title>{source_id}</title>"
            f"<link>https://news.test/{source_id}</link>"
            "<pubDate>Wed, 15 Jul 2026 00:00:00 GMT</pubDate>"
            "</item></channel></rss>"
        ).encode()
        return httpx.Response(200, content=feed)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        items, health = collect(
            {"sources": [source(x) for x in ("one", "two", "three")], "interests": {}},
            client=client,
            now=datetime(2026, 7, 15, 1, tzinfo=UTC),
            concurrency=2,
        )
    assert peak == 2
    assert [entry["source_id"] for entry in health] == ["one", "two", "three"]
    assert [entry["status"] for entry in health] == ["success", "http-error", "success"]
    assert [item.source_id for item in items] == ["one", "three"]


@pytest.mark.parametrize("value", [0, 17])
def test_concurrency_has_safe_bounds(value):
    with pytest.raises(ValueError, match="concurrency"):
        collect({"sources": []}, concurrency=value)
