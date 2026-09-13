# Portable Rank Cache Status

## Status

Implemented on `codex/multiplatform-architecture-v5`.

## Goal

Expose read-only rank cache diagnostics to authorized users through the shared
command router, without porting refresh jobs or OneBot handlers.

## Scope

- `rank.sample_status` renders local sample-cache statistics.
- `rank.page_status` renders either the global page-cache overview or one
  parsed rank's page-cache status.
- The command catalog remains authoritative for `seer_rank` and superuser
  access checks on each bot account.

Refresh, batch caching and group display-limit mutation remain outside this
slice. They require progress delivery or mutable group settings and must not be
presented as read-only diagnostics.

## Acceptance

- `/样本情况` receives the current conversation when calculating display
  settings.
- `/榜单情况` renders the overview.
- `/榜单情况 <榜名>` uses the existing global-rank parser.
- Ordinary users cannot discover or execute either command.
- Existing OneBot behavior remains unchanged.
