# Runtime Image Inventory

Status: `verified` (published Linux candidate measured; live QQ acceptance pending)

Target: bounded runtime packaging with verifiable size evidence. Owner:
Dockerfile/build context and the existing release measurement step.

## Current Evidence (2026-09-14)

Workflow `34852716528` succeeded for `e0aaeb12`, including dependency audit,
Linux build, offline entrypoint smoke, directory budgets and publication.
The published image measures 259748177 bytes expanded on the CI engine;
the fixed baseline measures 259738853 bytes on that engine (+9324 bytes).
Runtime directories: `/app` 4480 KiB, site-packages 105948 KiB, fonts 19452 KiB.
The exact digest and remaining connection/message gates are recorded in
[QQ Official Live Acceptance](2026-09-14-qq-official-live-acceptance.md).
This is not a compressed download-size measurement or a real QQ delivery test.

The dated findings below retain their original evidence boundaries. Statements
that publication was pending describe those earlier checkpoints, not the current
candidate. Do not compare sizes from different Docker engines as a growth delta.

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
or root project, then run pinned pip-audit 2.10.1 under Python 3.11. Collection
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

The frozen `--no-dev` export originally contained 59 packages. Installing that
exact export into an isolated Python 3.10 Windows environment occupied about
64.49 MiB in `site-packages`; this is diagnostic evidence rather than a Linux
image-size measurement. The largest runtime packages were htmlkit's native
rendering core (about 16.06 MiB), Pillow (about 13.96 MiB), SQLAlchemy (about
8.37 MiB), Pydantic Core (about 5.37 MiB), and Pygments (about 4.27 MiB).

Every remaining direct runtime dependency has a current production owner:
NoneBot and the OneBot adapter provide the active platform runtime;
FastAPI/httpx provide the configured drivers; htmlkit and Pillow implement image
rendering; Hishel implements the shared HTTP cache; APScheduler owns scheduled
work; qrcode generates Bilibili login QR images; and
seerapi-models/SQLAlchemy read the published database.

The audit later proved that `resvg-py` had no production or private-extension
caller: its only public wrapper was itself unused. The wrapper and direct
dependency were removed rather than shipping an approximately 1.17 MiB Linux
wheel solely because it had existed in an earlier rendering experiment.
After removal, the full suite passed (`3207 passed, 7 skipped`), together with
Ruff, BasedPyright, compileall and the frozen dependency export check. Actual
Linux image size remains a release-run measurement, not a projected claim.

The same ownership check later removed
`nonebot-plugin-send-anything-anywhere`. Four OneBot adapters used it only to
wrap image bytes or URLs, while IronsBot already owns its outbound message
contract and OneBot renderer. Those adapters now construct native OneBot image
segments at the platform boundary. This also removes the transitive `filetype`
and `StrEnum` distributions without changing service contracts or moving
platform types inward. The Windows environment shed roughly 0.5 MiB of package
payload; the exact Linux image delta remains pending candidate measurement.

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

The previously floating `python:3.10` and `python:3.10-slim` tags had moved to
Debian Trixie without a repository change. Both stages now explicitly select
Bookworm (`python:3.10-bookworm` and `python:3.10-slim-bookworm`), preventing a
future Debian release switch from changing ABI and size implicitly. The tags
remain patch-updatable for base security fixes; the release workflow records the
resolved final digest and layer inventory for every publication. At the audited
2026-09-13 manifests, the amd64 compressed slim base is about 45.05 MiB versus
45.75 MiB for Trixie, but the 0.70 MiB difference is secondary to matching the
builder and runtime ABI.

The candidate image now has a pre-publication directory budget gate. It records
the same isolated `du` inventory used for diagnosis and rejects `/app` above
8 MiB, Python `site-packages` above 128 MiB, or `/usr/share/fonts` above 24 MiB.
These are intentionally separate budgets: deployer content cannot hide inside
the application layer, a dependency increase cannot be mistaken for font growth,
and font changes must preserve the explicit two-weight contract. Evidence is
uploaded even when the gate fails, and registry login remains after the gate.
Shell tests cover each exact boundary and each independent overflow; actual Linux
values still require the first candidate CI run.

## Release Action Runtime Refresh

The publication workflows now use one current first-party action contract per
owner: checkout, setup-python, upload-artifact and build-push use v7;
setup-buildx and login use v4; metadata uses v6. This removes the Docker release
workflow's older Node action runtimes without adding anything to the application
image. A repository-wide workflow test rejects a future downgrade or mixed major
for these action owners. Third-party release and Docker Hub description actions
remain independently versioned and are not inferred from this matrix.

This is a workflow compatibility update, not candidate execution evidence. The
same Linux candidate smoke, frozen dependency audit, three directory budgets and
digest-pinned publication inventory remain the acceptance gates.

