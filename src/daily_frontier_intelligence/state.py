from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .models import Article

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS articles (
 content_hash TEXT PRIMARY KEY, canonical_url TEXT NOT NULL UNIQUE, data_json TEXT NOT NULL,
 considered_at TEXT, delivered_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
 run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, status TEXT NOT NULL,
 published_page_id TEXT
);
CREATE TABLE IF NOT EXISTS run_items (
 run_id TEXT NOT NULL REFERENCES runs(run_id),
 content_hash TEXT NOT NULL REFERENCES articles(content_hash),
 selected INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(run_id, content_hash)
);
CREATE TABLE IF NOT EXISTS source_health (
 run_id TEXT NOT NULL REFERENCES runs(run_id), source_id TEXT NOT NULL, status TEXT NOT NULL,
 item_count INTEGER NOT NULL, detail TEXT NOT NULL, PRIMARY KEY(run_id, source_id)
);
CREATE TABLE IF NOT EXISTS publications (
 local_date TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
 page_id TEXT, reserved_at TEXT NOT NULL, completed_at TEXT
);
"""


class State:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def begin_run(self, run_id: str | None = None) -> str:
        run_id = run_id or str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO runs VALUES (?, ?, 'collected', NULL)", (run_id, now))
        return run_id

    def register(self, run_id: str, items: list[Article], health: list[dict[str, object]]) -> None:
        with self.connect() as db:
            for item in items:
                db.execute(
                    "INSERT OR IGNORE INTO articles"
                    "(content_hash,canonical_url,data_json) VALUES(?,?,?)",
                    (item.content_hash, item.canonical_url, json.dumps(item.to_dict())),
                )
                row = db.execute(
                    "SELECT content_hash FROM articles WHERE canonical_url=?", (item.canonical_url,)
                ).fetchone()
                db.execute(
                    "INSERT OR IGNORE INTO run_items(run_id,content_hash) VALUES(?,?)",
                    (run_id, row[0]),
                )
            for entry in health:
                db.execute(
                    "INSERT OR REPLACE INTO source_health VALUES(?,?,?,?,?)",
                    (
                        run_id,
                        entry["source_id"],
                        entry["status"],
                        entry["item_count"],
                        entry["detail"],
                    ),
                )

    def filter_unseen(self, items: list[Article]) -> list[Article]:
        """Exclude articles considered by a successfully finalized run."""
        if not items:
            return []
        with self.connect() as db:
            seen = {
                row[0]
                for row in db.execute(
                    "SELECT content_hash FROM articles WHERE considered_at IS NOT NULL"
                )
            }
        return [item for item in items if item.content_hash not in seen]

    def finalize(self, run_id: str, selected_hashes: list[str], page_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self.connect() as db:
            run = db.execute(
                "SELECT status,published_page_id FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if not run:
                raise ValueError("unknown run_id")
            if run["status"] == "published":
                if run["published_page_id"] != page_id:
                    raise ValueError("run already finalized with another page")
                return
            registered = {
                r[0]
                for r in db.execute("SELECT content_hash FROM run_items WHERE run_id=?", (run_id,))
            }
            if not set(selected_hashes) <= registered:
                raise ValueError("selected item is not registered to run")
            db.execute(
                "UPDATE articles SET considered_at=COALESCE(considered_at,?) WHERE content_hash IN "
                "(SELECT content_hash FROM run_items WHERE run_id=?)",
                (now, run_id),
            )
            for digest in selected_hashes:
                db.execute(
                    "UPDATE articles SET delivered_at=COALESCE(delivered_at,?) "
                    "WHERE content_hash=?",
                    (now, digest),
                )
                db.execute(
                    "UPDATE run_items SET selected=1 WHERE run_id=? AND content_hash=?",
                    (run_id, digest),
                )
            db.execute(
                "UPDATE runs SET status='published',published_page_id=? WHERE run_id=?",
                (page_id, run_id),
            )

    def reserve_publication(self, local_date: str, run_id: str) -> str | None:
        now = datetime.now(UTC).isoformat()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT run_id,page_id FROM publications WHERE local_date=?", (local_date,)
            ).fetchone()
            if row:
                if row["run_id"] != run_id:
                    raise ValueError("publication date is already reserved by another run")
                return row["page_id"]
            if not db.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
                raise ValueError("unknown run_id")
            db.execute(
                "INSERT INTO publications VALUES(?,?,NULL,?,NULL)", (local_date, run_id, now)
            )
        return None

    def complete_publication(self, local_date: str, run_id: str, page_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self.connect() as db:
            result = db.execute(
                "UPDATE publications SET page_id=?,completed_at=? WHERE local_date=? AND run_id=?",
                (page_id, now, local_date, run_id),
            )
            if result.rowcount != 1:
                raise ValueError("publication reservation not found")

    def get_publication(self, local_date: str, run_id: str) -> dict[str, str | None] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT local_date,run_id,page_id,reserved_at,completed_at FROM publications "
                "WHERE local_date=? AND run_id=?",
                (local_date, run_id),
            ).fetchone()
        return dict(row) if row else None
