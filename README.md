# daily-frontier-intelligence

A Skill-first replacement for the original `everydaynews` Next.js prototype. It produces a
lightweight, source-grounded Chinese daily global technology brief, archives the full version to
Notion, and leaves concise WeChat delivery to the Hermes cron response.

The default catalog was built from a live audit of 70 candidate RSS, Atom, and API endpoints on
2026-07-15. Forty-nine production-parseable endpoints are enabled: 28 first-party/official sources, 13
specialist sources, and 8 discovery sources. Geography is unfiltered and never affects ranking, but
the current default catalog is mostly English/global-tech; bounded web gap checks can broaden it.

## What changed from the old prototype

Removed:

- Next.js UI and unauthenticated public API routes;
- Vercel deployment and browser-local history;
- homepage-link guessing and the missing-date-to-today fallback;
- the default third-party OpenAI-compatible relay;
- China-only and political/editorial geography restrictions.

Added:

- bounded concurrent RSS/Atom/arXiv collection;
- explicit publication dates and source-health states;
- canonical URL identity, deterministic title clustering, and corroborating-source metadata;
- SQLite run, article, delivery, and retry state;
- strict agent-report validation;
- narrow idempotent Notion publication and transactional finalization;
- source audit, web-gap watchlist, CI, tests, and a complete Hermes `SKILL.md`.

## Architecture

```text
49 enabled feeds
      ↓
bounded deterministic collector
      ↓
manifest.json + SQLite state + source health
      ↓
Hermes opens and verifies finalists
      ↓
validated report.json
      ↓
idempotent Notion Daily Briefs page
      ↓
state finalization
      ↓
concise cron response delivered to WeChat
```

The Python runtime collects and validates evidence contracts. The Hermes Skill performs editorial
judgment and original-source reading. The repository does not contain a model API key or a generic
public writing endpoint.

## Install for development

Requires Python 3.11 and [uv](https://docs.astral.sh/uv/):

```sh
uv sync --all-extras
uv run pytest -q
uv run ruff check .
uv run mypy src/daily_frontier_intelligence
uv build
```

## Install as a Hermes Skill

Copy or clone the repository to a profile-local skill directory such as:

```text
~/.hermes/skills/research/daily-frontier-intelligence/
```

Create a private runtime config outside Git from `config.example.json`. The Notion integration must
have access only to the intended Daily Briefs database. Keep the token in the process environment as
`NOTION_API_KEY` or `NOTION_TOKEN`.

## Manual collection

```sh
uv run daily-frontier-intelligence collect \
  --config references/sources.yaml \
  --state-db /private/runtime/state.sqlite3 \
  --output /private/runtime/manifest.json \
  --since-hours 36 --max-items 160 --concurrency 8
```

Collection performs no model call and no Notion write. It tolerates isolated source failures and
records `success`, `success-empty`, `parse-error`, `http-error`, or `timeout` per source. Missing dates
are excluded instead of being relabeled as today.

After an agent reads finalists and writes `report.json`:

```sh
uv run daily-frontier-intelligence validate-report \
  --report /private/runtime/report.json \
  --manifest /private/runtime/manifest.json

uv run daily-frontier-intelligence publish-notion \
  --report /private/runtime/report.json \
  --manifest /private/runtime/manifest.json \
  --runtime-config /private/runtime/config.json

uv run daily-frontier-intelligence verify-notion-page \
  --report /private/runtime/report.json \
  --page-id VERIFIED_NOTION_PAGE_ID \
  --runtime-config /private/runtime/config.json \
  --receipt /private/runtime/notion-receipt.json

uv run daily-frontier-intelligence finalize \
  --report /private/runtime/report.json \
  --manifest /private/runtime/manifest.json \
  --state-db /private/runtime/state.sqlite3 \
  --receipt /private/runtime/notion-receipt.json
```

Read `SKILL.md` before operating the pipeline. Publication must be read back successfully before
finalization. Each additional report source has exactly `name`, `url`, `role`, `publisher_id`, and a
timezone-aware ISO-8601 `retrieved_at`; high-stakes corroboration must differ from the primary source
in both hostname and publisher ID.

## Source model

- Tier 1: first-party, official standards/academic sources, and project release feeds.
- Tier 2: specialist technical, research, robotics, software, or hardware reporting.
- Tier 3: discovery/commentary sources; never sufficient alone for high-stakes claims.

See `references/source-audit.md` for admission policy and `references/web-watchlist.md` for important
organizations without verified feeds. Web gap checks are bounded and optional.

## Privacy and security

- No credential, Notion ID, user ID, or machine-specific path belongs in Git.
- The collector validates public HTTPS/DNS targets, keeps redirects disabled, caps each body at 5 MB,
  and bounds sources, entries, accepted items, and elapsed streaming time.
- Network concurrency is bounded to 1–16 workers.
- No missing date is replaced with the current date.
- Notion publication queries exact Run ID first and treats a same-date/different-run page as a conflict.
- Failed or ambiguous publication leaves local state retryable.
- Verification receipts contain exactly non-empty `run_id`, `page_id`, public HTTPS `url`, and
  timezone-aware ISO-8601 `verified_at`. Finalization also requires a matching completed publication
  reservation for the report date and run.
- WeChat delivery is the scheduler's final response; the repository sends no external message itself.

## Tests and CI

The suite covers date handling, URL canonicalization, stable article identity, title clustering,
region-neutral scoring, source failure isolation, bounded streaming, concurrency order, SQLite retry
and finalization, report validation, independent corroboration, Notion idempotency/payloads, and
secret scanning.

```sh
uv run --all-extras pytest -q
uv run --all-extras ruff check .
uv run --all-extras mypy src/daily_frontier_intelligence
uv build
```

## Limitations

Feeds can move or change structure. A feed item is discovery evidence, so the agent must open every
finalist's original URL. Vendor posts establish what a vendor announced, not independent proof of its
claims. The pipeline deliberately avoids full-page scraping, public posting, and automatic paper
reviews. Re-probe the catalog periodically and keep failed-source history visible.
