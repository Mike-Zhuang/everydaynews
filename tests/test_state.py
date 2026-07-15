import sqlite3

import pytest

from daily_frontier_intelligence.state import State


def test_retry_idempotency_and_finalization(tmp_path, article):
    state = State(tmp_path / "state.db")
    run = state.begin_run("run-1")
    state.register(
        run, [article], [{"source_id": "s", "status": "success", "item_count": 1, "detail": ""}]
    )
    state.register(
        run, [article], [{"source_id": "s", "status": "success", "item_count": 1, "detail": ""}]
    )
    with sqlite3.connect(state.path) as db:
        assert db.execute("select delivered_at from articles").fetchone()[0] is None
    state.finalize(run, [article.content_hash], "page-1")
    state.finalize(run, [article.content_hash], "page-1")
    with sqlite3.connect(state.path) as db:
        assert all(db.execute("select considered_at,delivered_at from articles").fetchone())
    with pytest.raises(ValueError):
        state.finalize(run, [], "page-2")


def test_seen_filter_excludes_finalized_but_keeps_unfinalized_items(tmp_path, article):
    state = State(tmp_path / "state.db")
    run1 = state.begin_run("run-1")
    state.register(run1, [article], [])
    assert state.filter_unseen([article]) == [article]
    state.finalize(run1, [], "page-1")
    assert state.filter_unseen([article]) == []

    other = article.__class__(
        **{**article.to_dict(), "canonical_url": "https://x.test/b", "content_hash": "hash2"}
    )
    run2 = state.begin_run("run-2")
    state.register(run2, [other], [])
    assert state.filter_unseen([other]) == [other]
