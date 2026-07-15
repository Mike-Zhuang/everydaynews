from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .security import validate_public_url

CONFIDENCE = {"high", "medium", "low"}
SOURCE_ROLES = {"corroboration", "context", "primary"}


def _bounded_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be non-empty and at most {maximum} characters")
    return value


def _absolute_url(value: object, field: str) -> str:
    return validate_public_url(value, field=field)


def _aware_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a timezone-aware ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be a timezone-aware ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware ISO-8601 timestamp")
    return parsed


def load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def validate_report(report: dict[str, Any], manifest: dict[str, Any]) -> None:
    required = {
        "run_id",
        "date",
        "timezone",
        "title",
        "tldr",
        "top_items",
        "radar",
        "source_health_summary",
    }
    if not isinstance(report, dict) or required - report.keys():
        raise ValueError("report is missing required fields")
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    try:
        if not isinstance(report["date"], str) or not isinstance(report["timezone"], str):
            raise TypeError
        zone = ZoneInfo(report["timezone"])
        generated_at = _aware_timestamp(manifest["generated_at"], "manifest.generated_at")
        generated_date = generated_at.astimezone(zone).date().isoformat()
        if report["date"] != generated_date:
            raise ValueError("report.date does not match manifest.generated_at in report.timezone")
    except KeyError as exc:
        raise ValueError("manifest.generated_at is required") from exc
    except (ValueError, TypeError, ZoneInfoNotFoundError) as exc:
        if "does not match" in str(exc):
            raise
        raise ValueError("invalid report date or timezone") from exc
    if not isinstance(report["run_id"], str) or report["run_id"] != manifest.get("run_id"):
        raise ValueError("report run_id does not match manifest")
    _bounded_text(report["title"], "title", 120)
    tldr = _bounded_text(report["tldr"], "tldr", 1000)
    _bounded_text(report["source_health_summary"], "source_health_summary", 1000)
    if not tldr.startswith("TL;DR："):
        raise ValueError("tldr must start with TL;DR：")
    items = report["top_items"]
    if not isinstance(items, list) or not 3 <= len(items) <= 8:
        raise ValueError("top_items must contain 3-8 items")
    raw_manifest_items = manifest.get("items")
    if not isinstance(raw_manifest_items, list):
        raise ValueError("manifest.items must be a list")
    manifest_items: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(raw_manifest_items):
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("content_hash"), str)
            or not isinstance(value.get("url"), str)
        ):
            raise ValueError(f"manifest.items[{index}] has invalid boundaries")
        _absolute_url(value["url"], f"manifest.items[{index}].url")
        manifest_items[value["content_hash"]] = value
    hashes: set[str] = set()
    for item in items:
        needed = {
            "content_hash",
            "title",
            "url",
            "fact",
            "why_it_matters",
            "uncertainty",
            "confidence",
            "high_stakes",
            "additional_sources",
        }
        if not isinstance(item, dict) or needed - item.keys():
            raise ValueError("top item is missing required fields")
        if not isinstance(item["content_hash"], str) or not item["content_hash"]:
            raise ValueError("top item content_hash must be a non-empty string")
        source = manifest_items.get(item["content_hash"])
        if item["content_hash"] in hashes:
            raise ValueError("top item content_hash values must be unique")
        hashes.add(item["content_hash"])
        if not source or item["url"] != source["url"]:
            raise ValueError("top item must link to an original URL in the manifest")
        _absolute_url(item["url"], "top item URL")
        _bounded_text(item["title"], "top item title", 300)
        _bounded_text(item["fact"], "fact", 10000)
        _bounded_text(item["why_it_matters"], "why_it_matters", 5000)
        _bounded_text(item["uncertainty"], "uncertainty", 5000)
        if not isinstance(item["confidence"], str) or item["confidence"] not in CONFIDENCE:
            raise ValueError("invalid confidence label")
        if not isinstance(item["high_stakes"], bool):
            raise ValueError("high_stakes must be boolean")
        additional = item["additional_sources"]
        if not isinstance(additional, list) or len(additional) > 20:
            raise ValueError("additional_sources must be a list of at most 20 sources")
        source_urls: set[str] = set()
        primary_host = urlsplit(item["url"]).hostname
        primary_publisher_id = source.get("source_id")
        independent_corroboration = False
        for extra in additional:
            expected_fields = {"name", "url", "role", "publisher_id", "retrieved_at"}
            if not isinstance(extra, dict) or set(extra) != expected_fields:
                raise ValueError(
                    "additional source must contain exactly name, url, role, publisher_id, "
                    "and retrieved_at"
                )
            _bounded_text(extra["name"], "additional source name", 200)
            publisher_id = _bounded_text(extra["publisher_id"], "publisher_id", 100)
            retrieved_at = _aware_timestamp(extra["retrieved_at"], "retrieved_at")
            if retrieved_at < generated_at - timedelta(hours=1):
                raise ValueError("retrieved_at precedes manifest.generated_at by more than 1 hour")
            if retrieved_at > datetime.now(UTC) + timedelta(minutes=5):
                raise ValueError("retrieved_at is over 5 minutes in the future")
            url = _absolute_url(extra["url"], "additional source URL")
            if url in source_urls:
                raise ValueError("additional source URLs must be unique")
            source_urls.add(url)
            if not isinstance(extra["role"], str) or extra["role"] not in SOURCE_ROLES:
                raise ValueError("invalid additional source role")
            if (
                extra["role"] == "corroboration"
                and urlsplit(url).hostname != primary_host
                and isinstance(primary_publisher_id, str)
                and bool(primary_publisher_id.strip())
                and publisher_id != primary_publisher_id
            ):
                independent_corroboration = True
        if item["high_stakes"] and not independent_corroboration:
            raise ValueError(
                "high-stakes item requires independent corroboration from a different host "
                "and publisher_id"
            )
    if not isinstance(report["radar"], list) or len(report["radar"]) > 20:
        raise ValueError("radar must contain at most 20 entries")
    for entry in report["radar"]:
        _bounded_text(entry, "radar entry", 500)
    children_count = (
        2 + sum(5 + len(item["additional_sources"]) for item in items) + 3 + len(report["radar"])
    )
    if children_count > 100:
        raise ValueError(f"Notion create children count {children_count} exceeds 100")
