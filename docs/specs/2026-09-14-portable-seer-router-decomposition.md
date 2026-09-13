# Portable Seer Router Decomposition

Status: completed

## Goal

Keep the platform-neutral command router below the repository's structural
limit without moving unrelated responsibilities into a generic utility module.
The router should select an authorized command and normalize its result; Seer
query parsing and operation construction belong to a dedicated Seer composition
module.

## Contract

- `PortableCommandRouter` remains the only platform-neutral dispatcher used by
  QQ Official.
- `build_portable_seer_operations()` builds the existing data, team, rank-help,
  pet, mintmark, equipment, type, battle-effect and peak operations.
- Existing domain services, parsers, query sessions and outbound values are
  reused. No command syntax, feature policy, reply text or session ownership is
  changed.
- The extraction must not add dependencies, configuration, databases, assets or
  Docker layers.

## Acceptance

- Existing portable Seer and QQ Official tests pass unchanged.
- Full Ruff, BasedPyright, compileall and structural line-limit checks pass.
- `portable_commands.py` has clear headroom below 800 lines.
- The implementation and verification evidence are committed separately when
  practical.

## Evidence

- `portable_commands.py` decreased from 739 to 468 lines.
- `portable_seer_commands.py` owns the extracted Seer operation composition in
  320 lines.
- Targeted portable/Seer verification: `142 passed, 7 skipped`.
- Full verification: `3363 passed, 7 skipped`; Ruff, BasedPyright (zero errors),
  compileall, structural checks and diff checks passed.
- No runtime dependency, configuration field, database, asset or image layer was
  added.
