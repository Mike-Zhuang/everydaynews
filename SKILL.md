---
name: daily-frontier-intelligence
description: Produce a lightweight, source-grounded Chinese daily global technology brief focused on AI/LLM/agents, robotics and embodied AI, ML research, AI systems, software engineering, open source, cloud, chips, and consequential technology policy; archive the full brief to Notion and return a concise WeChat update.
version: 1.0.0
license: MIT
author: Hermes Agent
metadata:
  hermes:
    tags: [daily-news, ai, agents, robotics, software-engineering, notion, wechat]
---

# Daily Frontier Intelligence

Create one compact global technology brief per local calendar day. The workflow is breadth-first and
news-oriented. It complements the separate paper deep-dive Skill; it does not inherit that workflow's
long-form exposition, independent code audit, formulas, or nine-card publication package.

Geography is metadata only. Apply no regional, national, language, or political exclusion. The
default catalog is nevertheless mostly English/global-tech; bounded web gap checks can broaden
coverage. Rank an
item by evidence and relevance, never by whether its origin is considered politically convenient.

## Inputs and private state

- Source catalog: `references/sources.yaml`
- Source policy and audit: `references/source-audit.md`
- Optional no-feed watchlist: `references/web-watchlist.md`
- Private runtime config: outside Git, containing `notion_database_id`,
  `notion_data_source_id`, `timezone`, and `state_db`
- Runtime token: `NOTION_API_KEY` or a process-local `NOTION_TOKEN`; never copy it into a report,
  repository, command history, prompt artifact, or log

Resolve the Skill directory from the loaded Skill metadata. Use absolute paths in scheduled jobs.

## Interest profile

Prioritize:

1. AI agents, tool use, MCP, multi-agent systems, reasoning, evaluation, and safety;
2. robotics, embodied AI, VLA, manipulation, navigation, humanoids, simulation, and world models;
3. AI systems, inference, serving, compilers, developer tooling, cloud, and deployable products;
4. useful open-source releases and engineering practices;
5. important ML research that has immediate conceptual or engineering significance;
6. chips, accelerators, robotics hardware, and systems infrastructure;
7. technology policy, security, finance, or geopolitics only when it materially changes the above.

Do not fill the brief with generic corporate marketing, undifferentiated funding news, routine model
benchmarks, minor version bumps, speculative rumors, or general politics without technical impact.

## Mandatory workflow

### 1. Collect deterministically

Run the packaged collector with a 36-hour window so time-zone boundaries do not hide late stories:

```bash
uv run daily-frontier-intelligence collect \
  --config references/sources.yaml \
  --state-db "$PRIVATE_STATE_DB" \
  --output "$RUN_DIR/manifest.json" \
  --since-hours 36 --max-items 160 --concurrency 8
```

The collector may contact only configured HTTPS feeds. Missing or invalid publication dates never
become today's date. It records source health and excludes items considered by completed runs.

### 2. Apply the coverage gate

Inspect `candidate_count`, `health_summary`, and per-source health.

- Isolated source failures are normal and do not abort the run.
- Distinguish `success-empty` from timeout, HTTP failure, and parse failure.
- If fewer than 12 sources are reachable/parseable, or fewer than 8 candidates survive, describe the
  partial coverage and use the bounded gap check below.
- If fewer than 3 credible finalists remain after verification, do not pad the report. Return a brief
  low-signal/coverage notice and leave the run unfinalized for operator review.

### 3. Perform bounded gap checks

Use `references/web-watchlist.md` only to cover obvious missing organizations or a suspected major
event. Limit this stage to a few targeted official-domain searches. Open the original page and require
a visible or structured publication date. A failed gap check never aborts deterministic collection.

Do not add a guessed feed URL or turn the watchlist into unbounded scraping.

### 4. Shortlist and score editorially

Use this 100-point editorial score:

- user relevance: 35;
- technical or industry significance: 25;
- evidence quality: 20;
- information gain versus recent briefs: 10;
- actionability or learning value: 10.

Geography contributes zero points. Deterministic `interest_score` is a pre-ranking signal, not the
final decision. Prefer 3–6 top items; the report validator permits up to 8. Limit concentration:

- at most two top items from one organization;
- at most one paper as a top item; additional papers belong in Radar;
- routine releases belong in Radar unless they materially change engineering choices;
- tier-3 sources are discovery channels and cannot independently support consequential claims.

### 5. Read and verify every finalist

Open the original URL for every top item. Do not summarize a search snippet or feed title as though it
were the article.

For each finalist record:

- **事实:** what the source verifiably announced, measured, released, or reported;
- **为何重要:** the editor's concise technical or practical interpretation;
- **不确定性:** missing evidence, first-party limitations, disputed points, or what remains unknown;
- **置信度:** `high`, `medium`, or `low`.

