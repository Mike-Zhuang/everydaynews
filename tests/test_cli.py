import json
import sqlite3

import httpx
import pytest

from daily_frontier_intelligence import cli
from daily_frontier_intelligence.state import State


def source_config(tmp_path):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"sources": [], "interests": {}}), encoding="utf-8")
    return path


def test_collect_creates_output_parents_and_manifest_metadata(tmp_path, monkeypatch, article):
    monkeypatch.setattr(
        cli,
        "collect",
        lambda *args, **kwargs: (
            [article],
            [{"source_id": "s", "status": "success", "item_count": 1, "detail": ""}],
        ),
    )
    output = tmp_path / "nested" / "manifest.json"
    assert (
        cli.main(
            [
                "collect",
                "--config",
                str(source_config(tmp_path)),
                "--state-db",
                str(tmp_path / "state.db"),
                "--output",
                str(output),
                "--since-hours",
                "24",
                "--concurrency",
                "4",
            ]
        )
        == 0
    )
    manifest = json.loads(output.read_text())
    assert manifest["window_hours"] == 24
    assert manifest["candidate_count"] == 1
    assert manifest["generated_at"].endswith("Z")
    assert manifest["health_summary"] == {"success": 1}


def test_collect_excludes_seen_by_default_and_include_seen_overrides(
    tmp_path, monkeypatch, article
):
    monkeypatch.setattr(cli, "collect", lambda *args, **kwargs: ([article], []))
    config = source_config(tmp_path)
    state_path = tmp_path / "state.db"
    first = tmp_path / "first.json"
    assert (
        cli.main(
            [
                "collect",
                "--config",
                str(config),
                "--state-db",
                str(state_path),
                "--output",
                str(first),
            ]
        )
        == 0
    )
    run_id = json.loads(first.read_text())["run_id"]
    from daily_frontier_intelligence.state import State

    State(state_path).finalize(run_id, [], "page")
    second = tmp_path / "second.json"
    assert (
        cli.main(
            [
                "collect",
                "--config",
                str(config),
                "--state-db",
                str(state_path),
                "--output",
                str(second),
            ]
        )
        == 0
    )
    assert json.loads(second.read_text())["items"] == []
    third = tmp_path / "third.json"
    assert (
        cli.main(
            [
                "collect",
                "--config",
                str(config),
                "--state-db",
                str(state_path),
                "--output",
                str(third),
                "--include-seen",
            ]
        )
        == 0
    )
    assert len(json.loads(third.read_text())["items"]) == 1


def test_cli_catches_httpx_and_sqlite_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "collect", lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError("offline"))
    )
    args = [
        "collect",
        "--config",
        str(source_config(tmp_path)),
        "--state-db",
        str(tmp_path / "state.db"),
        "--output",
        str(tmp_path / "out.json"),
    ]
    assert cli.main(args) == 2
    assert "error: offline" in capsys.readouterr().err
    monkeypatch.setattr(
        cli, "State", lambda path: (_ for _ in ()).throw(sqlite3.OperationalError("locked"))
    )
    assert cli.main(args) == 2
    assert "error: locked" in capsys.readouterr().err


def finalize_files(tmp_path, *, reservation_page="page-1"):
    manifest = {
        "run_id": "r1",
        "generated_at": "2026-07-15T00:00:00Z",
        "items": [
            {"content_hash": f"h{i}", "url": f"https://news.example/{i}", "source_id": f"s{i}"}
            for i in range(3)
        ],
    }
    report = {
        "run_id": "r1",
        "date": "2026-07-15",
        "timezone": "Asia/Shanghai",
        "title": "Daily",
        "tldr": "TL;DR：summary",
        "top_items": [
            {
                "content_hash": f"h{i}",
                "title": f"Title {i}",
                "url": f"https://news.example/{i}",
                "fact": "Fact",
                "why_it_matters": "Why",
                "uncertainty": "Unknown",
                "confidence": "high",
                "high_stakes": False,
                "additional_sources": [],
            }
            for i in range(3)
        ],
        "radar": [],
        "source_health_summary": "healthy",
    }
    report_path = tmp_path / "report.json"
    manifest_path = tmp_path / "manifest.json"
    receipt_path = tmp_path / "receipt.json"
    state_path = tmp_path / "state.db"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    state = State(state_path)
    state.begin_run("r1")
    if reservation_page is not None:
        state.reserve_publication(report["date"], report["run_id"])
        state.complete_publication(report["date"], report["run_id"], reservation_page)
    args = [
        "finalize",
        "--report",
        str(report_path),
        "--manifest",
        str(manifest_path),
        "--state-db",
        str(state_path),
        "--receipt",
        str(receipt_path),
    ]
    return args, receipt_path


def receipt(page_id="page-1"):
    return {
        "run_id": "r1",
        "page_id": page_id,
        "url": "https://www.notion.so/page-1",
        "verified_at": "2026-07-15T01:00:00Z",
    }


def test_finalize_rejects_fabricated_receipt_without_reservation(tmp_path, capsys):
    args, receipt_path = finalize_files(tmp_path, reservation_page=None)
    receipt_path.write_text(json.dumps(receipt()), encoding="utf-8")
    assert cli.main(args) == 2
    assert "reservation not found" in capsys.readouterr().err


def test_finalize_rejects_receipt_page_mismatch(tmp_path, capsys):
    args, receipt_path = finalize_files(tmp_path)
    receipt_path.write_text(json.dumps(receipt("fabricated-page")), encoding="utf-8")
    assert cli.main(args) == 2
    assert "page_id does not match" in capsys.readouterr().err


@pytest.mark.parametrize(
    "bad_receipt",
    [
        {"run_id": "r1", "page_id": "page-1", "url": "https://www.notion.so/page-1"},
        {**receipt(), "verified_at": "2026-07-15T01:00:00"},
        {**receipt(), "url": "http://www.notion.so/page-1"},
        {**receipt(), "extra": "field"},
    ],
)
def test_finalize_rejects_incomplete_or_invalid_receipt(tmp_path, bad_receipt, capsys):
    args, receipt_path = finalize_files(tmp_path)
    receipt_path.write_text(json.dumps(bad_receipt), encoding="utf-8")
    assert cli.main(args) == 2
    assert "receipt" in capsys.readouterr().err
