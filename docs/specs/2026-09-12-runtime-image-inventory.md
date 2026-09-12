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
- The five deployer-specific sendpic PNGs total about 14 MB. Move their command
  ownership to explicit TOML local/CNB configuration, then remove the packaged
  files and the private `builtin` backend; retain required htmlkit/SAA dependencies.
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

## Locked Runtime Dependency Audit

Target: the existing release workflow must audit the frozen production dependency
set before registry login or image publication, without installing audit tooling
in the runtime image. Export hashed requirements with no development dependencies
or root project, then run pinned pip-audit 2.10.1 under Python 3.10. Collection
errors, advisory failures and export failures stop release; no automatic fixes,
ignored advisories or continue-on-error. Preserve requirements and JSON evidence
even when auditing fails. This is a Python package advisory gate, not a scan of
Debian packages, native libraries, secrets or exploitability.

The first actual local scan found h2 4.3.0 affected by
[GHSA-6hr6-w5qg-qmwg](https://github.com/python-hyper/h2/security/advisories/GHSA-6hr6-w5qg-qmwg).
The advisory service returned the same ID twice; it is one distinct advisory,
not two different defects. Upgrade h2 to 4.4.1; its metadata requires hpack>=4.2,
so hpack moves from 4.1.0 to 4.2.0. No other locked version changes. This does not
claim IronsBot exposes the advisory's HTTP/2-to-HTTP/1 request-smuggling scenario.

Actual frozen sync installed both versions. The post-upgrade local scan of 58
dependencies under the default Windows interpreter reported no known advisories
and no skipped packages. Marker-dependent Linux dependencies are only covered
when the release gate runs on Linux; a local scan is not proof that an image was
built or audited. The Docker Desktop Linux engine pipe remains absent, verified
again this turn; no daemon start, image measurement or remote release was done.

Workflow shell tests exercise success, export failure and audit failure, preserving
the nonzero status and report. They mock the command execution, unlike the local
advisory scan above. Focused packaging/architecture tests: 39 passed. Private
native-enabled regressions after sync: 43 passed. Stage count remains 4/8.

The actual pinned tool was also run with Python 3.10 and the exact hashed-input
flags used by CI: 59 applicable Windows dependencies, zero known advisories and
zero skipped packages. Advisory HTTP-cache decode warnings caused network
refetches, not ignored packages. Full public suite after the two dependency
updates: 2924 passed, 319 existing warnings, 131.85 seconds. Full Ruff,
BasedPyright, compileall and diff check passed. Local main remains 55a39fd1;
no fetch, merge, production edit or push was performed.

## Candidate Runtime Smoke Gate

The release workflow now builds and loads a local candidate before either
registry login or publication. In a network-isolated container it runs the real
entrypoint with a read-only copy of `config.example.toml`, changing only
`check_on_startup` to false so the check does not depend on a mounted Docker
socket. The command imports NoneBot and `seerapi_models` and parses the complete
configuration. Only after that succeeds does the workflow log in and publish
from the same context, labels and BuildKit cache. The final runtime image gains
no files or dependencies from this gate.

Workflow and startup-preflight tests pass 21 cases; Ruff and diff checks pass.
This is a verified CI contract, not evidence that the candidate has already run:
the local Docker 29.5.2 client has no connected Linux daemon. A future release
run must supply the actual container result and size artifacts before Phase 7
can claim Linux runtime acceptance.

## Frozen Runtime Footprint Audit

The frozen `--no-dev` export contains 59 packages. Installing that exact export
into an isolated Python 3.10 Windows environment occupies about 64.49 MiB in
`site-packages`; this is diagnostic evidence rather than a Linux image-size
measurement. The largest runtime packages are htmlkit's native rendering core
(about 16.06 MiB), Pillow (about 13.96 MiB), SQLAlchemy (about 8.37 MiB),
Pydantic Core (about 5.37 MiB), Pygments (about 4.27 MiB), and resvg-py (about
1.89 MiB).

Every direct runtime dependency has a current production owner: NoneBot and the
OneBot adapter provide the active platform runtime; FastAPI/httpx provide the
configured drivers; htmlkit, Pillow and resvg-py implement image rendering;
Hishel implements the shared HTTP cache; APScheduler owns scheduled work; SAA
encodes outgoing image messages; qrcode generates Bilibili login QR images;
and seerapi-models/SQLAlchemy read the published database. Therefore this audit
removes no direct dependency. Deleting any of these packages would remove an
active feature or merely move the same dependency behind an implicit import.

Development-only `nodejs_wheel`, BasedPyright, pytest, Ruff and audit tooling do
not occur in the frozen production export. The Dockerfile already exports with
`--no-dev`, installs only that wheel set, and removes pip/setuptools/wheel from
the final stage. The five deployer-specific sendpic PNGs and their hard-coded
defaults have now been removed, reducing the application payload by about
13.65 MiB. Fixed-image support remains available through explicit TOML `local`
or `cnb` commands; the old private `builtin` backend is intentionally rejected.

Pinned Seer render assets remain owned by the producer publication. The consumer
derives both GitHub Raw and jsDelivr URLs from the exact repository and commit
revision published by SeerAPI, trying the CDN only after Raw fails. It never
embeds those official assets in the application image and never falls back to a
mutable branch. The two native render cases previously blocked by Raw network
failures pass with this route (`2 passed`, real release database and HTML render).

The image previously retained Source Han Sans SC Regular and Bold, about
31.94 MiB unpacked, from a 90.77 MiB archive. The same official 2.005R release
provides the Simplified Chinese CN subset: Regular and Bold total about
16.21 MiB. The Docker build now extracts exactly those two files, reducing the
projected font layer payload by about 15.73 MiB while retaining both weights and
the Chinese glyph family used by every template. Candidate smoke resolves both
styles through fontconfig and requires distinct files. The upstream
`LICENSE.txt` is copied to `/usr/share/doc/source-han-sans/LICENSE.txt`.

Together with externalized sendpic assets, the projected application-plus-font
payload reduction is about 29.38 MiB. This remains a source/archive calculation;
only the digest-pinned Linux CI inventory may report the actual image delta.
