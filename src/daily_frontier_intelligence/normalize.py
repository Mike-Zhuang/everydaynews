from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dateutil import parser as date_parser

from .models import Article

TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        raise ValueError("article URL must be absolute HTTP(S)")
    port = f":{parts.port}" if parts.port and parts.port not in {80, 443} else ""
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_KEYS
    ]
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, host + port, path, urlencode(sorted(query)), ""))


def normalized_title(title: str) -> str:
    value = unicodedata.normalize("NFKC", html.unescape(title)).casefold()
    return re.sub(r"[^\w]+", "", value, flags=re.UNICODE)


def parse_date(value: object) -> tuple[str | None, str]:
    if not isinstance(value, str) or not value.strip():
        return None, "unknown"
    try:
        parsed = date_parser.parse(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
            confidence = "inferred_timezone"
        else:
            confidence = "source"
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z"), confidence
    except (ValueError, OverflowError):
        return None, "invalid"


def score_item(
    title: str, summary: str, categories: list[str], tier: int, interests: dict[str, object]
) -> float:
    weights = interests.get("category_weights", {})
    keywords = interests.get("keywords", {})
    tier_weight = interests.get("tier_weight", 1.0)
    if not isinstance(tier_weight, (str, int, float)):
        tier_weight = 1.0
    score = float((4 - tier) * float(tier_weight))
    if isinstance(weights, dict):
        score += sum(float(weights.get(category, 0)) for category in categories)
    text = f"{title} {summary}".casefold()
    if isinstance(keywords, dict):
        score += sum(
            float(weight) for keyword, weight in keywords.items() if str(keyword).casefold() in text
        )
    return round(score, 3)


def normalize_entry(
    source: dict[str, object],
    entry: dict[str, object],
    fetched_at: datetime,
    interests: dict[str, object],
) -> Article:
    title = str(entry.get("title", "")).strip()
    url = str(entry.get("link", "")).strip()
    if not title or not url:
        raise ValueError("entry must contain title and link")
    canonical = canonicalize_url(url)
    date_value = entry.get("published")
    date_source = "source_published"
    if not date_value and source.get("allow_updated_as_published") is True:
        date_value = entry.get("updated")
        date_source = "source_updated"
    published, parsed_confidence = parse_date(date_value)
    confidence = date_source if published else parsed_confidence
    summary = re.sub(r"<[^>]+>", " ", str(entry.get("summary", ""))).strip()
    # The canonical URL is the stable article identity. Publishers often edit headlines after
    # publication; including the title here would make the same article reappear as a new item and
    # could break SQLite finalization against the canonical_url uniqueness constraint.
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    categories_value = source.get("categories")
    if not isinstance(categories_value, list):
        raise ValueError("source categories must be a list")
    categories = [str(value) for value in categories_value]
    tier_value = source.get("tier")
    if not isinstance(tier_value, (str, int)):
        raise ValueError("source tier must be an integer")
    tier = int(tier_value)
    return Article(
        source_id=str(source["id"]),
        source_name=str(source["name"]),
        source_tier=tier,
        categories=categories,
        title=title,
        url=url,
        canonical_url=canonical,
        published_at=published,
        fetched_at=fetched_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        date_confidence=confidence,
        summary=summary,
        language=str(source["language"]),
        region=str(source["region"]),
        content_hash=digest,
        interest_score=score_item(title, summary, categories, tier, interests),
        corroborating_sources=[],
    )


def deduplicate(items: list[Article]) -> list[Article]:
    ordered = sorted(
        items,
        key=lambda x: (-x.interest_score, x.source_tier, x.canonical_url, x.source_id),
    )
    groups: list[list[Article]] = []
    group_by_url: dict[str, int] = {}
    group_by_title: dict[str, int] = {}
    for item in ordered:
        title_key = normalized_title(item.title)
        group_index = group_by_url.get(item.canonical_url, group_by_title.get(title_key))
        if group_index is None:
            group_index = len(groups)
            groups.append([])
        groups[group_index].append(item)
        group_by_url[item.canonical_url] = group_index
        group_by_title[title_key] = group_index

    result: list[Article] = []
    for group in groups:
        primary = group[0]
        corroborating = {
            (other.source_id, other.canonical_url): {
                "source_id": other.source_id,
                "source_name": other.source_name,
                "url": other.url,
                "canonical_url": other.canonical_url,
                "tier": other.source_tier,
            }
            for other in group[1:]
            if (other.source_id, other.canonical_url) != (primary.source_id, primary.canonical_url)
        }
        result.append(
            replace(
                primary,
                corroborating_sources=[corroborating[key] for key in sorted(corroborating)],
            )
        )
    return result
