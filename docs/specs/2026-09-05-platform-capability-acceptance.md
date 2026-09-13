# Platform Capability Acceptance: First Slice

Status: `verified`

Contract: `target`

Owner: core outbound values; existing feature, player and messaging services;
test-only transport harness.

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md)
Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

## Problem

IncomingMessageRef carries a sequence and a timezone-aware reply deadline, but
ReplyContext cannot preserve them. SendResult cannot carry a transport trace ID.
Existing outbound tests primarily simulate permissive OneBot delivery. They do
not prove that the shared services retain opaque identities under restricted
capabilities.

## Goal And Ownership

Keep OutboundMessenger as the only transport port. Extend its existing values
with reply metadata and trace diagnostics, without a second delivery interface.
Share deadline validation with inbound values. ReplyContext.from_message targets
the current inbound message, never the message it quoted. Deadline enforcement
belongs to the adapter, with an injected clock in tests.

The test-only FakeOfficialPlatform implements this port with configurable
capabilities, deterministic reply expiry, simulated binary uploads and injected
errors. Its limits/error codes are synthetic test policy, NOT claims about QQ's
current API. Nothing is installed into production or requires credentials.

## Scope And Non-Goals

- Exercise actual help/about contracts and FeatureService with opaque actors.
- Exercise PlayerIdResolver with the real namespaced SQLite binding repository,
  including separate groups with the same member ID.
- Exercise ProactiveMessageDelivery with real persisted subscriptions, denied
  proactive delivery, supported text/images, and diagnostic errors.
- Keep OneBot behavior unchanged; no production configuration/schema migration.
- Do not claim real official API compatibility, image rendering correctness,
  complete live player lookup, AI portability or a real OneBot smoke test.
- Do not modify upstream repositories, production databases or TOML.

## Acceptance Tests

- [x] Reply conversion preserves current message ID, sequence and deadline;
  naive deadlines fail for both inbound and outbound values.
- [x] Restricted reply expiry/capabilities fail explicitly without dropping parts;
  binary images are uploaded once per delivered part by the simulator.
- [x] Real catalog/feature filtering works with opaque identities and manager
  roles without leaking permissions across platform or group.
- [x] Persisted bindings resolve independently by platform, actor kind and scope.
- [x] Real subscription filtering skips only the selected destination; denied
  proactive delivery never invokes send; failures retain trace/error diagnostics.
- [x] OneBot regressions, full pytest, Ruff, BasedPyright, compileall and diff check.

## Migration And Rollback

No persistent migration or compatibility read path. Reverting the code slice
restores the previous optional outbound value contract without touching data.

## Evidence And Progress

2026-09-05: explicitly fetched origin and fast-forward-only pulled local main;
main and origin/main remain f19c7089. No merge into the architecture branch.

Program: 3/8 verified phases; overall ETA unavailable pending remaining gates.
Verification on 2026-09-05:

- Outbound/capability/proactive/OneBot focused tests: 33 passed.
- `uv run pytest -q --basetemp=.test-tmp/platform-capability-full`:
  1589 passed, 87 pre-existing dependency warnings, 88.08 seconds.
- `uv run ruff check ironsbot tests`: passed.
- `uv run basedpyright`: 0 errors, 0 warnings, 0 notes.
- `uv run python -m compileall -q ironsbot` and `git diff --check`: passed.

Current slice: verified; no remaining work within this slice. The helper is
test-only, binary content is synthetic (not a rendered Seer fixture), and the
new reply factory is not a claim that every existing OneBot reply workflow has
been migrated to the outbound port.
Phase 7 remains incomplete until full Seer/AI workflows, security/dependency
audit and real OneBot smoke testing satisfy the ledger gates.

## Seer Query Content Contract (2026-09-12)

Contract: `target`; OneBot group mentions and direct/selected query behavior are
`baseline` invariants. `QueryReply.to_outbound()` now owns the shared ordered
content: leading text, image (or the explicit image error), then description.
Incomplete but deliverable replies keep their available content. Empty payloads
are rejected by the existing outbound value validation, not sent as success.

