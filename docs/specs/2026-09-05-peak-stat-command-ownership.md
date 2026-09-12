# Peak, Countermark And Data Command Ownership

Status: `verified`

Contract: `target` domain-owned command grammar, preserve `baseline` query behavior.

## Problem

Peak pool/vote/item/pet-rank aliases remain literal tuples in the OneBot plugin.
The catalog only owns selected examples. Countermark stat ranking already has a
pure parser, but its descriptor does not use it and the plugin calls a redundant
service wrapper. Its exclusion of collection rankings duplicates six names from
the rank catalog.

## Design And Scope

- Move peak aliases into the existing peak domain module. Derive mode-specific
  item/pet commands from its existing mode-name map. Both plugin and catalog
  consume these constants, preserving exact fullmatch semantics (including no
  implicit slash or whitespace spelling).
- Countermark plugin and catalog both call the existing stat parser directly;
  remove the service parser wrapper and test fake.
- Replace the six-name exclusion list with the actual rank-list parser. This
  preserves current names and lets new global/sample aliases remain under their
  existing command owner without another synchronization list.
- Unknown stat terms remain owned validation errors, not unrecognized AI input.
- The same fixed-command audit found that data help examples omit season aliases
  and incorrectly claim the new-content root. Include the existing data command
  tuples in authoritative catalog admission, without changing visible examples
  or the distinct new-content owner.
- No persistence, dependency, renderer, network lookup, permission, config or
  live deployment changes. No new production module or compatibility wrapper.

## Acceptance

- All installed peak aliases have exactly the expected catalog owner, remain
  feature gated, and make private AI yield. Invalid surrounding text is rejected.
- Countermark stat/angle/combination and rank suffix variants are owned; unknown
  stats keep their command-specific validation. Real installed rule stores the
  same parsed object consumed by the query service.
- All current global/sample aliases remain outside stat ranking; a newly added
  rank alias is covered by the existing rank parser, not a copied list.
- Every installed data query alias is recognized; `新增内容` belongs to the
  new-content command, not the generic data helper descriptor.
- Static/type/compile checks and query/catalog/rank regressions pass. Run public
  full suite and private extension regression before committing.

## Progress And Upstream

Program: 4/8 verified phases. Task: implementation and verification complete.
Overall ETA is not established by this slice. This completes the identified
peak/stat/data syntax gaps, not all remaining Phase 5/cache/release requirements.
The broader audit still finds indexed image commands whose argument/prefix
ownership needs a separate shared grammar, not a guessed AI-only prefix rule.

The initial local-main observation was `d15c02f8`: `6b52bee9` added backpack
badges and the next commit reverted it, leaving no diff from `963a83c3`.
On resume, local main had advanced to `d8c5c7ee`, after `dbcfb241` (master-pool
test annotations) and `d8c5c7ee` (configured fixed-command multipart replies).
These later changes were read only, not fetched, merged or ported. Multipart
reply validation and ordered delivery need their own target-boundary spec;
this command-ownership slice does not implement that main feature.

## Evidence

- Initial ownership tests reproduced nine failures; the expanded data cases
  reproduced missing season-alias ownership and duplicate new-content ownership.
- Resumed final focused suite: 212 passed, 18 dependency deprecation warnings.
- Private extension: 26 passed against this public worktree; its pre-existing
  untracked `uv.lock` was preserved. No private or producer code changes.
- Ruff, BasedPyright (0 errors/warnings), compileall and diff checks passed.
- Earlier full suite, before the data cases were added: 2639 passed, 1 failed.
  The bootstrap subprocess exceeded its existing 30-second timeout; unchanged
  isolated rerun passed in 26.93 seconds. This is not proof of a resolved root
  cause and its timeout has not been relaxed.
- Final full public suite: 2645 passed, 319 warnings, 306.18 seconds. This run
  included the unchanged bootstrap smoke test. Warnings are NoneBot forward
  annotation deprecations and SQLAlchemy relationship overlap diagnostics.
- Production diff: 46 net added lines, no new production module, dependency,
  schema or config. Actual container size has not been measured.

Rollback is a code commit revert; no production state migration is required.
