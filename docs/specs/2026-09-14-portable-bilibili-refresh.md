# Portable Bilibili Refresh

Status: completed

## Goal

Expose the existing superuser-only Bilibili refresh command through the shared
portable command router without copying OneBot matcher behavior. Both adapters
must use one domain-owned result classification.

## Contract

- `BilibiliMonitorService.manual_refresh()` owns forced refresh execution and
  maps monitor results to the existing user-facing completion, busy or failure
  message.
- OneBot may send its existing progress message before awaiting the shared
  method. Passive QQ Official returns the final message only.
- An executed check with an invalid HTTP/auth response is a failure, not a
  successful refresh.
- Command authorization remains owned by the existing `bilibili.refresh`
  catalog contract and its superuser access rule.
- No configuration, database, dependency, asset or image change is introduced.

## Acceptance

- Completed, busy and invalid-response outcomes have service tests.
- The portable operation map includes `bilibili.refresh` and executes the shared
  method.
- A regular QQ Official actor cannot see or dispatch the command; a configured
  superuser can.
- Bilibili, portable router and QQ Official regression tests pass, followed by
  Ruff, BasedPyright, compileall and diff checks.

## Evidence

- Targeted Bilibili/catalog/QQ Official verification: `75 passed`.
- Full verification: `3368 passed, 7 skipped`; Ruff, BasedPyright (zero errors),
  compileall, structural checks and diff checks passed.
- The complete example catalog now has 60 of 75 commands backed by portable
  operations. The remaining commands are explicitly bounded to numeric-QQ skin
  accounts, long-running maintenance/progress delivery, or group rank settings.
- No runtime dependency, configuration, database, asset or image layer was
  added.
