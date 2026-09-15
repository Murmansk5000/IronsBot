# QQ Official Multi-Account Isolation

Status: `implemented`

Contract: `target`

Owner: QQ Official configuration adapter, feature policy, bootstrap, and
outbound transport adapter.

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md)
Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

## Problem

QQ Official OpenIDs belong to one bot application. A process-wide default bot,
shared token state, or account-less outbound fallback can deliver with the wrong
AppID and cannot safely support several bots with one IronsBot service.

## Goal

Run several QQ Official bot accounts in one IronsBot process while preserving one
shared command and business-service implementation. Isolate credentials,
connections, feature defaults, superusers, OpenID policies, persisted identity,
reply sequences, and outbound routing by the owning AppID.

## Configuration Contract

- `[bot.qq_official]` owns process-wide enablement and sandbox selection.
- `[bot.qq_official.accounts.<alias>]` owns one account. Aliases contain only
  letters, digits, and underscores and are unique ignoring case.
- Each enabled account loads its unique AppID and AppSecret from
  `QQ_OFFICIAL_APP_ID_<ALIAS_UPPER>` and
  `QQ_OFFICIAL_SECRET_<ALIAS_UPPER>`.
- The retired static Token and old single-account fields are rejected.
- Accounts in one process use the same production or sandbox environment because
  the Tencent SDK API base is process-wide.

## Runtime Contract

- Bootstrap creates one Tencent SDK API client, WebSocket, and session store for
  each enabled account.
- Inbound identity uses the owning connection's AppID as `account_id`.
- Feature defaults, OpenID policy, and superusers are compiled per AppID.
- C2C superusers use `user_openid`; group superusers are explicitly scoped by
  group OpenID and `member_openid`, and are not private-message targets.
- Official outbound targets without an AppID, or with an unknown AppID, fail;
  there is no default-account fallback.
- Proactive permission and passive reply sequence allocation are per AppID.
- Persistent account columns and their offline v2 migration are specified by the
  preceding account-scoped state work.

## Dependency Evidence

The Tencent `qqbot-agent-sdk 1.2.2` transport constructs one `QQApiClient`,
`QQWebSocket`, and persisted resume session per AppID. Token requests use that
instance's AppID and AppSecret. This matches Tencent's public multi-account
guidance, which requires independent connection, token cache, and OpenID routing
for every AppID.

## Acceptance

- [x] Two accounts load independent environment secrets.
- [x] Disabled accounts do not enter adapter configuration.
- [x] Duplicate AppIDs and colliding environment aliases are rejected.
- [x] The same OpenID receives different feature defaults under two AppIDs.
- [x] Proactive delivery selects the owning bot and per-account permission.
- [x] Identical message IDs allocate independent reply sequences per AppID.
- [x] Account-less and unknown-account outbound targets are rejected.
- [x] Full pytest, Ruff, BasedPyright, compileall, diff checks, and preview image
  build pass.

## Evidence

Commit `4de228dd` implements the target path. Public tests completed with
`3340 passed, 7 skipped`; Ruff and BasedPyright reported no findings. Private
preview workflow `34777514033` built, smoke-tested, size-checked, and published
the image successfully.

## Remaining External Gate

This spec does not claim successful login, passive reply, or proactive delivery
against a real QQ application. Phase 7 remains open until those operations are
verified with real AppIDs and the platform-granted permissions and quotas.

## Rollback

Revert `4de228dd` and this evidence update. Persistent state already includes the
account dimension and must not be downgraded or read through an account-less
compatibility path.
