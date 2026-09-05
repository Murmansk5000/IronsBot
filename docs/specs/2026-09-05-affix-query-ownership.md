# Shared Affix Query Ownership

Status: `verified`

Contract: `target` command parsing; preserve `baseline` query syntax.

Owner: core affix parser, domain command contracts, OneBot state adapter.

## Problem And Scope

Seer fuzzy queries currently define their prefix/suffix grammar inside OneBot
rules. Their catalog descriptors mostly recognize only help examples, so private
AI ownership differs from the real parameterized query entry. Pet configuration
also imports a Seer plugin's exclusion rules.

Extract the existing affix algorithm into a pure parser, consumed by both the
catalog and OneBot. Cover all current affix-rule consumers: pet info/images,
mintmarks/gems, equipment, types/abnormal states, teams, autocards/sanctuaries,
and pet configuration. Preserve argument whitespace, case handling, prefix order,
overlapping suffix behavior, feature policy and existing rank/image exclusions.

## Ownership And Reuse

- Core owns literal affix parsing and its typed argument result, not Seer syntax.
- Domain services own affixes and exclusion predicates. Reuse existing rank,
  team-ID and autocard syntax instead of another keyword list.
- OneBot only reads plaintext and writes the existing argument/state keys.
- CommandCatalog reuses `parsed_command_input_matcher`; no new command registry.
- Exact configured image commands are injected into both query admission paths.
- When a contract supplies an input matcher, it is authoritative, including
  rejection of a help example. Exact examples/aliases remain the fallback only
  for contracts without a parser. Verify existing parser-backed domains rather
  than retaining an example-specific bypass; their real grammar must cover any
  accepted aliases.
- No data/config/schema/dependency changes, release operations or main merge.

## Non-Goals

Do not change player alias ownership, query search algorithms, menus, mention
policy, or natural-language product behavior. Separate fixed peak aliases and
other non-affix grammars remain an explicit subsequent Phase 5 coverage audit.

## Acceptance

- Parameterized queries beyond help examples are recognized by their actual
  catalog contract, and enabled private AI yields to them.
- Disabled features and non-command text are not claimed.
- Catalog and actual OneBot affix rule agree on inputs and argument extraction.
- Rank syntax and configured exact images still bypass fuzzy query ownership;
  bare team queries still belong to subscriptions rather than numeric lookup.
- Prefix-only, suffix-only, both, overlap, case, whitespace and regex literals
  retain existing behavior.
- Remove the OneBot-owned parsing implementation and duplicated exclusion rules
  after all consumers migrate; no old-function compatibility wrapper.
- Focused parser/catalog/AI/query tests, Ruff, typecheck, compileall, diff check.

## Migration And Progress

No persistent migration. Revert the code commit to roll back; no live data touched.
Program remains 4/8 verified phases. This slice is verified; implementation and
regression are complete. Total ETA remains unverified pending remaining-gate
inventory. Fixed peak aliases and countermark-stat rank ownership still need
their actual grammar connected to the catalog; Phase 5 is not complete.

## Evidence

- Local main remains `963a83c3`; read only, not merged.
- Red: 16 parameterized examples failed catalog ownership before implementation.
- Shared parser/adapter/catalog/rank tests: 606 passed before the final three
  authority/pet-config regression cases; final public full suite includes them.
- Public full suite: `uv run pytest -q --basetemp=.test-tmp/affix-full --tb=short`:
  2493 passed, 301 framework/ORM warnings, 382.73 seconds.
- Private extension against this public worktree: 26 passed, 2.24 seconds;
  its existing untracked `uv.lock` was untouched. SeerAPI has no changes.
- `uv run basedpyright ironsbot tests`: 0 errors, 0 warnings.
- `uv run ruff check ironsbot tests`, compileall and `git diff --check`: passed.
- Searches of public/private production code found no remaining old affix-rule
  or deleted query-rule imports. No wrapper retained.
- Parser authority exposed a rank overview descriptor that combined an exact
  entry and parameterized parser: it now explicitly uses both real domain
  grammars, including `/榜单状态`, with unchanged superuser permissions.
- No new dependency, image build, publication, or production change. Source
  extraction and added command ownership are not evidence of image-size savings.
  Production Python is net +63 lines, including the extracted pure parser and
  all newly connected command ownership, rather than a claimed size reduction.
