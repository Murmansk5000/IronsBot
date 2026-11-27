# Effect container visibility

Status: `verified`

Contract: `baseline`

Owner: SeerAPI facts; IronsBot seer_data adapter consumption.

## Problem And Goal

A client status container with no independent description currently appears as
an extra card beside its two real forms. Hide only producer-confirmed containers,
while preserving complete state data and useful standalone effects.

## Ownership And Contract

SeerAPI owns `pet_special_effect.display_in_pet_info`, a boolean defaulting to
true. It evaluates complete, evidence-bound branches and retains independent
descriptions, glossary identities and panel evidence. IronsBot filters false
rows before view construction and image requests. No pet ID, name, text matching
or equal-image inference is allowed in the consumer. No new command or layout.

Old databases without this column retain their previous display. Present but
malformed flags fail the existing strict boolean contract rather than silently
hiding data. No production configuration, pinned dependency or deployment changes.

## Delivery And Acceptance

- Test false/true and missing flags, malformed flags and identical icon keys.
- Render the real candidate: both actual forms remain with their own text,
  icons and source labels; the container card and its image request disappear.
- Render independent-description controls and preserve unrelated entries.
- Run complete pytest, Ruff, static checks and diff checks.
- Commit and normally push main after joint acceptance, verify cumulative
  original-history archive and automatic Actions. Never rewrite history.

## Evidence

- Candidate SHA256: `06b046a21fd7a73925225877e582e78a7a098dc5f9c4e7edda4de4ace8681991`.
- Producer replay preserves every preexisting field in 723 facts, 1446 sources
  and 404 issues. One container is hidden; three independent-description control
  states remain visible. No per-pet rule.
- Real Python 3.11 backend: 4872 shows both named forms and the existing glossary
  effect, requests sign_buff/151_2 and /151_3 but not /151. Controls 4620, 4643
  and 4816 retain their state text and icons. A separate preexisting mintmark
  20447 asset is unavailable in the 4643 control, not a state-icon failure.
- 55 focused tests, changed-file format, repository Ruff (excluding reserved
  working files), targeted basedpyright and diff checks passed. Python 3.11
  remaining-suite validation passed: 7728 passed, 13 skipped; the reserved
  ordinal-resolver test file was explicitly excluded. Producer CI also passed
  on commit 6438e14f36da7d9fc9663825c8028ef5aaad9b58. No deployment is claimed.
