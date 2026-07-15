import json

import httpx
import pytest

from daily_frontier_intelligence.notion import NOTION_VERSION, publish, verify_page
from daily_frontier_intelligence.report import validate_report


def sample():
    manifest = {
        "run_id": "r1",
        "generated_at": "2026-07-15T00:00:00Z",
        "items": [
            {
                "content_hash": f"h{i}",
                "url": f"https://x.test/{i}",
                "categories": ["ai"],
                "source_id": f"s{i}",
            }
            for i in range(3)
        ],
        "source_health": [{"source_id": "s0", "status": "success"}],
    }
    report = {
        "run_id": "r1",
        "date": "2026-07-15",
        "timezone": "Asia/Shanghai",
        "title": "每日前沿日报",
        "tldr": "TL;DR：摘要",
        "top_items": [
            {
                "content_hash": f"h{i}",
                "title": f"Title {i}",
                "url": f"https://x.test/{i}",
                "fact": "Fact",
                "why_it_matters": "Why",
                "uncertainty": "Unknown",
                "confidence": "high",
                "high_stakes": False,
                "additional_sources": [],
            }
            for i in range(3)
        ],
        "radar": ["weak signal"],
        "source_health_summary": "all good",
    }
    return report, manifest


def extra_source(
    name="Authority",
    url="https://authority.test/evidence",
    role="corroboration",
    publisher_id="authority",
    retrieved_at="2026-07-15T00:00:00Z",
):
    return {
        "name": name,
        "url": url,
        "role": role,
        "publisher_id": publisher_id,
        "retrieved_at": retrieved_at,
    }


def test_report_schema_linkage_and_duplicate_hashes():
    report, manifest = sample()
    validate_report(report, manifest)
    report["top_items"][0]["url"] = "https://evil.test/"
    with pytest.raises(ValueError, match="original URL"):
        validate_report(report, manifest)
    report, manifest = sample()
    report["top_items"][1]["content_hash"] = "h0"
    report["top_items"][1]["url"] = "https://x.test/0"
    with pytest.raises(ValueError, match="unique"):
        validate_report(report, manifest)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", ""),
        ("title", "x" * 121),
        ("tldr", "TL;DR：" + "x" * 995),
        ("source_health_summary", ""),
        ("radar", [""]),
        ("radar", ["x" * 501]),
    ],
)
def test_report_required_fields_are_nonempty_and_bounded(field, value):
    report, manifest = sample()
    report[field] = value
    with pytest.raises(ValueError):
        validate_report(report, manifest)


def test_report_validates_additional_sources_and_high_stakes_corroboration():
    report, manifest = sample()
    manifest["items"][0]["categories"] = ["policy"]
    report["top_items"][0]["high_stakes"] = True
    with pytest.raises(ValueError, match="independent corroboration"):
        validate_report(report, manifest)
    report["top_items"][0]["additional_sources"] = [extra_source()]
    validate_report(report, manifest)
    report["top_items"][0]["additional_sources"].append(
        extra_source(name="Duplicate", role="context", publisher_id="duplicate")
    )
    with pytest.raises(ValueError, match="unique"):
        validate_report(report, manifest)


def notion_page(page_id, run_id="r1"):
    return {
        "id": page_id,
        "properties": {"Run ID": {"rich_text": [{"plain_text": run_id}]}},
    }


def test_notion_exact_run_id_is_idempotent_and_queries_only_run_id():
    report, manifest = sample()
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"results": [notion_page("existing-page")]})

    with httpx.Client(
        base_url="https://api.notion.com", transport=httpx.MockTransport(handler)
    ) as client:
        page = publish(
            report,
            manifest,
            {"notion_database_id": "db", "notion_data_source_id": "ds"},
            "token",
            client,
        )
    assert page == "existing-page" and len(seen) == 1
    assert seen[0].headers["notion-version"] == NOTION_VERSION
    assert json.loads(seen[0].content)["filter"] == {
        "property": "Run ID",
        "rich_text": {"equals": "r1"},
    }


