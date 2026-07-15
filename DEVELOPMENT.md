# Development

Strict behavior-first TDD was used. The oversized-stream test must never run against an
implementation that calls `response.content`: replace `_fetch` with bounded streaming first, so it
stops immediately after the first chunk crossing 5 MB. Representative RED/GREEN pairs:

```text
RED   python -m pytest tests/test_normalize.py -q       # ModuleNotFoundError
GREEN python -m pytest tests/test_normalize.py -q       # passed
RED   python -m pytest tests/test_collector.py -q       # missing collector behavior
GREEN python -m pytest tests/test_collector.py -q       # passed
RED   python -m pytest tests/test_state.py -q           # missing transactional schema
GREEN python -m pytest tests/test_state.py -q           # passed
RED   python -m pytest tests/test_report_notion.py -q   # missing validation/publisher
GREEN python -m pytest tests/test_report_notion.py -q   # passed
RED   python -m pytest tests/test_security.py -q         # obsolete relay secret example found
GREEN python -m pytest tests/test_security.py -q         # passed
```

Run changed modules individually before the full suite. Final verification commands are:

```sh
uv run pytest
uv run ruff check .
uv run mypy src/daily_frontier_intelligence
uv build
git diff --check
```

Tests use `httpx.MockTransport`; no development verification should call real feeds or Notion.
DNS-dependent tests inject or monkeypatch a resolver and never use real DNS.
