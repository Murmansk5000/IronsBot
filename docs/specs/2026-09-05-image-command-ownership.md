# Configured Image Command Ownership

Status: `verified`

Contract: `target` shared domain input grammar; preserve `baseline` OneBot image queries.

Owner: `services.messaging.sendpic`, with the existing core affix parser and
OneBot event/state adapter.

## Problem

Indexed image commands use NoneBot command parsing and validate text inside the
handler, while their catalog only recognizes bare examples. Numbered queries
can therefore fall through to private AI. Single-image catalog normalization
also accepts spellings that the actual fullmatch rule rejects.

## Design

- Inject existing `bot.command_start` into the image service at composition.
  No driver/config reads from services and no new TOML field or dependency.
- Reuse `AffixCommand` for literal indexed command prefixes, ordered longest
  first across configured indexed galleries. Preserve case sensitivity, leading
  whitespace removal and argument-leading whitespace removal; do not silently
  allow trailing whitespace inside a numeric argument.
- The domain returns a typed gallery ID and optional integer index. Both catalog
  admission and the installed rule use this parser. The handler consumes the
  stored result; fetching and selection do not parse the original string again.
- Keep NoneBot's command gate for transport segment handling and its global
  command-prefix routing; the service adds domain validation, not another AI
  keyword table. Single images remain exact fullmatches, without command starts.
- Empty starts disable indexed entrypoints and their help, not single images.
  Indexed help examples use an actually configured start, preferring the empty
  start when available. Longest alias selection must not fall back to a shorter
  gallery merely because the longer one's argument is invalid.
- The exact-image spellings supplied to other domain query guards use those
  same configured starts; prefix-only galleries must not reserve a bare spelling.
- Reject non-decimal digit lookalikes and unrepresentable integer input before
  I/O instead of raising an uncaught integer-conversion error. Zero/out-of-range
  numeric input remains owned and keeps the existing range diagnostic.
- No compatibility wrapper, new production module, state migration or main
  feature import. Local main `d8c5c7ee` is read only.

## Acceptance

- Numbered, random, alias and configured-prefix inputs share catalog, actual
  installed rule and handler output; disabled features are not claimed by AI.
- Compare valid inputs to the installed NoneBot parser, including overlapping
  gallery aliases, leading whitespace and fullwidth decimal digits.
- Invalid text, extra prefixes, case changes and trailing numeric whitespace
  are not claimed. Invalid arguments do not count/download files.
- Typed index reaches the backend once, random selection stays in the domain,
  and unavailable indices retain the existing error.
- Single images have exact grammar; empty starts only suppress indexed commands.
- Run focused image/catalog/adapter tests, public types/Ruff/compileall/full
  regression, private extension regression and diff checks.

## Progress And Risk

Program: 4/8 verified phases. This task is implemented and verified; the whole
program has no evidence-backed ETA. Segmented-message facts remain a transport
gate, not a string parser responsibility. No actual image-size reduction is
claimed. Rollback is a code revert; no production configuration changes.

## Evidence

- Before implementation, `表情包2` had no catalog owner (one reproduced failure).
- Final focused image/catalog/affix/plugin-import suite: 95 passed, 27 existing
  dependency warnings. The adapter matrix compares stored typed indices with
  NoneBot's actual command argument and exercises the installed handler.
- Private extension: 26 passed. Public BasedPyright: 0 errors/warnings; Ruff,
  compileall and diff checks passed. Full public regression: 2671 passed,
  319 existing dependency warnings, 187.84 seconds (including bootstrap smoke).
- Production change: 60 net added lines in three existing modules; no new
  production module or runtime dependency. No producer/private code changes.
- Remaining general contract audit: descriptors without a routing parser still
  normalize exact examples, whereas several fixed OneBot fullmatches use literal
  text. Resolve this at the common exact-input contract, not with another set of
  per-plugin exceptions. This slice only fixes the image domain's admission.
  Read-only reproduction: `帮 助` is claimed by the help contract, while the
  installed NoneBot `fullmatch("帮助")` rejects it.
