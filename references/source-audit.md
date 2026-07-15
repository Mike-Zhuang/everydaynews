# Source audit

Audit date: 2026-07-15

The maintainer probed 70 candidate RSS, Atom, and API endpoints with bounded HTTP requests. An endpoint counted as initially usable only when it returned HTTP 200 and contained real RSS/Atom `item` or `entry` records. A full collector pilot then disabled Open Robotics Blog because `feedparser` encountered an undefined XML entity. The default catalog enables 49 endpoints:

- 28 tier-1 official, first-party, standards, academic-lab, or project-release feeds;
- 13 tier-2 specialist research, engineering, robotics, software, or hardware publications;
- 8 tier-3 discovery and commentary feeds.

The probe recorded status, content type, final URL, item count, and latest available publication timestamp. Redirect targets were written back into the catalog where needed. A successful feed response is evidence of transport and parse availability on the audit date, not a permanent uptime guarantee or an endorsement of every claim it publishes.

## Admission policy

A source may be enabled when it has a stable machine-readable endpoint, attributable publication timestamps, and material relevance to at least one configured topic. Tier determines how its claims may be used:

- **Tier 1:** cite as the authoritative source for what that organization released, announced, documented, or published. Vendor performance and safety claims remain first-party claims.
- **Tier 2:** suitable professional reporting or specialist context. Consequential claims may require a first-party or independent second source.
- **Tier 3:** discovery only. Open the linked original source and do not let the tier-3 item alone support high-stakes conclusions.

Geography is metadata only and contributes zero positive or negative score.

## Known failed or unsuitable feed candidates

The following tested endpoints were not enabled because they returned 404/500, HTML rather than a feed, no items, or an obsolete feed:

- Anthropic News guessed RSS endpoints;
- Meta AI Blog guessed RSS endpoints;
- Boston Dynamics Blog feed;
- Stanford HAI News guessed RSS endpoint;
- MIT CSAIL guessed RSS endpoint;
- LangChain Blog guessed RSS endpoint;
- Weights & Biases Fully Connected guessed RSS endpoint;
- Google Cloud AI guessed RSS endpoint;
- Machine Intelligence/机器之心 guessed RSS endpoint;
- 智东西 feed (server error during audit);
- White House OSTP guessed feed;
- OECD.AI guessed feed;
- PyTorch guessed feed;
- Docker Blog guessed feed.
- Open Robotics Blog (HTTP 200, but malformed XML under the production parser).

These organizations may still be checked through the bounded web-gap workflow in `web-watchlist.md`. Do not invent or silently substitute an RSS URL.

## Maintenance

Re-probe all enabled feeds at least monthly. Disable a source after repeated structural failure, not after one transient timeout. Treat `success-empty` separately from HTTP or parse failure. Record endpoint migrations in Git history.