Mark an item `high_stakes=true` when it makes consequential policy, safety, security, financial,
market, or geopolitical claims. Such an item requires corroboration whose host and `publisher_id`
both differ from the primary manifest item's host and `source_id`. A second hostname operated by the
same publisher is context, not independent corroboration.

Official vendor sources are authoritative for what the vendor released. They are not independent
proof of performance, safety, adoption, or comparative superiority.

### 6. Write the full Chinese report

Start with literal `TL;DR：`. Use direct Chinese sentences and avoid habitual filler contrasts. Each
top item should usually fit in three short paragraphs: fact, why it matters, uncertainty. Explain only
the minimum context needed to make the news useful.

Prepare JSON conforming to `references/report.template.json`. Preserve each primary `content_hash`
and original URL from the manifest. For every additional source, record exactly `name`, `url`,
`role`, stable `publisher_id` (1–100 characters), and a timezone-aware ISO-8601 `retrieved_at` near
the collection run (not over one hour before manifest generation or over five minutes in the future).

### 7. Validate before any write

```bash
uv run daily-frontier-intelligence validate-report \
  --report "$RUN_DIR/report.json" --manifest "$RUN_DIR/manifest.json"
```

Fix every error. Validation success is necessary but does not prove factual accuracy; source reading
and editorial judgment remain mandatory.

### 8. Publish idempotently to Notion

The publisher first queries exact Run ID, then checks for a conflicting page on the same date. It
writes only the configured Daily Briefs database and has no generic arbitrary-page interface.

```bash
uv run daily-frontier-intelligence publish-notion \
  --report "$RUN_DIR/report.json" --manifest "$RUN_DIR/manifest.json" \
  --runtime-config "$PRIVATE_CONFIG"
```

Run executable readback and retain its receipt:

```bash
uv run daily-frontier-intelligence verify-notion-page \
  --report "$RUN_DIR/report.json" --page-id "$NOTION_PAGE_ID" \
  --runtime-config "$PRIVATE_CONFIG" --receipt "$RUN_DIR/notion-receipt.json"
```

This verifies the Run ID, date, status, item/source counts, literal TL;DR, every top-item heading,
and every source link across paginated blocks. It writes a receipt containing exactly `run_id`,
`page_id`, public HTTPS `url`, and timezone-aware `verified_at`. Do not finalize if it fails.

### 9. Finalize local state

After successful Notion readback:

```bash
uv run daily-frontier-intelligence finalize \
  --report "$RUN_DIR/report.json" --manifest "$RUN_DIR/manifest.json" \
  --state-db "$PRIVATE_STATE_DB" --receipt "$RUN_DIR/notion-receipt.json"
```

Finalization marks all candidates considered and selected items delivered. It requires receipt IDs
to match the report and the completed publication reservation for that date and run. It is
idempotent for the same Run ID and page ID. Never finalize a failed or ambiguous publication.

### 10. Return the concise WeChat brief

Use `references/wechat.template.txt`. Include:

- one-line TL;DR;
- the 3–5 most important items, each in one or two compact sentences;
- at most one Radar line;
- the verified Notion page URL;
- a short partial-coverage note only when material.

The cron final response is the WeChat delivery. Do not call an extra messaging API, post publicly, or
produce a carousel. Keep the full detail in Notion.

## Relationship to the paper deep-dive

The daily brief may nominate one paper or technical direction in Radar. It must not automatically run
the paper deep-dive, claim peer review from arXiv presence, perform a repository audit, generate nine
images, or duplicate a paper already selected by the separate scheduled workflow.

## Failure policy

- One feed fails: continue and record it.
- Coverage is degraded: run bounded gap checks and disclose the limitation.
- Fewer than three credible stories: do not manufacture a full brief.
- Original page is inaccessible: keep the item in Radar or drop it; do not promote a snippet.
- Notion write fails: retain local artifacts and do not finalize.
- Notion succeeds but finalization fails: retry finalization with the same report and page ID.
- Same date has a different Run ID: stop for reconciliation; do not overwrite or silently duplicate.

## Common Pitfalls

- Do not treat `updated` as publication time unless that source explicitly opts in.
- Do not bypass URL validation, enable redirects, or copy credentials into artifacts.
- Do not finalize from a manually copied page ID; use the verified receipt.
- An ambiguous Notion write remains locally reserved so the same run can reconcile and retry.

## Verification Checklist

- Report date matches manifest generation time in the configured IANA timezone.
- Every finalist was opened, and high-stakes claims have independent-host corroboration.
- Report validation, Notion publication, executable readback, and receipt-gated finalization succeeded.
- Partial coverage and the catalog's mostly English/global-tech limitation are disclosed when material.

## References

- `references/schema.md` — data and state contracts
- `references/source-audit.md` — source tiers and admission evidence
- `references/web-watchlist.md` — bounded no-feed gap checks
- `references/report.template.json` — report contract
- `references/wechat.template.txt` — concise delivery format