def test_notion_same_date_different_run_is_conflict():
    report, manifest = sample()
    responses = [{"results": []}, {"results": [notion_page("old", "other-run")]}]

    def handler(request):
        return httpx.Response(200, json=responses.pop(0))

    with httpx.Client(
        base_url="https://api.notion.com", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ValueError, match="different Run ID"):
            publish(
                report,
                manifest,
                {"notion_database_id": "db", "notion_data_source_id": "ds"},
                "token",
                client,
            )


def test_notion_payload_has_properties_sections_all_sources_and_chunked_text():
    report, manifest = sample()
    report["top_items"][0]["fact"] = "x" * 4100
    report["top_items"][0]["additional_sources"] = [
        extra_source(name="Context", url="https://context.test/a", role="context")
    ]
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json={"id": "created-page"})

    with httpx.Client(
        base_url="https://api.notion.com", transport=httpx.MockTransport(handler)
    ) as client:
        assert (
            publish(
                report,
                manifest,
                {"notion_database_id": "db", "notion_data_source_id": "ds"},
                "token",
                client,
            )
            == "created-page"
        )
    payload = json.loads(requests[-1].content)
    assert set(payload["properties"]) == {
        "Name",
        "Date",
        "Status",
        "Run ID",
        "Item Count",
        "Source Count",
        "Confidence",
        "Topics",
        "Timezone",
    }
    assert payload["properties"]["Status"] == {"select": {"name": "Published"}}
    assert payload["properties"]["Confidence"] == {"number": 1.0}
    blocks = payload["children"]
    rendered = json.dumps(blocks, ensure_ascii=False)
    assert all(
        label in rendered
        for label in (
            "TL;DR",
            "事实",
            "为何重要",
            "不确定性",
            "来源",
            "研究与工程雷达",
            "来源健康",
            "Context",
        )
    )
    rich_texts = []
    for block in blocks:
        rich_texts.extend(block[block["type"]].get("rich_text", []))
    assert all(len(part["text"]["content"]) <= 2000 for part in rich_texts)
    assert "x" * 4100 in "".join(part["text"]["content"] for part in rich_texts)
    assert len(blocks) < 100


def test_notion_payload_counts_and_tags_only_selected_report_sources():
    report, manifest = sample()
    report["top_items"][0]["additional_sources"] = [
        {
            "name": "Independent",
            "url": "https://evidence.example/independent",
            "role": "corroboration",
            "publisher_id": "independent",
            "retrieved_at": "2026-07-15T00:00:00Z",
        }
    ]
    manifest["items"][0]["categories"] = ["agents", "security"]
    manifest["items"].append(
        {
            **manifest["items"][0],
            "content_hash": "not-selected",
            "source_id": "unselected-source",
            "url": "https://unselected.example/story",
            "canonical_url": "https://unselected.example/story",
            "categories": ["chips", "policy"],
        }
    )

    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json={"id": "created-page"})

    with httpx.Client(
        base_url="https://api.notion.com", transport=httpx.MockTransport(handler)
    ) as client:
        publish(
            report,
            manifest,
            {"notion_database_id": "db", "notion_data_source_id": "ds"},
            "token",
            client,
        )
    payload = json.loads(requests[-1].content)
    assert payload["properties"]["Source Count"]["number"] == 2
    topics = {item["name"] for item in payload["properties"]["Topics"]["multi_select"]}
    assert {"agents", "security"} <= topics
    assert "chips" not in topics
    assert "policy" not in topics


def test_notion_rejects_missing_response_id():
    report, manifest = sample()
    replies = [{"results": []}, {"results": []}, {}]
    with httpx.Client(
        base_url="https://api.notion.com",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=replies.pop(0))),
    ) as client:
        with pytest.raises(ValueError, match="page id"):
            publish(
                report,
                manifest,
                {"notion_database_id": "db", "notion_data_source_id": "ds"},
                "token",
                client,
            )


def test_high_stakes_corroboration_must_use_an_independent_host():
    report, manifest = sample()
    report["top_items"][0]["high_stakes"] = True
    report["top_items"][0]["additional_sources"] = [
        extra_source(name="Same publisher", url="https://x.test/context")
    ]
    with pytest.raises(ValueError, match="different host"):
        validate_report(report, manifest)


