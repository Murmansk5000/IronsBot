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

## Private Extension Build Context

The private Dockerfile explicitly copies pyproject.toml, but .dockerignore
excluded that file. Remove that exclusion; retain and copy the root LICENSE
alongside the manifest and extension package. Exclude local virtual environments,
credentials, test output, fontconfig cache and uv.lock from the context. Test and
font caches are also ignored by Git; the existing untracked uv.lock is untouched.
This fixes a required build input, not measured image size. The existing private
manifest tests now check source existence, COPY instructions and these explicit
ignore entries (2 passed). They do not implement a full Dockerignore parser.

Docker version was attempted on this host; the dockerDesktopLinuxEngine named
pipe is absent. No image build or size measurement is claimed. Private runtime
tests, including opt-in native lineup rendering, passed 42 cases before this
packaging-only change. No daemon was started and no remote build was triggered.
The final private suite including the added packaging case passed 43 tests in
3.37 seconds, with native rendering enabled. Private commit: 4a3d007.

## Retired HTTP Client Dependency

The public runtime and private extension have no imports of the `seerapi` HTTP
client. They consume `seerapi-models` and published SQLite through repositories.
Remove only the client from pyproject and regenerate the lock offline: no other
locked version changed. Frozen production export still retains the models,
SQLModel, HTTP clients and render dependencies. The removed wheel is only 14388
bytes compressed; this is boundary cleanup, not a large measured image saving.

`uv sync --frozen --offline` actually removed the client, and find_spec confirms
it is absent while seerapi_models remains importable. Exact sync also removed
three pre-existing untracked environment extras (localstore, nonestorage and
qrcode-terminal); those were not in the lock and are not claimed as savings from
this change. Private native-enabled tests pass 43 cases in this exact environment.
The existing AST architecture test now prevents runtime imports of the retired
client; its 19 tests pass. Full type checking reports zero errors/warnings, and
Ruff passes. Full public suite result is recorded after completion below.

Public full suite: 2834 passed, 319 existing dependency warnings, 121.85 seconds.
The newly added AST guard was collected in the separate 19-test architecture
run, not retroactively counted in that full run. Compileall and diff checks
passed. Docker daemon/image execution is still unverified; this checkpoint does
not complete Phase 4/7 or prove production rollout.
