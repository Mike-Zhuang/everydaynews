from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .collector import collect
from .config import load_runtime_config, load_sources
from .notion import publish, verify_page
from .report import _aware_timestamp, load_json, validate_report
from .security import validate_public_url
from .state import State


def _write(path: str, value: object) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, destination)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="daily-frontier-intelligence")
    sub = parser.add_subparsers(dest="command", required=True)
    collect_p = sub.add_parser("collect")
    collect_p.add_argument("--config", required=True)
    collect_p.add_argument("--state-db", required=True)
    collect_p.add_argument("--output", required=True)
    collect_p.add_argument("--since-hours", type=int, default=30)
    collect_p.add_argument("--max-items", type=int, default=100)
    collect_p.add_argument("--concurrency", type=int, default=8)
    collect_p.add_argument("--include-seen", action="store_true")
    validate_p = sub.add_parser("validate-report")
    validate_p.add_argument("--report", required=True)
    validate_p.add_argument("--manifest", required=True)
    publish_p = sub.add_parser("publish-notion")
    publish_p.add_argument("--report", required=True)
    publish_p.add_argument("--manifest", required=True)
    publish_p.add_argument("--runtime-config", required=True)
    verify_p = sub.add_parser("verify-notion-page")
    verify_p.add_argument("--report", required=True)
    verify_p.add_argument("--page-id", required=True)
    verify_p.add_argument("--runtime-config", required=True)
    verify_p.add_argument("--receipt", required=True)
    finalize_p = sub.add_parser("finalize")
    finalize_p.add_argument("--report", required=True)
    finalize_p.add_argument("--manifest", required=True)
    finalize_p.add_argument("--state-db", required=True)
    finalize_p.add_argument("--receipt", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "collect":
            config = load_sources(args.config)
            state = State(args.state_db)
            run_id = state.begin_run()
            items, health = collect(
                config, args.since_hours, args.max_items, concurrency=args.concurrency
            )
            if not args.include_seen:
                items = state.filter_unseen(items)
            state.register(run_id, items, health)
            generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            _write(
                args.output,
                {
                    "run_id": run_id,
                    "generated_at": generated_at,
                    "window_hours": args.since_hours,
                    "candidate_count": len(items),
                    "health_summary": dict(Counter(str(x["status"]) for x in health)),
                    "items": [x.to_dict() for x in items],
                    "source_health": health,
                },
            )
            return 0
        report = load_json(args.report)
        if args.command == "verify-notion-page":
            config = load_runtime_config(args.runtime_config)
            token = os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_API_KEY", "")
            _write(args.receipt, verify_page(report, args.page_id, config, token))
            return 0
        manifest = load_json(args.manifest)
        validate_report(report, manifest)
        if args.command == "validate-report":
            print("report valid")
            return 0
        if args.command == "publish-notion":
            config = load_runtime_config(args.runtime_config)
            token = os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_API_KEY", "")
            state = State(config["state_db"])
            existing = state.reserve_publication(report["date"], report["run_id"])
            if existing:
                print(existing)
                return 0
            page_id = publish(report, manifest, config, token)
            state.complete_publication(report["date"], report["run_id"], page_id)
            print(page_id)
            return 0
        selected = [item["content_hash"] for item in report["top_items"]]
        receipt = load_json(args.receipt)
        if set(receipt) != {"run_id", "page_id", "url", "verified_at"}:
            raise ValueError("receipt must contain exactly run_id, page_id, url, and verified_at")
        for field in receipt:
            if not isinstance(receipt[field], str) or not receipt[field].strip():
                raise ValueError(f"receipt {field} must be a non-empty string")
        _aware_timestamp(receipt["verified_at"], "receipt verified_at")
        validate_public_url(receipt["url"], field="receipt url")
        if receipt["run_id"] != report["run_id"]:
            raise ValueError("receipt run_id does not match report")
        state = State(args.state_db)
        publication = state.get_publication(report["date"], report["run_id"])
        if publication is None:
            raise ValueError("publication reservation not found")
        if receipt["page_id"] != publication["page_id"]:
            raise ValueError("receipt page_id does not match publication reservation")
        state.finalize(report["run_id"], selected, receipt["page_id"])
        return 0
    except (ValueError, TypeError, KeyError, OSError, httpx.HTTPError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
