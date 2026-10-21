# Separate Autocard Data Commands And Share Player Standings

Status: `implemented`

Contract: `baseline`

Owner: shared Seer command grammar, command catalog and player shortcut service.

## Scope And Design

Use 群星卡牌, 群星角色, 群星场地 and 群星芯片 for separate typed game-data
lookups. Keep 卡牌, 场地, 圣域, 祝印, 战斗芯片, 强化芯片 and 芯片 aliases.
Remove former game-data prefixes/suffixes containing 群星牌. Preserve 群星牌
for player standings. Retired explicit commands remain silent, not AI prompts.

Rename weekly umbrella commands to 新增/每周/本周/更新群星. Give cards,
roles, sanctuary effects and chips separate category commands using the same
four data names. 新增卡牌 is card-only. Keep existing short sanctuary aliases.

Use 群星之巅榜 as the primary official rank alias; remove 群星牌榜, keep
other official aliases. Rename sample aliases to 样本群星积分榜 and
机器人群星积分榜. Internal keys, SQLite schema and feature names do not change.

Explicit autocard leaderboard player targets delegate to the existing player
shortcut operation. Resolve once and share action identity, cache/prewarm,
quota, binding policy and output. Admission remains owned by each original
command's feature. Bare ranks and score/window queries stay rank operations;
rank-row selection still opens player profiles.

## Acceptance

- Both platforms have one owner per data, weekly, player and rank command.
- Card/role/chip numeric IDs and partial names stay scoped to their kind.
- Former commands are silent; retained aliases and normal player queries work.
- Autocard rank player targets use the same action, target, cache and quota as
  player shortcuts; preserve access checks and shared-menu semantics.
- Run targeted tests, Ruff, BasedPyright, compileall and diff checks.

## Delivery And Rollback

Independent bilingual commit and cumulative private archive only; do not push
public main, deploy or fold history. Preserve unrelated working changes and
reserved mintmark files. Revert the independent commit to roll back; no data
or configuration migration is needed.

## Verification Evidence

- 1,367 targeted tests passed, covering command ownership, typed data searches,
  weekly category scopes, rank parsing, ambiguous/member player targets,
  feature admission, shared cooldowns, player cache/prewarm and shared menus.
- Ruff formatting/lint, BasedPyright (zero errors), compileall and
  `git diff --check` passed for the change scope.
- No production queries, configuration changes or deployment were performed.
