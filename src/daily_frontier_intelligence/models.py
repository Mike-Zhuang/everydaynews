from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Article:
    source_id: str
    source_name: str
    source_tier: int
    categories: list[str]
    title: str
    url: str
    canonical_url: str
    published_at: str | None
    fetched_at: str
    date_confidence: str
    summary: str
    language: str
    region: str
    content_hash: str
    interest_score: float
    corroborating_sources: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
