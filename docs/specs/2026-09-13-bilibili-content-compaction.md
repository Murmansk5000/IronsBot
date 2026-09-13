# Bilibili Long Content Compaction

Status: `verified`

Contract: `target`

Owner: `services.bilibili.content`

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md#change-design-gate)

## Problem

Bilibili push and history detail previously had separate long-body behavior. The push
path owned summarizer invocation and truncation while history could repeatedly expose
the full body. The old call also passed `max_chars` positionally even though the AI
service requires a keyword-only argument.

## Contract

`DynamicContentCompactor` is the single platform-neutral owner of long-body policy:

- short bodies are returned unchanged by yielding no override;
- an enabled AI summarizer receives `max_chars` as a keyword argument;
- unusable summaries receive a bounded number of attempts;
- deterministic truncation is the final fallback;
- the result records whether AI produced it.

Push and history detail share the same instance. Generated overrides are persisted in
the existing Bilibili history database and survive later snapshot refreshes. History
detail lazily creates a missing summary; startup does not perform bulk AI work.

## Boundaries

- The OneBot plugin only adapts the selection event and sends the prepared result.
- `BilibiliService` coordinates hydration, compaction and persistence.
- The SQLite adapter owns schema migration and summary storage.
- Delivery retries remain solely in `ProactiveMessageDelivery`; content compaction
  does not add a second delivery loop.
- No TOML field, image asset or runtime dependency is added.

## Verification

- Existing version-2 history databases upgrade in place and retain their records.
- Snapshot refresh does not erase a stored summary.
- Push and repeated history detail reuse one persisted summary.
- Short text skips AI; invalid AI output falls back after bounded attempts.
- Focused Bilibili and runtime tests, Ruff, BasedPyright, compileall and diff checks
  are required before the slice is committed.

Verified on 2026-09-13: 118 focused tests and the full suite
(`3207 passed, 7 skipped`) passed; Ruff, BasedPyright, compileall and
`git diff --check` also passed.
