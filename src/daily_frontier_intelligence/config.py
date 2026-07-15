from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .security import validate_public_url

REQUIRED_SOURCE_FIELDS = {
    "id",
    "name",
    "url",
    "kind",
    "categories",
    "tier",
    "language",
    "region",
    "enabled",
    "notes",
}


def load_sources(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid source configuration: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise ValueError("source configuration must contain a sources list")
    if len(data["sources"]) > 100:
        raise ValueError("sources must contain at most 100 entries")
    interests = data.get("interests", {})
    if not isinstance(interests, dict):
        raise ValueError("interests must be an object")
    ids: set[str] = set()
    for index, source in enumerate(data["sources"]):
        path_name = f"sources[{index}]"
        if not isinstance(source, dict) or REQUIRED_SOURCE_FIELDS - source.keys():
            raise ValueError(f"{path_name} is missing required fields")
        types = {
            "id": str,
            "name": str,
            "url": str,
            "kind": str,
            "categories": list,
            "tier": int,
            "language": str,
            "region": str,
            "enabled": bool,
            "notes": str,
        }
        for key, expected in types.items():
            if type(source[key]) is not expected or (  # noqa: E721 - reject bool as integer
                expected is str and not source[key].strip()
            ):
                raise ValueError(f"{path_name}.{key} has invalid type or value")
        if "allow_updated_as_published" in source and not isinstance(
            source["allow_updated_as_published"], bool
        ):
            raise ValueError(f"{path_name}.allow_updated_as_published must be boolean")
        if source["kind"] not in {"rss", "atom", "arxiv_query"}:
            raise ValueError(f"unsupported source kind: {source['kind']}")
        validate_public_url(source["url"], field=f"{path_name}.url")
        if source["id"] in ids:
            raise ValueError(f"duplicate source id: {source['id']}")
        ids.add(source["id"])
        if (
            not source["categories"]
            or not all(isinstance(x, str) and x for x in source["categories"])
            or not 1 <= source["tier"] <= 3
        ):
            raise ValueError(f"invalid categories or tier for {source['id']}")
    for field in ("category_weights", "keywords"):
        value = interests.get(field, {})
        if not isinstance(value, dict):
            raise ValueError(f"interests.{field} must be an object")
        for key, weight in value.items():
            if not isinstance(key, str) or not key or type(weight) not in {int, float}:
                raise ValueError(f"interests.{field} entries must be string-to-number")
    tier_weight = interests.get("tier_weight", 1.0)
    if type(tier_weight) not in {int, float}:
        raise ValueError("interests.tier_weight must be numeric")
    return data


def load_runtime_config(path: str | Path) -> dict[str, str]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid runtime config: {exc}") from exc
    required = {"notion_database_id", "notion_data_source_id", "timezone", "state_db"}
    if not isinstance(data, dict) or required - data.keys():
        raise ValueError("runtime config is missing required fields")
    for key in required:
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError(f"runtime config field {key} must be non-empty")
    return {key: data[key] for key in required}
