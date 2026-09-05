# Platform Identity Closure Audit

Status: `verified`

Contract: `target`

Owner: core platform/feature/command access; shared admin-notice sender.

## Audit Scope

Close Phase 1 against its existing requirements, not against a smaller new
definition. Inventory: feature policy, cooldown, rate limits, subscriptions,
administrator notices, actor/conversation state repositories, the single
offline migration CLI, and private-extension identity/state contracts.
Seer player/rank/headless IDs and pet partner group IDs are domain integers,
not transport identities; they remain numeric.

## Findings And Design

FeatureService currently accepts a member scoped to group A when evaluating
group B; a member used as a private actor raises instead of denying access.
CommandAccess without a feature check can also grant mismatched contexts, and
`both` treats channel/guild as supported although commands only declare group
and private semantics. Add one shared shape predicate for those two supported
message contexts. Check platform first, require member scope to match a group,
and require an unscoped user's ID for private context. Unknown channel/guild
authorization fails closed until an explicit contract exists. This predicate
does not assert actual membership; authenticated adapters supply that fact.

Shared administrator delivery currently converts every superuser into a private
conversation, raising for scoped members. Report those recipients as failed and
continue valid targets. Never guess a private ID or send private notices to the
member's group instead. The private-conversation constructor remains strict.

The remaining OneBot help-hint limiter caller passes a raw group integer to
the common limiter. Convert it to ConversationRef at that existing adapter
boundary; preserve its namespace and window behavior. Add an architecture
guard preventing runtime packages from importing identity migration modules,
and verify CLI errors as well as service-level migration failures.

## Reuse And Non-Goals

- Reuse ActorRef, ConversationRef, CommandAccess, FeatureService, and existing
  delivery summaries; no second permission service or platform adapter.
- Do not change OneBot numeric edge conversion, Seer domain IDs or any schema.
- Do not fetch/merge main, modify production files or touch the private repo's
  existing untracked uv.lock.
- Remaining image release and whole-platform smoke gates belong to other phases.

## Acceptance And Closure Evidence

- [x] Reproduce invalid context grants and scoped-recipient batch failure.
- [x] Valid OneBot/opaque private/group contexts retain behavior; cross-platform,
  cross-group members, mismatched private actors and unsupported scopes deny
  access even for manager/superuser/featureless commands.
- [x] Scoped private recipients are logged and returned as failures; valid
  private and group recipients still receive notifications.
- [x] Inventory all identity-bearing repositories and public service entry points;
  prove legacy identity reads are isolated to the offline migration tool.
- [x] Run empty/normal/duplicate/corrupt/interrupted offline-migration coverage.
- [x] Run actual private-extension contract tests against this checkout.
- [x] Public full pytest, Ruff, BasedPyright, compileall and diff checks.

## Progress

Program advances from 3/8 to 4/8 verified phases when this verified slice is
committed. Phase 1's original gates above are satisfied; Phases 4/5/6/7 retain
their separate uncompleted gates. No overall ETA is claimed.

Migration: none. Rollback is code-only; production databases remain unchanged.

## Inventory Evidence

Inspected on 2026-09-05, including declarations, call sites and SQL ownership:

| Phase 1 requirement | Authoritative code and verification |
| --- | --- |
| Feature/command identity | `core.feature_policy`, `core.command_catalog`, `core.platform`; the new invalid-context tests failed in seven cases before the fix and pass afterwards |
| Cooldown and rate limits | `CommandCooldownService` keys by `(ActorRef, command_id)`; `BotMentionBlockService` keys by ActorRef; OneBot help hints now pass ConversationRef; AI error throttling intentionally keys by error class, not a user identity |
| Actor state | `player_bindings`, `player_query_limits`, `lucky_skin_watch`, and `ai_memory` repositories use ActorIdentityColumns, retaining platform/kind/id/scope in predicates and keys |
| Conversation/mixed state | `push_subscriptions`, `bilibili_preferences`, `rank_display`, `team_resources`, `team_audit` repositories use typed public parameters and independent actor/conversation columns; no old integer-identity read path remains in these repositories |
| Identity-free stores | Activity reminder/snapshot and lucky-skin daily cache records use activity/date/Seer-account keys; rank/player sample/lineup caches use Seer IDs; file/image caches use content keys. These are not missing QQ migrations |
| Offline migration | Only `state_migration` / `platform_state_migration` import `platform_state_schema`; the single CLI owns argument parsing/output/exit status. Static layer tests guard these imports; migration tests cover read-only dry runs, empty roots, invalid/duplicate rows, corrupt input, interrupted build/install, restoration and idempotency |
| Private extension | Actual checkout `ironsbot-private` at `a278d11`: production imports use public core/extensions contracts, not app/runtime/services/integrations. All 24 private tests passed with `IRONSBOT_PUBLIC_ROOT` explicitly set to this V5 worktree; the existing untracked uv.lock was not modified |

Targeted closure/CLI/layer/hint tests: 57 passed. Earlier feature/catalog/AI/
delivery/migration regression selection: 62 passed.

Final verification (2026-09-05):

- `uv run pytest -q --basetemp=.test-tmp/identity-closure-final-full`:
  1608 passed, 87 pre-existing dependency warnings, 85.25 seconds.
- `uv run basedpyright`: 0 errors, 0 warnings, 0 notes.
- `uv run ruff check ironsbot tests`, `uv run python -m compileall -q ironsbot`,
  `git diff --check`: passed.
- Private `pytest -q` with this checkout's Python and explicit public-root env:
  24 passed, 1.58 seconds; private working-tree state unchanged.

No production migration was performed or needed to verify this phase. Catchable
migration interruption is tested with restored sources and retry; this does not
claim multi-file atomicity across process kill or power failure.
