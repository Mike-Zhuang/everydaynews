# Data contracts

## Source catalog

`references/sources.yaml` is JSON-compatible YAML. Each source has:

- `id`, `name`, `url`, `kind` (`rss`, `atom`, or `arxiv_query`);
- `categories`, evidence `tier` (1–3), `language`, and display-only `region`;
- `enabled` and maintenance `notes`;
- optional boolean `allow_updated_as_published` for feeds (notably release feeds) whose update field
  is explicitly their publication signal.

`region` is never an input to deterministic or editorial ranking.

## Collector manifest

A manifest contains:

- `run_id`, `generated_at`, `window_hours`, and `candidate_count`;
- aggregate `health_summary` and detailed `source_health`;
- normalized `items`.

Each normalized item contains:

- source identity: `source_id`, `source_name`, `source_tier`;
- classification: `categories`, `language`, `region`;
- provenance: `title`, `url`, `canonical_url`, `published_at`, `fetched_at`,
  `date_confidence`, and feed `summary`;
- stable canonical-URL `content_hash` and deterministic `interest_score`;
- `corroborating_sources`, populated when equivalent normalized titles occur at distinct URLs.

Missing or invalid dates remain null and are excluded from the default daily window. Source health
statuses are `success`, `success-empty`, `parse-error`, `http-error`, and `timeout`.

## SQLite state

- `articles` stores stable canonical identities and considered/delivered timestamps.
- `runs` stores collection/finalization status and the published Notion page ID.
- `run_items` links manifest candidates to a run and marks selected items.
- `source_health` stores the health result for each source/run pair.
- `publications` reserves one local date per run before remote creation and stores the resulting page.

Collection registers candidates without marking them delivered. Successful finalization marks all run
candidates considered and selected items delivered in one transaction. Failed publication is
retryable. Finalizing the same Run ID and page ID is idempotent; a different page ID is an error.

## Agent report

Follow `report.template.json`. A report has:

- `run_id`, local `date`, IANA `timezone`, `title`, and literal-prefix `tldr`;
- 3–8 `top_items`;
- zero or more short `radar` entries;
- a concise `source_health_summary`.

Each top item preserves a manifest `content_hash` and primary `url`, and provides `fact`,
`why_it_matters`, `uncertainty`, `confidence`, `high_stakes`, and `additional_sources`.

Additional sources contain exactly `name`, absolute `url`, `role` (`corroboration`, `context`, or
`primary`), `publisher_id`, and `retrieved_at`. Use a stable, non-empty publisher identifier of at
most 100 characters. Record `retrieved_at` as a timezone-aware ISO-8601 timestamp no earlier than
one hour before `manifest.generated_at` and no more than five minutes in the future. A high-stakes
item requires a `corroboration` source whose host and publisher ID both differ from the primary
manifest item's host and `source_id`.

## Notion contract

The configured database must expose these exact properties:

- `Name` (title)
- `Date` (date)
- `Status` (select containing `Published`)
- `Run ID` (rich text)
- `Item Count` (number)
- `Source Count` (number)
- `Confidence` (percent number)
- `Topics` (multi-select)
- `Timezone` (rich text)

The CLI reserves the local date with `BEGIN IMMEDIATE`; same-run retries reconcile while a different
run is rejected. The publisher queries exact Run ID first. An existing date with a different Run ID is a reconciliation
error. It writes TL;DR, structured top items, all source links, Radar, and source health. The caller
must run paginated readback and produce a matching receipt before finalizing state. The receipt has
exactly non-empty `run_id`, `page_id`, public HTTPS `url`, and timezone-aware ISO-8601 `verified_at`.
Finalization requires its IDs to match the report and the completed publication reservation for that
date and run. Create payloads are rejected when their actual top-level child count exceeds 100.
