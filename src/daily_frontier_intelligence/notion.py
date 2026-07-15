from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

NOTION_VERSION = "2026-03-11"
RICH_TEXT_LIMIT = 2000


def _rich(text: str, url: str | None = None) -> list[dict[str, Any]]:
    parts = []
    for start in range(0, len(text), RICH_TEXT_LIMIT):
        value: dict[str, Any] = {
            "type": "text",
            "text": {"content": text[start : start + RICH_TEXT_LIMIT]},
        }
        if url:
            value["text"]["link"] = {"url": url}
        parts.append(value)
    return parts or [{"type": "text", "text": {"content": ""}}]


def _block(kind: str, text: str, url: str | None = None) -> dict[str, Any]:
    return {"object": "block", "type": kind, kind: {"rich_text": _rich(text, url)}}


def _query(
    client: httpx.Client, data_source_id: str, headers: dict[str, str], filter_: dict[str, Any]
) -> list[dict[str, Any]]:
    response = client.post(
        f"/v1/data_sources/{data_source_id}/query", headers=headers, json={"filter": filter_}
    )
    response.raise_for_status()
    data = response.json()
    results = data.get("results", [])
    if not isinstance(results, list):
        raise ValueError("Notion query response has invalid results")
    return results


def publish(
    report: dict[str, Any],
    manifest: dict[str, Any],
    config: dict[str, str],
    token: str,
    client: httpx.Client | None = None,
) -> str:
    if not token.strip():
        raise ValueError("Notion token is required")
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
        "User-Agent": "daily-frontier-intelligence/1.0.0",
    }
    owned = client is None
    client = client or httpx.Client(base_url="https://api.notion.com", timeout=20)
    try:
        data_source_id = config["notion_data_source_id"]
        run_results = _query(
            client,
            data_source_id,
            headers,
            {"property": "Run ID", "rich_text": {"equals": report["run_id"]}},
        )
        if run_results:
            page_id = run_results[0].get("id")
            if not isinstance(page_id, str) or not page_id:
                raise ValueError("Notion response is missing page id")
            return page_id

        date_results = _query(
            client,
            data_source_id,
            headers,
            {"property": "Date", "date": {"equals": report["date"]}},
        )
        if date_results:
            raise ValueError("Notion date already exists with a different Run ID")

        children = [_block("heading_1", "TL;DR"), _block("paragraph", report["tldr"])]
        for item in report["top_items"]:
            children.extend(
                [
                    _block("heading_2", item["title"], item["url"]),
                    _block("paragraph", f"事实：{item['fact']}"),
                    _block("paragraph", f"为何重要：{item['why_it_matters']}"),
                    _block(
                        "paragraph",
                        f"不确定性：{item['uncertainty']}（{item['confidence']}）",
                    ),
                    _block("paragraph", f"来源：{item['url']}", item["url"]),
                ]
            )
            for extra in item["additional_sources"]:
                children.append(
                    _block(
                        "paragraph",
                        f"{extra['name']}（{extra['role']}）：{extra['url']}",
                        extra["url"],
                    )
                )
        children.extend(
            [
                _block("heading_1", "研究与工程雷达"),
                *[_block("bulleted_list_item", entry) for entry in report["radar"]],
                _block("heading_1", "来源健康"),
                _block("paragraph", report["source_health_summary"]),
            ]
        )

        confidences = [item["confidence"] for item in report["top_items"]]
        confidence_rank = {"low": 0, "medium": 1, "high": 2}
        confidence = min(confidences, key=lambda value: confidence_rank[value])
        manifest_by_hash = {
            item.get("content_hash"): item
            for item in manifest.get("items", [])
            if item.get("content_hash")
        }
        selected_manifest_items = [
            manifest_by_hash[item["content_hash"]] for item in report["top_items"]
        ]
        topics = sorted(
            {
                category
                for item in selected_manifest_items
                for category in item.get("categories", [])
            }
        )
        source_hosts = {
            urlsplit(item["url"]).hostname
            for item in report["top_items"]
            if urlsplit(item["url"]).hostname
        }
        source_hosts.update(
            urlsplit(extra["url"]).hostname
            for item in report["top_items"]
            for extra in item["additional_sources"]
            if urlsplit(extra["url"]).hostname
        )
        source_count = len(source_hosts)
        payload = {
            "parent": {"type": "database_id", "database_id": config["notion_database_id"]},
            "properties": {
                "Name": {"title": _rich(report["title"])},
                "Date": {"date": {"start": report["date"]}},
                "Status": {"select": {"name": "Published"}},
                "Run ID": {"rich_text": _rich(report["run_id"])},
                "Item Count": {"number": len(report["top_items"])},
                "Source Count": {"number": source_count},
                "Confidence": {"number": {"low": 0.33, "medium": 0.67, "high": 1.0}[confidence]},
                "Topics": {"multi_select": [{"name": topic} for topic in topics]},
                "Timezone": {"rich_text": _rich(report["timezone"])},
            },
            "children": children,
        }
        created = client.post("/v1/pages", headers=headers, json=payload)
        created.raise_for_status()
        page_id = created.json().get("id")
        if not isinstance(page_id, str) or not page_id:
            raise ValueError("Notion response is missing page id")
        return page_id
    finally:
        if owned:
            client.close()


