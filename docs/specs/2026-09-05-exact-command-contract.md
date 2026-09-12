# Exact Command Contract

Status: `verified`

Contract: `target` explicit syntax ownership; preserve `baseline` matcher behavior.

Owner: `core.command_catalog` with existing domain command parsers.

## Problem

The catalog normalizes every exact example and alias by removing whitespace and
lowercasing. OneBot fullmatch does neither by default. This is reproduced for
`帮 助`: the help descriptor claims it, but the real fullmatch rejects it.
Normalizing by default also allocates another normalized set on every lookup.

## Design

- Exact examples/aliases are literal, including their case, whitespace and slash.
  Parameter placeholders do not become literal inputs. An explicit parser is
  authoritative and receives the original text without catalog normalization.
- Private AI must also pass original input to the catalog; prompt trimming only
  happens after command ownership has been decided. Its current pre-check strip
  would otherwise bypass the exact-input policy for surrounding whitespace.
- Existing intentionally normalized entrypoints opt into one shared catalog
  adapter around `core.commands.command_text_matches`. This includes configured
  text replies, push subscription/time menus, meeting, Bilibili fixed commands
  and subscribed-team shortcuts. Their actual rules already use that helper.
- Remove the single-image exact parser wrapper introduced before the catalog
  default was corrected. Indexed images still use their real argument parser.
- Correct the rank-page overview's literal-alias branch; its parameter parser
  retains its own normalization and required prefix. Do not make a fixed alias
  broad merely because another branch accepts normalized parameters.
- No matcher behavior, config, storage, dependency or platform API changes.
  No new flag on every descriptor, compatibility wrapper or AI keyword list.

## Acceptance

- Core tests reject implicit case changes, removed/added whitespace and prefix
  changes; literal whitespace in a registered command is significant.
- Help/about/rank/operations fixed examples agree with actual fullmatch rules.
- TD and intended normalized configured/Bilibili/meeting/team inputs continue
  to match both catalog and actual domain/adapter checks; permissions still apply.
- Raw parser input, parser rejection, placeholder, automatic/conversation and
  private-AI behavior remain covered. Single and indexed image regressions pass.
- Public full suite, focused command tests, types, Ruff, compileall, private
  extension and diff checks pass before commit.

## Upstream And Progress

Local main advanced from `d8c5c7ee` to `4b82881b`, which replaces configured
message strings with arrays across commands and schedules. Read only; not
ported into this command-contract change. It requires a separate target spec.
On 2026-09-12 local main is `ba08f749`; the additional eleven commits were
inspected read-only and are tracked in the phase ledger, not ported here.
Program: 4/8 verified phases. Task estimate: 30-60 minutes. No reliable whole
program ETA or actual image-size measurement. Rollback is a code commit revert.

## Evidence

- Revalidated on 2026-09-12 after the earlier full-suite handle was missing and
  no matching test process remained. Earlier partial output was not counted as
  a successful run.
- Public full suite: 2697 passed, 319 dependency warnings, 203.24 seconds;
  `--basetemp=.test-tmp/exact-contract-final-0912 --tb=short`.
- Exact ownership and catalog focused tests: 37 passed in 1.73 seconds.
  Tests include installed help/about and meeting rules, raw private-AI input,
  intended domain normalization and literal case/whitespace rejection.
- Real private extension: 26 passed in 4.03 seconds against this public tree.
  Its pre-existing untracked `uv.lock` was not modified or committed.
- Ruff passed; BasedPyright reported zero errors/warnings; compileall and
  `git diff --check` passed. No producer code changes.
- Production net change: +29 lines, no new runtime module, dependency, schema
  or TOML field. Docker Linux engine is unavailable; no image-size claim.
- This closes exact-input ownership only, not all command domains, source-time
  cache admission, real asset publication or whole-program acceptance.
