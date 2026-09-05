# AI Platform Session Isolation

Status: `verified`

Contract: `target`

Owner: AiService session identity; existing AiMemoryStore and OutboundMessenger.

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md)
Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

## Problem

AiService accepts typed ActorRef/ConversationRef but concatenates their fields
with colons to form its short-history key. These fields are opaque strings and
may contain colons. Two different, correctly scoped identities can therefore
share a short-history entry even though SQLite actor columns remain distinct.

## Goal And Design

Keep the existing AI service and memory port; encode the complete typed session
identity with a standard structured serializer, not separator escaping or a
platform-specific branch. Platform values use their explicit persisted value.
The in-memory history and newly written memory turns share this canonical key.
No additional identity registry, memory store or platform adapter is introduced.

Replace the memory prompt's assumption that every actor is a QQ user with a
platform-neutral actor description. The existing long-memory policy is retained:
unscoped users may reuse their own memory across conversations; scoped members
cannot reuse another scope's memory. Model output remains subject to outbound
capabilities and reply expiry, enforced by the test transport in this slice.

## Scope And Non-Goals

- Real AiService, real SQLite memory, FeatureService, administrator notice
  delivery and test-only FakeOfficialPlatform; fake only the model/network.
- Preserve OneBot error visibility and notices; do not change feature gates in
  the command/matcher adapters or enable real official accounts.
- No new dependency, TOML field, database schema or old-key fallback parser.
- Existing stored keys remain historical sessions; rows remain readable by
  typed actor columns. New sessions use the new encoding, without rewriting
  deployed history. A key-format boundary may retain older turns as long-term
  memory rather than classifying them as the active short session.
- Do not claim full platform acceptance, live QQ behavior or Seer rendering.

## Acceptance Tests

- [x] Reproduce short-history collision with two valid scoped actor/conversation
  pairs; structured encoding prevents the cross-actor history leak.
- [x] Canonical identity distinguishes platform, conversation kind, actor kind,
  scope, punctuation, Unicode and field boundaries; repeated identity is stable.
- [x] Real SQLite memory survives service restart but stays isolated by actor,
  platform and scope; same-session memory is not replayed twice.
- [x] Actual AI results can pass through the outbound port; reply expiry and
  proactive notice denial remain explicit, without OneBot conversion.
- [x] API errors preserve existing administrator/ordinary-user visibility.
- [x] Existing AI/OneBot tests, full pytest, Ruff, types, compileall, diff check.

## Progress And Evidence

Program: 3/8 phases verified; total ETA not established.
Current slice: verified. Before the fix, the new service-level reproduction
failed because the second actor's completion request contained `first secret`;
the other five initial acceptance cases passed. After structural JSON encoding,
the reproduction and lossless-key case pass without alternate identity paths.

Verification on 2026-09-05:

- AI service/memory and platform focused tests: 32 passed.
- `uv run pytest -q --basetemp=.test-tmp/ai-platform-full`:
  1596 passed, 87 pre-existing dependency warnings, 84.89 seconds.
- `uv run ruff check ironsbot tests`: passed.
- `uv run basedpyright`: 0 errors, 0 warnings, 0 notes.
- `uv run python -m compileall -q ironsbot`, `git diff --check`: passed.

No schema migration is required. Code rollback is a commit revert; production
files have not been rewritten. Existing persisted turns are loaded by typed
identity columns, never by reverse-parsing either old or new session keys.
No production data or upstream/main changes in this slice.
