# Runtime Image Inventory

Status: `verified` (packaging/workflow contract only; actual image run pending)

Target: bounded runtime packaging with verifiable size evidence. Owner:
Dockerfile/build context and the existing release measurement step.

## Findings And Changes

- Wheel bind mounts, no-dev dependency export, explicit runtime copies and
  packaging-tool removal already exist. Do not add a second build pipeline.
- Root LICENSE/LICENSING files are excluded and not copied. Retain them explicitly
  in the runtime, alongside existing third-party notices. Slimming must not strip
  distribution notices. This does not claim a complete licensing audit.
- The five largest bundled PNGs total about 14 MB and remain used assets. Do not
  delete them or required htmlkit/SAA dependencies without a replacement path.
- Extend the existing digest-pinned image-size artifact with a runtime directory
  inventory (KiB). Run only du in a network-disabled disposable container;
  never start the bot or read deployment configuration. This distinguishes code,
  fonts and installed dependencies from retained build layers.
- No dependency, runtime API, TOML or producer changes. No new diagnostic module.

## Validation

Existing workflow shell tests verify exact digest, invocation isolation and
artifact linkage; Docker packaging checks cover retained licenses and existing
exclusions. Focused pytest, Ruff and diff checks. Actual image measurement awaits
a build-capable environment/release, not substituted by mocked output.

Rollback: code revert. Program 4/8; estimate 20-40 minutes for this item, overall
ETA unestablished. Focused packaging/workflow tests: 16 passed in 1.97 seconds.
Ruff and diff checks passed. No image size reduction or live image execution is
claimed; these tests mock Docker and exercise the release shell contract.
