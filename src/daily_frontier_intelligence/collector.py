from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import feedparser
import httpx

from .models import Article
from .normalize import deduplicate, normalize_entry
from .security import Resolver, URLValidator

MAX_RESPONSE_BYTES = 5_000_000
USER_AGENT = "daily-frontier-intelligence/1.0.0 (+local Hermes Skill)"


MAX_SOURCE_SECONDS = 30.0
ALLOWED_CONTENT_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
    "application/octet-stream",
}


def _fetch(client: httpx.Client, url: str, *, monotonic=time.monotonic) -> bytes:
    # Redirects are disabled so collection contacts only explicitly configured URLs.
    body = bytearray()
    started = monotonic()
    timeout = httpx.Timeout(20, connect=10, read=10, write=10, pool=10)
    with client.stream(
        "GET",
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        follow_redirects=False,
    ) as response:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type and content_type not in ALLOWED_CONTENT_TYPES:
            raise ValueError(f"unsupported feed content type: {content_type}")
        for chunk in response.iter_bytes(chunk_size=64 * 1024):
            if monotonic() - started > MAX_SOURCE_SECONDS:
                raise httpx.ReadTimeout(
                    "source elapsed deadline exceeded", request=response.request
                )
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError("response exceeds 5 MB limit")
    return bytes(body)


def collect(
    config: dict[str, object],
    since_hours: int = 30,
    max_items: int = 100,
    client: httpx.Client | None = None,
    now: datetime | None = None,
    concurrency: int = 8,
    resolver: Resolver | None = None,
) -> tuple[list[Article], list[dict[str, object]]]:
    if not 1 <= since_hours <= 24 * 30 or not 1 <= max_items <= 1000:
        raise ValueError("since-hours or max-items is outside safe bounds")
    if not 1 <= concurrency <= 16:
        raise ValueError("concurrency is outside safe bounds (1-16)")
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=since_hours)
    interests_value = config.get("interests", {})
    interests = (
        cast(dict[str, object], interests_value) if isinstance(interests_value, dict) else {}
    )
    items: list[Article] = []
    owned = client is None
    client = client or httpx.Client()
    try:
        configured_sources = config.get("sources")
        if not isinstance(configured_sources, list):
            raise ValueError("source configuration must contain a sources list")
        if len(configured_sources) > 100:
            raise ValueError("sources must contain at most 100 entries")
        sources = [
            cast(dict[str, object], source)
            for source in configured_sources
            if isinstance(source, dict) and source.get("enabled") is True
        ]

        validator = URLValidator(resolver=resolver)

        def worker(source: dict[str, object]) -> tuple[list[Article], dict[str, object]]:
            source_items: list[Article] = []
            status, detail, count = "success", "", 0
            try:
                source_url = source.get("url")
                if not isinstance(source_url, str):
                    raise ValueError("source URL must be a string")
                validator.validate(
                    source_url, resolve=owned or resolver is not None, field="source URL"
                )
                parsed: Any = feedparser.parse(_fetch(client, source_url))
                if parsed.bozo and not parsed.entries:
                    status, detail = "parse-error", str(parsed.bozo_exception)[:300]
                else:
                    for raw in parsed.entries[:500]:
                        if len(source_items) >= 100:
                            break
                        try:
                            item = normalize_entry(source, dict(raw), now, interests)
                            validator.validate(
                                item.url, resolve=owned or resolver is not None, field="article URL"
                            )
                            if item.published_at and cutoff <= datetime.fromisoformat(
                                item.published_at.replace("Z", "+00:00")
                            ) <= now + timedelta(hours=6):
                                source_items.append(item)
                                count += 1
                        except ValueError:
                            continue
                    if parsed.bozo:
                        status, detail = "parse-error", str(parsed.bozo_exception)[:300]
                    else:
                        status = "success" if count else "success-empty"
            except httpx.TimeoutException as exc:
                status, detail = "timeout", str(exc)[:300]
            except httpx.HTTPStatusError as exc:
                status, detail = "http-error", f"HTTP {exc.response.status_code}"
            except (httpx.HTTPError, ValueError) as exc:
                status, detail = "http-error", str(exc)[:300]
            return source_items, {
                "source_id": str(source.get("id", "")),
                "status": status,
                "item_count": count,
                "detail": detail,
            }

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            results = list(executor.map(worker, sources))
        for source_items, _ in results:
            items.extend(source_items)
        health = [entry for _, entry in results]
    finally:
        if owned:
            client.close()
    return deduplicate(items)[:max_items], health