def test_radar_may_be_empty():
    report, manifest = sample()
    report["radar"] = []
    validate_report(report, manifest)


def test_report_date_uses_generated_at_timezone_and_children_cap():
    report, manifest = sample()
    manifest["generated_at"] = "2026-07-14T17:00:00Z"
    validate_report(report, manifest)
    report["date"] = "2026-07-14"
    with pytest.raises(ValueError, match="does not match"):
        validate_report(report, manifest)
    report, manifest = sample()
    report["top_items"] = []
    manifest["items"] = []
    for i in range(8):
        manifest["items"].append(
            {"content_hash": f"h{i}", "url": f"https://x.test/{i}", "categories": ["ai"]}
        )
        report["top_items"].append(
            {
                "content_hash": f"h{i}",
                "title": f"T{i}",
                "url": f"https://x.test/{i}",
                "fact": "F",
                "why_it_matters": "W",
                "uncertainty": "U",
                "confidence": "high",
                "high_stakes": False,
                "additional_sources": [
                    extra_source(
                        name=f"E{j}",
                        url=f"https://e{i}-{j}.test/x",
                        role="context",
                        publisher_id=f"e{i}-{j}",
                    )
                    for j in range(20)
                ],
            }
        )
    with pytest.raises(ValueError, match="children count"):
        validate_report(report, manifest)


def test_high_stakes_corroboration_rejects_same_publisher_on_different_host():
    report, manifest = sample()
    report["top_items"][0]["high_stakes"] = True
    report["top_items"][0]["additional_sources"] = [
        extra_source(url="https://different-host.test/evidence", publisher_id="s0")
    ]
    with pytest.raises(ValueError, match="independent corroboration"):
        validate_report(report, manifest)


@pytest.mark.parametrize("retrieved_at", [None, "", "not-a-date", "2026-07-15T00:00:00"])
def test_additional_source_rejects_missing_or_malformed_retrieved_at(retrieved_at):
    report, manifest = sample()
    source = extra_source()
    if retrieved_at is None:
        del source["retrieved_at"]
    else:
        source["retrieved_at"] = retrieved_at
    report["top_items"][0]["additional_sources"] = [source]
    with pytest.raises(ValueError, match="retrieved_at"):
        validate_report(report, manifest)


def test_verify_page_paginates_and_detects_missing_content():
    report, _ = sample()
    properties = {
        "Run ID": {"type": "rich_text", "rich_text": [{"plain_text": "r1"}]},
        "Date": {"type": "date", "date": {"start": "2026-07-15"}},
        "Status": {"type": "select", "select": {"name": "Published"}},
        "Item Count": {"type": "number", "number": 3},
        "Source Count": {"type": "number", "number": 1},
    }

    def block(kind, text, url=None):
        rich = {"plain_text": text, "text": {"content": text}}
        if url:
            rich["href"] = url
        return {"type": kind, kind: {"rich_text": [rich]}}

    blocks = [block("heading_1", "TL;DR"), block("paragraph", report["tldr"])]
    blocks += [block("heading_2", item["title"], item["url"]) for item in report["top_items"]]
    blocks += [block("heading_1", "研究与工程雷达"), block("heading_1", "来源健康")]
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.startswith("/v1/pages/"):
            return httpx.Response(
                200, json={"properties": properties, "url": "https://notion.so/page"}
            )
        if "start_cursor" not in request.url.params:
            return httpx.Response(
                200, json={"results": blocks[:3], "has_more": True, "next_cursor": "next"}
            )
        return httpx.Response(200, json={"results": blocks[3:], "has_more": False})

    with httpx.Client(
        base_url="https://api.notion.com", transport=httpx.MockTransport(handler)
    ) as client:
        receipt = verify_page(report, "page", {}, "token", client)
    assert receipt["page_id"] == "page" and receipt["run_id"] == "r1"
    assert any("start_cursor=next" in str(call.url) for call in calls)
    report["tldr"] = "TL;DR：missing"
    with httpx.Client(
        base_url="https://api.notion.com", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ValueError, match="TL;DR"):
            verify_page(report, "page", {}, "token", client)
