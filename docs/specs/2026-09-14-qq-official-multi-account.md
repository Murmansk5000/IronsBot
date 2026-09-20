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
- Each enabled account requires `QQ_OFFICIAL_APP_ID_<ALIAS_UPPER>` and
  `QQ_OFFICIAL_SECRET_<ALIAS_UPPER>`. AppID and AppSecret are deployment
  credentials and are rejected when written directly in TOML.
- The retired static Token and old single-account fields are rejected.
- Accounts in one process use the same production or sandbox environment because
  the Tencent SDK API base is process-wide.

## Runtime Contract

- Bootstrap creates one Tencent SDK API client, WebSocket, and session store for
  each enabled account.
- Inbound identity uses the owning connection's AppID as `account_id`.
- Feature defaults, logical identity policy, and superusers are compiled per AppID.
- C2C superusers use `user_openid`; group superusers are explicitly scoped by
  group OpenID and `member_openid`, and are not private-message targets.
- Official outbound targets without an AppID, or with an unknown AppID, fail;
  there is no default-account fallback.
- Proactive permission and passive reply sequence allocation are per AppID.
- Persistent account columns and their offline v2 migration are specified by the
  preceding account-scoped state work.

## Shared-Group Topology

- One NoneBot process may accept several OneBot/NapCat connections. Silent
  identity observation treats them as interchangeable observers; duplicate
  reports of one official reply do not count as independent confirmations.
- Every official account has one distinct trusted bot QQ number. Observation
  first selects that trusted sender, then requires the owning AppID, mapped
  official group OpenID, numeric OneBot group, exact normalized reply text and
  one mentioned QQ member to agree.
- Several official accounts may be present in the same numeric QQ group without
  sharing identity state. Their OpenIDs and links remain scoped by AppID.
- Only one official account in a group should enable full-message command
  handling. If two accounts receive all group messages and expose the same
  command, both may legitimately claim an unaddressed command and send duplicate
  replies. Other accounts in that group must remain mention-only or disable the
  overlapping features; identity isolation is not responder election.
- A second NapCat observer is redundant, not an automatic failover mechanism.
  Deployments that require observer high availability need an explicit
  connection-health and leader policy rather than relying on duplicate events.

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
- [x] Duplicate NapCat observations cannot satisfy the two-observation threshold.
- [x] Trusted bot QQ and AppID isolate observations when accounts share a group.
- [x] Full pytest, Ruff, BasedPyright, compileall, diff checks, and preview image
  build pass.

## Evidence

Commit `4de228dd` implements the target path. Public tests completed with
`3340 passed, 7 skipped`; Ruff and BasedPyright reported no findings. Private
preview workflow `34777514033` built, smoke-tested, size-checked, and published
the image successfully.

On 2026-09-19, a second, independently configured public-facing account was
checked directly against Tencent without starting the existing personal account.
The runtime obtained its credentials from ignored environment configuration,
reached `ready`, remained `ready` during the observation interval, and completed
a normal transition to `stopped`. No message was sent and no AppID, AppSecret,
OpenID, or access token was logged. This proves the second account's credential
and isolated lifecycle path, but not simultaneous two-account delivery.

The same account then passed a bounded full-application smoke using an isolated
temporary TOML and state root. `bootstrap()` loaded the core manifest and six
plugin contributions, cached Seer databases, command catalog, lifecycle and
official transport; resource startup reached `ready` while OneBot message
handling remained disabled, stayed healthy during observation, and resource
shutdown reached `stopped`. The smoke emitted only the two already-known
SQLAlchemy relationship warnings. It did not send a client-visible message and
therefore does not close any Phase 7 delivery row.

A subsequent bounded live run used the same isolated core configuration. The
public account recovered from one unexpected WebSocket close and returned to
`ready` in about three seconds. It then received a real `C2C_MESSAGE_CREATE`
for the `帮助` command, classified the input as direct, claimed the command once,
and received a successful Tencent passive-send response for text sequence 1.
The user subsequently confirmed that the first-level help was visible in the QQ
client. A second isolated run received `帮助`, `1`, `2`, `0`, and `3` in order:
the first four inputs were recognized and each produced one successful passive
delivery, while `3` after exit was explicitly unrecognized and was not consumed
by the closed menu. This proves real inbound routing, reconnect recovery, client
visibility for C2C help, and menu-exit cleanup for the second account. Group help
and the exact rendered contents of the two second-level pages remain separate
acceptance gates.

Commit `108c4fc0` adds regression evidence that duplicate NapCat observations
cannot satisfy the confirmation threshold and that trusted bot QQ plus AppID
separate observations when two official accounts share one numeric group. The
post-commit full suite completed with `3817 passed, 7 skipped`; Ruff, formatting,
production and test BasedPyright, compileall, repository static checks, and diff
checks all passed.

## Remaining External Gate

This spec does not yet claim simultaneous login of two accounts in one process,
cross-account passive or proactive delivery, or shared-group client behavior.
Phase 7 remains open until those operations are verified with a precise build and
the platform-granted permissions and quotas.

## Rollback

Revert `4de228dd` and this evidence update. Persistent state already includes the
account dimension and must not be downgraded or read through an account-less
compatibility path.