Verification on 2026-09-13: all workflow YAML files parsed successfully; the
Docker release workflow suite passed 17 tests; Ruff and `git diff --check`
passed. The exact frozen Python 3.10 audit covered 59 runtime distributions and
reported zero known vulnerabilities and zero skipped distributions. Repeated
advisory-cache decode warnings caused network refetches and did not suppress
audit input or findings. No workflow was dispatched and no image was published.

## Fork-Aware Render Metadata

Candidate and published images now receive the current repository URL as a Docker
build argument. The runtime injects it into every HTML render and scopes final
render-cache keys by the same value. Five Seer templates no longer package a
hard-coded upstream URL; source runs without build metadata omit the link rather
than guessing ownership. This adds no asset or dependency to the image.

Focused metadata, cache, workflow and render tests passed 55 cases. Ruff and diff
checks passed. At that checkpoint the Linux Docker daemon was unavailable; the
later real candidate evidence below supersedes only that environment limitation.

## Real Linux Candidate Evidence (2026-09-13)

Docker Desktop's Linux/amd64 Engine 29.5.2 was started and the exact public
commit `93bd3aac21e8ee23e6cfc7c108024073b1fae5ce` was built with the release
Dockerfile. The network-isolated entrypoint smoke resolved distinct regular and
bold Source Han Sans CN files, loaded the example configuration, and imported
NoneBot and `seerapi_models` successfully.

The first real build exposed nested local `__pycache__` directories in the
context: `/app` was 9384 KiB and would have failed the 8192 KiB gate. Recursive
Docker ignore rules removed every `.pyc`; the rebuilt candidate measured
4220 KiB for `/app`, 104644 KiB for site-packages, and 19452 KiB for fonts.
All three runtime budgets now pass without raising a limit.

The rebuilt candidate image ID is `sha256:7ffd8c985a7c...`; Docker reports
98,861,824 bytes (94.28 MiB). On the same engine, pulled GHCR `latest` digest
`sha256:4677ca61fe55...` reports 425,224,471 bytes (405.53 MiB), a reduction of
326,362,647 bytes (311.24 MiB). These are real local Docker measurements, not
source projections. A published digest-pinned CI artifact remains pending, so
this evidence does not claim publication or real platform acceptance.

The application entry point explicitly selects the pure-Python `asyncio`, `h11`
and `websockets-sansio` implementations. Runtime dependencies therefore declare
FastAPI, Uvicorn and WebSockets directly instead of installing NoneBot's FastAPI
extra, which pulled Uvicorn's unused standard accelerators. The frozen lock no
longer contains `httptools`, `uvloop` or `watchfiles`. A full host process smoke
reached Uvicorn's listening state and shut down cleanly with this dependency set.
The exact post-change Linux image size remains to be remeasured by the published
candidate workflow; the earlier local Linux measurement remains the latest
digest-comparable evidence.

The post-change frozen production export was also audited with the release
workflow's pinned `pip-audit==2.10.1`, `--require-hashes`, `--disable-pip` and
`--strict` options. All 53 resolved runtime distributions were inspected and no
known vulnerability was reported. The generated requirements and JSON report
were temporary local evidence; the workflow remains responsible for retaining
the corresponding artifact for each published candidate.

## Python 3.11 Runtime Baseline (2026-09-13)

The application, both Docker stages, the release workflow and BasedPyright now
share Python 3.11 as the minimum runtime. The Dockerfile exposes one
`PYTHON_VERSION` build argument and keeps both stages on Bookworm, so the builder
and runtime cannot silently drift to different Python or Debian releases. Python
3.10's conditional `tomli` compatibility path and the no-longer-required
`backports-asyncio-runner` lock entry were removed. Ruff intentionally retains
its `py310` syntax-style target for now: raising that target would trigger a
separate repository-wide modernization and is not required to execute on 3.11.

An isolated CPython 3.11.15 environment completed the full suite with 3241
passed, 7 skipped and 2 warnings. The focused packaging/configuration suite
passed 90 tests, BasedPyright reported zero errors, and the exact hashed audit
covered 52 applicable distributions with zero known vulnerabilities. The compact
frozen runtime export contained 152 lines with neither `tomli` nor
`backports-asyncio-runner`. The lock update removed substantially more metadata
than it added. These results prove the source and dependency baseline; they do
not establish a new image-size delta. The published candidate workflow must
still produce the Linux directory inventory and digest evidence.

The release workflow now declares that minor version once and passes it to
setup-python, the pinned audit tool, both Docker builds and the candidate
container. The network-isolated smoke reads `sys.version_info` inside the built
image and rejects a mismatch before registry credentials are used. Workflow
parsing, shell quoting, 25 release-workflow tests, Ruff and BasedPyright passed.
The local Docker daemon did not answer a bounded version probe, so this improves
the executable publication gate but does not claim a new local image run.