The query plugin no longer constructs this content with SAA. It uses the existing
OneBot outbound renderer and matcher send/finish context; the new-content menu
reuses this same query delivery entry. No compatibility wrapper, production
adapter, dependency, schema, or configuration is added. This does not migrate
all other direct matcher replies to `OutboundMessenger`.

Tests exercise the actual TypeQueryService and calculator, converting its normal
type text and image result through the same production content method. Restricted
capabilities reject unsupported images and expired replies before upload. The
repository and image renderer remain controlled test doubles: this is service
flow and content-boundary acceptance, not a native PNG rendering, live database,
game protocol, or QQ Official API acceptance claim.

OneBot regression tests retain group-only mentions, direct finish/selected send,
image base64 transport, part ordering and explicit image failure text. Existing
menu reservation tests continue to run. Stage count remains 4/8.

Verification: 59 focused tests; private extension 43 passed; full public suite
2920 passed with 319 existing dependency warnings (118.14 seconds). Full Ruff,
BasedPyright (0 errors/warnings), compileall and diff check passed. The initial
full run exposed an unchanged rank test fixture returning repeated players and
non-descending scores for every page. Commit `1823e03c` fixes that fixture without
changing the expected requests, final rank or production consistency checks;
all 25 rank-limit tests and the subsequent full run passed.

## Native Published Type Query Smoke (2026-09-12)

The existing type-query test module now has an opt-in native smoke test. Set
`IRONSBOT_RENDER_RELEASE` to a built SeerAPI SQLite file; optionally set
`IRONSBOT_RENDER_FONTCONFIG` to the host's fontconfig file. These are test inputs,
not runtime TOML fields. Without a release input it explicitly skips rather than
substituting an invented database or marking native rendering verified.

```sh
uv run pytest -q tests/test_seer_type_query_service.py -k native_published \
  --basetemp=.test-tmp/native-release-smoke
```

It uses DatabaseManager's read-only file import and real release validation,
build_seer_rendering_components, the actual type repository/calculator,
immutable published HTTP assets, RenderCoordinator and htmlkit. A temporary empty
cache guarantees the first call performs SQL, HTTP and exactly one render; the
second produces identical PNG bytes with no additional SQL, HTTP or renderer
call. The PNG is decoded for dimensions and color diversity and retained under
the pytest temporary directory. The same bytes pass through QueryReply, simulated
official upload and the real OneBot message encoder without corruption. Task
ownership and database cleanup run in finally, including failure paths.

Executed against the existing local `v5-release-acceptance-fixed` producer
artifact: 1 native test passed in 22.57 seconds (two existing ORM warnings).
The output is an 848x3453 grass-type matchup PNG; visual inspection confirmed
the title, attack/defense sections, icons and multiplier rows render without
overlap. The ordinary focused suite passed 46 tests with one explicitly skipped
native test when the release environment variable was absent.

This replaces a one-off probe for this path with a reproducible gate. It is not
an actual official platform upload, live player/game query, Linux image smoke,
nor proof of completeness for pet, pool or lineup asset scopes. No production
code, dependencies, database or configuration was changed; 4/8 remains unchanged.

Final fresh-cache rerun with the native test enabled: all 26 type-query tests
passed in 13.33 seconds. Full Ruff, targeted BasedPyright and diff check passed.
Source release SHA-256 remains
`1ef66a0039326f1f2a8d2ca523af02e6e44da7134f3edff5ce15e0d385119845`.
No full-suite rerun is claimed for this test/documentation-only checkpoint.

## Specialized Seer Result Contract (2026-09-13)

Weekly-preview image results, peak query results and Autocard entries now expose the same
platform-neutral `to_outbound()` boundary as ordinary `QueryReply` values. The
service result owns image/text ordering and MIME type; Autocard also owns its
primary/additional-image selection. OneBot only renders the result at its
adapter boundary. The obsolete raw-bytes branch in the weekly preview adapter
was removed because the service has no such producer.

The fake official capability suite accepts preview, peak image, peak text and
Autocard remote-image results through the real `OutboundMessenger` protocol,
including upload counting. This expands non-QQ Phase 7 evidence without
inventing OpenID-to-QQ mapping, direct-mention support or account-binding
behavior. Those capabilities remain deferred until a target API can represent
them.