def _plain_rich(value: object) -> str:
    if not isinstance(value, list):
        return ""
    return "".join(
        str(part.get("plain_text", part.get("text", {}).get("content", "")))
        for part in value
        if isinstance(part, dict)
    )


def _property_value(prop: object) -> object:
    if not isinstance(prop, dict):
        return None
    kind = prop.get("type")
    if kind in {"title", "rich_text"}:
        return _plain_rich(prop.get(str(kind)))
    if kind == "date" and isinstance(prop.get("date"), dict):
        return prop["date"].get("start")
    if kind == "select" and isinstance(prop.get("select"), dict):
        return prop["select"].get("name")
    if kind == "number":
        return prop.get("number")
    # Also accept minimal fixtures and stable Notion property shapes without type.
    for candidate in ("title", "rich_text"):
        if candidate in prop:
            return _plain_rich(prop[candidate])
    for candidate in ("date", "select"):
        if isinstance(prop.get(candidate), dict):
            return prop[candidate].get("start" if candidate == "date" else "name")
    return prop.get("number")


def verify_page(
    report: dict[str, Any],
    page_id: str,
    config: dict[str, str],
    token: str,
    client: httpx.Client | None = None,
) -> dict[str, str]:
    if not token.strip() or not page_id.strip():
        raise ValueError("Notion token and page id are required")
    headers = {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION}
    owned = client is None
    client = client or httpx.Client(base_url="https://api.notion.com", timeout=20)
    try:
        page_response = client.get(f"/v1/pages/{page_id}", headers=headers)
        page_response.raise_for_status()
        page = page_response.json()
        properties = page.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("Notion page has invalid properties")
        source_hosts = {urlsplit(item["url"]).hostname for item in report["top_items"]} | {
            urlsplit(extra["url"]).hostname
            for item in report["top_items"]
            for extra in item["additional_sources"]
        }
        expected = {
            "Run ID": report["run_id"],
            "Date": report["date"],
            "Status": "Published",
            "Item Count": len(report["top_items"]),
            "Source Count": len(source_hosts),
        }
        for name, value in expected.items():
            if _property_value(properties.get(name)) != value:
                raise ValueError(f"Notion verification failed: {name}")

        blocks: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, str | int] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            response = client.get(f"/v1/blocks/{page_id}/children", headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            results = data.get("results")
            if not isinstance(results, list) or not all(isinstance(x, dict) for x in results):
                raise ValueError("Notion block response has invalid results")
            blocks.extend(results)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not isinstance(cursor, str) or not cursor:
                raise ValueError("Notion pagination is missing next_cursor")
        texts: list[str] = []
        headings: set[str] = set()
        links: set[str] = set()
        for block in blocks:
            kind = block.get("type")
            body = block.get(kind, {}) if isinstance(kind, str) else {}
            rich = body.get("rich_text", []) if isinstance(body, dict) else []
            text = _plain_rich(rich)
            texts.append(text)
            if kind in {"heading_1", "heading_2", "heading_3"}:
                headings.add(text)
            for part in rich if isinstance(rich, list) else []:
                if isinstance(part, dict):
                    href = part.get("href")
                    linked = (
                        part.get("text", {}).get("link", {})
                        if isinstance(part.get("text"), dict)
                        else {}
                    )
                    url = href or (linked.get("url") if isinstance(linked, dict) else None)
                    if isinstance(url, str):
                        links.add(url)
        if report["tldr"] not in texts:
            raise ValueError("Notion verification failed: literal TL;DR paragraph")
        required_headings = {"TL;DR", "研究与工程雷达", "来源健康"} | {
            item["title"] for item in report["top_items"]
        }
        if not required_headings <= headings:
            raise ValueError("Notion verification failed: headings")
        required_links = {item["url"] for item in report["top_items"]} | {
            extra["url"] for item in report["top_items"] for extra in item["additional_sources"]
        }
        if not required_links <= links:
            raise ValueError("Notion verification failed: links")
        url = page.get("url")
        if not isinstance(url, str):
            url = f"https://www.notion.so/{page_id.replace('-', '')}"
        return {
            "run_id": report["run_id"],
            "page_id": page_id,
            "url": url,
            "verified_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
    finally:
        if owned:
            client.close()
