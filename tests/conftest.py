from __future__ import annotations

from datetime import UTC, datetime

import pytest

from daily_frontier_intelligence.models import Article


@pytest.fixture
def article():
    return Article(
        "s",
        "Source",
        1,
        ["ai"],
        "An Agent Launch",
        "https://x.test/a?utm_source=z",
        "https://x.test/a",
        "2026-07-14T00:00:00Z",
        datetime.now(UTC).isoformat(),
        "source",
        "summary",
        "en",
        "global",
        "hash1",
        5.0,
        [],
    )
