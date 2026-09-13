# Portable Rank Display Limit

Status: completed

## Goal

Allow an authorized QQ Official group manager to configure that group's default
rank display count through the existing platform-neutral rank service and
account-scoped state store.

## Contract

- The existing `rank.display_limit` command contract remains the only syntax and
  authorization owner.
- The portable operation parses the existing slash-prefixed command and calls
  `RankQueryService.set_display_limit()` with the full actor and conversation
  references.
- Catalog authorization admits only group owners, administrators and configured
  superusers. The domain service still receives `can_manage=True` only after that
  authorization and retains its own scope/range validation.
- Storage remains keyed by platform, AppID, conversation kind and group OpenID;
  no QQ-number mapping or default-account fallback is introduced.
- No configuration, migration, dependency, asset or image change is introduced.

## Acceptance

- Portable parsing preserves the required `/` syntax and writes through the
  shared rank service.
- A regular QQ Official group member cannot recognize or dispatch the command;
  a group administrator can.
- Existing OneBot rank behavior and account-scoped storage tests remain green.
- Ruff, BasedPyright, pytest, compileall, structural and diff checks pass.

## Evidence

- Targeted rank/QQ Official/storage verification: `55 passed`.
- Full verification: `3370 passed, 7 skipped`; Ruff, BasedPyright (zero errors),
  compileall, structural checks and diff checks passed.
- The complete example catalog now has 61 of 75 commands backed by portable
  operations.
- No runtime dependency, configuration, migration, database, asset or image
  layer was added.
