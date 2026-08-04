# IronsBot 程序设计要求与演进目标

Status: current engineering requirements and long-term target

This document is the single normative source for architecture work. It
separates the current transition state from the target state so a description
of today's implementation is never permission to extend a design that the
target removes. It is not permission to rewrite unrelated code in one change:
every migration must be a small, independently verifiable change that
preserves current OneBot behaviour unless an explicit product decision says
otherwise.

The current production shape is NoneBot2 + OneBot v11 + NapCat, usually in
Docker/Unraid. The long-term target is to support three deployment shapes with
one business core:

1. OneBot only;
2. QQ Official Bot only; and
3. OneBot and QQ Official Bot together.

QQ Official Bot support is a future boundary, not a currently enabled
integration. Do not add an empty official-bot plugin, fake adapters, official
credentials, or speculative compatibility code before a concrete feature needs
them.

## Architecture Status

The following distinctions are mandatory during the migration:

- **Target contracts** are the designs all new cross-feature work must move
  toward. New code must not create another competing contract for the same
  responsibility.
- **Transitional contracts** describe code that exists today only so it can be
  safely migrated. They may be maintained for correctness, but must not gain
  new feature ownership, optional fields, or another consumer when a target
  contract is available.
- **One-time migration tools** may read legacy data while transforming it, but
  normal runtime code must use exactly one schema and one read path after that
  migration succeeds.

### Normative Reading Rules

This document contains both a description of the running application and the
architecture it is moving toward. They have different force:

1. A **target** rule is mandatory for new cross-feature design, even when the
   current application has not reached that state yet.
2. A **transition** rule names an existing bridge only to constrain and remove
   it. It never grants permission to extend that bridge with new ownership.
3. A **baseline** rule freezes visible behaviour while its implementation is
   moved. It does not prescribe the package, class, or registry that must own
   that behaviour later.
4. When a current implementation and a target rule appear to disagree, the
   target rule decides new design. The current implementation may only receive
   a minimal correctness fix or an explicitly scoped migration step.

Every architecture change must label the contract it changes as **target**,
**transition**, or **baseline** in its plan and commit description. A document
or review must not call a transitional mechanism the "single" or "unique"
contract without the qualifier "current bootstrap bridge". This specifically
prevents a retired central application registry or any future bootstrap adapter
from being mistaken for the plugin, command, or lifecycle contract.

Current transition items are `MatcherRegistry`, the private-extension bootstrap
adapter, the legacy OneBot `MessageTarget` / `OneBotDelivery` send chain, and
the renderer data lookups listed in the Phase 0 guard below. They keep the
current OneBot application runnable; they are not the architecture that new
cross-feature work should target. Phase 2 has completed built-in plugin
discovery through the standard NoneBot manifest. `PluginContribution` is the
current plugin-local way to submit explicit runtime contributions; it is not an
application registry or a catch-all authority for every plugin concern. The
remaining Phase 2 work replaces `MatcherRegistry` with a matcher factory and
removes the temporary private-extension adapter. Phase 4 removes
renderer-owned persistence lookups. No new subsystem may be built on those
transition items merely because they already exist.

The authoritative long-term ownership is therefore:

- `PluginMetadata` owns plugin identity and static metadata;
- `PluginContribution` owns a plugin's explicit runtime contributions;
- `CommandCatalog` and `CommandContract` own direct-command semantics;
- the feature-policy service owns permission decisions; and
- `ApplicationLifecycle` owns application lifecycle and background task
  ownership.

The temporary private-extension adapter owns none of those target
responsibilities. It only adapts configured external private contributions
until that extension boundary has a standard declarative replacement.

### Plugin Contract Terminology

Plugin-related terms name separate responsibilities. They must not be collapsed
into a fictional "single plugin contract" in code, plans, reviews, or future
architecture work:

| Term | Owns | Does not own |
| --- | --- | --- |
| `PluginMetadata` | Static plugin identity and NoneBot metadata | Matchers, commands, lifecycle policy, or feature decisions |
| `PluginContribution` | A plugin's explicit runtime contributions submitted during installation | A central plugin registry, command semantics, or cross-plugin policy |
| `CommandCatalog` / `CommandContract` | Direct command syntax, examples, parsing ownership, help, poke candidates, and AI command claims | Passive notices, scheduled jobs, or matcher construction |
| Feature-policy service | Whether an actor or conversation may use a feature | Plugin discovery or command parsing |
| `ApplicationLifecycle` | Process lifecycle, owned tasks, and startup/shutdown ordering | Plugin metadata or user-command semantics |

`PluginDefinition` is a retired historical type. It may be mentioned only when
documenting a completed migration or inspecting old Git history; new code,
interfaces, tests, and diagrams must not introduce it or treat it as a current
contract. When a responsibility needs an authority, name the narrow authority
from the table rather than saying that a plugin, manifest, or contribution
object owns everything.

### Architecture Documentation Merge Rule

Architecture-document merge conflicts are resolved by responsibility, not by
choosing whichever wording is easiest to merge. A conflict is not evidence
that both designs must survive in the running application.

When resolving a conflict, preserve these parts in order:

1. the current normative target and its named authority;
2. the verified current bridge, explicitly marked `transition` when it still
   exists; and
3. the completion condition that deletes the bridge.

Discard an older unqualified claim that a retired registry, a bootstrap
adapter, or `PluginDefinition` is the application's single plugin contract.
Do not recreate an old code type, compatibility wrapper, or second registry
merely to make prose from two branches agree. If both branches contain useful
facts, rewrite them into the target/transition/completion form above and add
or update the matching transition-inventory row in the same change.

Git reports a text conflict because two branches touched nearby lines; it does
not establish an architectural conflict. The verified code state and this
document's target authority decide the resolution.

### Transition Inventory And Admission Rule

The following table is the working inventory for architecture tasks. It
prevents a currently working bridge from being treated as a design option for
new code. A row marked **transition** may receive a narrowly scoped bug fix,
or lose one consumer in a migration. It must not receive a new service,
feature, persistence schema, or policy decision.

| Responsibility | Status | Current safe boundary | Required direction before new ownership |
| --- | --- | --- | --- |
| Plugin runtime contribution submission | target | Plugin-local `PluginContribution` during installation | Extend a plugin's explicit contribution only; never recreate an application registry or let contributions replace the command catalog. |
| `ActorRef`, `ConversationRef`, `OutboundMessage`, `OutboundMessenger` | target | Core values and explicit ports | Services and new notification workflows use these values directly. |
| Team-audit reminders | target reference | `TeamAuditService` plus a OneBot adapter | Reuse this shape for event-triggered delivery. |
| Administrator notices | target reference with adapter bridge | `AdminNoticeService` plus `AdminNoticeSender` | Keep OneBot routing, queues and CQ rendering in `integrations.onebot`. |
| Activity reminders | target reference with adapter bridge | `ActivityService` plus `ActivityReminderSender` | Keep subscription and rate-limit semantics in the target integration. |
| OneBot `MessageTarget` / `OneBotDelivery` | transition | Only inside legacy callers and `integrations.onebot` adapters | A service must first receive a typed recipient and sender port; then move its legacy call into the adapter. |
| OneBot reference resolution and numeric QQ configuration | transition | Configuration parsing and application composition | Convert configuration values to opaque refs before a service receives them. |
| Lucky-skin-window delivery | target reference with adapter bridge | `LuckySkinWindowService` plus `OneBotLuckySkinWindowNotificationSender` | Reuse typed actor ownership; keep OneBot subscription and daily-hint policy in the adapter. |
| Team-resource subscription delivery | target reference with adapter bridge | `TeamResourceService` plus `TeamResourceNoticeSender` | Keep numeric QQ configuration, mention conversion and `OneBotDelivery` in `integrations.onebot.team_resource`. |
| Renderer-owned data lookup and association guessing | transition | Existing renderer code only for correctness fixes | Move data preparation to repositories/build facts, then make renderers consume view models. |
| Private-extension bootstrap adapter | transition | External configured contribution adaptation only | Move one declared responsibility at a time to a standard declarative extension contract, then delete it from the adapter. |

Before adding cross-feature code, locate its row in this table. If it has no
row, add a target responsibility with an owner and a testable boundary first.
If it is a transition row, the proposed diff must make the row smaller or
strictly preserve it; adding a second caller is a design failure even if the
tests pass.

## Engineering Principles

New behaviour must be designed as a reusable domain capability before a
single-plugin patch is added. When multiple features need the same kind of
input, identity, command description, persistence, rate control, notification,
or rendering, create one small, typed interface at its real ownership boundary
and make the features use it.

The following rules are mandatory:

- Plugins adapt transport events and send results. They do not own reusable
  parsing, persistence, HTTP calls, scheduling, retries, or business policy.
- Services own cohesive use cases and depend on explicit ports, never on
  NoneBot, OneBot event classes, matchers, or global application state.
- Renderers receive view models and assets. They do not execute raw SQL,
  create repositories, or guess business associations.
- Integrations implement ports and contain protocol, filesystem, HTTP,
  scheduler, and database details. They do not decide user-facing policy.
- Configuration, IDs, links, account UIDs, tokens, personal group names, and
  deployment-specific behaviour must not be hard-coded in business modules.
- A compatibility change is a one-time migration tool, not a permanent
  dual-read path. Do not add old-function wrappers or fallback schemas unless
  an explicit migration plan, removal condition, and test require them.
- Do not introduce a service locator, global registry, Redis, Celery,
  microservices, a universal repository, or another broad framework merely to
  anticipate future scale.
- Preserve intentionally cohesive low-level modules such as binary/SWF
  parsers and protocol schedulers. Splitting files only to make a tree look
  symmetrical is not an architectural improvement.

## Change Design Gate

Before changing production code, the implementation plan must answer these
questions in writing. A small bug fix may answer them in one short paragraph;
a migration must answer each one explicitly.

1. **Semantic owner:** What domain capability owns the behaviour? The answer
   must not be "this plugin already handles something similar."
2. **Reusable input/output:** Which existing typed value, port, resolver, or
   repository is reused? If none exists, why is a new narrow interface the
   correct boundary?
3. **Adapter boundary:** Which code is transport adaptation, and which code is
   platform-neutral policy? Adapter event types must stop at the plugin or
   adapter boundary.
4. **Persistence boundary:** Which lifecycle-owned store owns the data? State
   must be keyed by the correct actor/conversation/entity identity rather than
   by a feature-local convenience key.
5. **Migration boundary:** Does the change replace an old path? If so, name
   the one-time tool, rollback point, removal condition, and test. Runtime
   dual-read or dual-write is not an acceptable default.
6. **User contract:** Which existing command, reply, rate limit, permission,
   or scheduled behaviour is preserved or intentionally changed?
7. **Proof:** Which focused tests, architecture tests, static checks, and
   smoke checks demonstrate the result?

Do not solve a repeated need by adding a feature-specific parser, storage
file, background loop, command keyword list, or renderer query. First look
for the real shared abstraction. A new abstraction is justified only when it
has a clear domain owner and removes meaningful duplication; it is not
justified as a speculative framework.

## Code Size And Cohesion

Production Python modules under `ironsbot/` have a hard maximum of **800
physical lines**. The check is enforced by
`tests/test_structure_size_hygiene.py` through
`MAX_PRODUCTION_PYTHON_LINES = 800`; a module with 801 lines fails the test.

This is a review and design constraint, not an invitation to scatter one
cohesive responsibility across arbitrary files. Before a module approaches the
limit, its owner must decide whether it contains independent responsibilities
that can be extracted along a real boundary, for example:

- command parsing versus a domain service;
- repository/storage code versus business policy;
- transport adaptation versus user-content rendering; or
- a reusable resolver versus one feature's command handler.

If a file is naturally large because it is a generated artifact, a declarative
data table, a template, a test fixture, or a cohesive low-level parser, keep it
cohesive and document a narrowly scoped exception before changing the test.
Never evade the limit by moving unrelated helpers into a catch-all `utils`,
`shared`, or `common` module. New code should normally be kept comfortably
below the limit rather than treating 800 as a target.

## Long-Term Multi-Platform Boundary

Business services must become platform-neutral before a second transport is
introduced. The target core identities are deliberately opaque and must not
assume a QQ numeric ID:

```python
Platform = Literal["onebot", "qq_official"]

@dataclass(frozen=True, slots=True)
class ActorRef:
    platform: Platform
    id: str
    kind: Literal["user", "member"] = "user"
    scope_id: str | None = None

@dataclass(frozen=True, slots=True)
class ConversationRef:
    platform: Platform
    kind: Literal["private", "group", "channel", "guild"]
    id: str
```

Future services should receive typed input/output values such as
`IncomingMessageRef`, `OutboundMessage`, `RenderedImage`, and explicit
delivery ports. They must not receive `GroupMessageEvent`, `Bot`, CQ segments,
or adapter-specific session objects. Transport adapters own conversion in both
directions.

Phase 1 begins with `core.platform` and `core.outbound`: `ActorRef`,
`ConversationRef`, `IncomingMessageRef`, message parts, `OutboundMessage`,
`ReplyContext`, `SendResult`, `DeliveryCapabilities`, and
`OutboundMessenger`. They use opaque nonempty string IDs. The current
OneBot-only `MessageTarget` remains a Phase 3 transition type until its full
call chain can be replaced in one direction; no new platform-neutral service
may depend on it. `integrations.onebot.outbound_messenger.OneBotOutboundMessenger`
is the Phase 1 edge adapter for the new port: it translates text, images,
mentions and reply contexts only after a `ConversationRef` has been routed to
a OneBot bot. Existing `OneBotDelivery` callers still use `MessageTarget`
until the Phase 3 one-direction migration; new services must use the
platform-neutral port instead.

`services.team.audit.TeamAuditService` is the first complete reference use
case for this boundary. Its workflow, reminder store, scheduler jobs, and
outbound messages use `ConversationRef`, `ActorRef`, and `OutboundMessenger`.
The OneBot plugin converts notice events at the edge, while
`integrations.onebot.team_audit` owns configured feature policy, bot routing,
and group-member probes. Future transport migrations should follow this shape
rather than passing numeric IDs or adapter bot instances into a service.

`services.messaging.admin_notice.AdminNoticeService` is the reference use case
for platform-neutral operational delivery. It selects `ActorRef` and
`ConversationRef` recipients through feature policy and sends an
`OutboundMessage` through an explicit `AdminNoticeSender` port. The OneBot
adapter may delegate to the legacy `OneBotDelivery` chain while that chain is
being retired, because the adapter is the only place that knows numeric QQ
targets, routing, subscriptions, queueing, and rate limits. A new notification
service must use this shape or a narrower domain port; it must not import
`MessageTarget`, `OneBotDelivery`, a NoneBot `Bot`, or CQ message types.

`services.activity.ActivityService` applies the same ownership to scheduled
activity reminders: the service creates typed recipients and an
`OutboundMessage`, while `integrations.onebot.activity` preserves the current
OneBot subscription, advertisement, routing, queue, and rate-limit semantics.
The current push-preference SQLite schema still stores OneBot target IDs; its
conversion is confined to composition until the later identity-state migration.

Lucky-skin-window notification delivery now follows this rule: its service
owns `ActorRef`-scoped account, binding, cache and watch-preference policy;
the OneBot adapter owns numeric QQ conversion, unsubscription, daily-hint
deduplication and `OneBotDelivery`. Team-resource subscriptions use the same
shape: `TeamResourceService` owns typed conversations, actors, subscriptions
and low-resource policy, while `OneBotTeamResourceNoticeSender` owns QQ number
conversion, mentions and legacy delivery. The remaining messaging scheduler
migrations are ordered by semantic overlap, not file size. Each task must
extract a typed service-side port and move the corresponding OneBot
`MessageTarget` call into `integrations.onebot`; it must not add another
platform-neutral wrapper around `MessageTarget`. This keeps current
subscription, queue, rate-limit and failure semantics available while reducing
the old chain one domain at a time.

The eventual composition is:

```text
core values and ports
        ^
        |
services and use cases
        ^
        |
integrations (SQLite, HTTP, Seer data, render assets)
        ^                         ^
        |                         |
plugins/onebot              plugins/qq_official (future)
        ^                         ^
        +----------- app composition -----------+
```

`plugins/onebot` and future `plugins/qq_official` may share services but never
import each other's adapter/event types. A feature may be enabled for one
platform, both, or neither; an adapter must not emulate an unavailable action
by silently falling back to a OneBot-only operation.

When QQ Official Bot work actually begins, use `nonebot-adapter-qq` as the
official adapter. Do not run a separate `botpy.Client` alongside NoneBot for
the same official bot. Official-specific protocol and asset code belongs in a
dedicated integration/adapter boundary, created only with the first real
official feature.

## QQ Official Capability And Safety Requirements

QQ Official Bot delivery is constrained by official permissions, intents,
reply windows, proactive-message rules, quotas, and the platform's control of
personal bots. Future official work must therefore use explicit capabilities
instead of assuming that a OneBot operation exists everywhere:

```python
@dataclass(frozen=True, slots=True)
class DeliveryCapabilities:
    can_reply_to_event: bool
    can_send_proactively: bool
    can_mention_members: bool
    supports_group_context: bool
    supports_private_context: bool
    supports_images: bool
```

- Check capabilities and official policy before scheduling or delivering a
  message; fail closed with observable logs when an action is unavailable.
- Model official reply deadlines and proactive-delivery eligibility explicitly;
  never hide an expired official reply behind a generic retry loop.
- Keep OneBot numeric QQ IDs separate from official open IDs. There is no
  implicit cross-platform identity mapping.
- Store official targets with their platform and scope. Never treat an official
  identifier as a QQ number or reuse a OneBot group alias for it.
- Treat mentions, callbacks, message references, and media as adapter-specific
  capabilities. A command that needs an unavailable capability must degrade
  safely, not guess.
- Record a trace ID, platform, capability decision, and official error code for
  failed deliveries so platform restrictions can be distinguished from product
  bugs.

## Reusable Input And Command Contracts

Input semantics must have one owner. Future refactors should converge on these
reusable contracts rather than adding feature-local regexes:

- `MessageInputContext` parses new text, direct mentions, reply metadata,
  actor, and conversation once. Quoted content never contributes aliases or
  mentions.
- Entity aliases use a typed lookup/resolution interface. Pets, mintmarks,
  mintmark series, gems, Bilibili accounts, and player identities keep their
  own storage and normalization rules but expose the same result shape.
- Every command parameter whose semantic type is a Seer player ID accepts the
  shared player-ID resolver: a numeric ID, a permitted player alias, or one
  direct `@` target whose current binding can be resolved. Multiple mentions,
  mixed ambiguous targets, and unbound targets return a clear error. Binding a
  player ID binds the resolved target to the command sender, never to the
  mentioned user.
- `CommandCatalog`/`CommandContract` is the authority for a command's example,
  description, scope, feature, audience, parser ownership, help visibility,
  poke candidates, and AI command-claim check. Do not maintain separate
  keyword lists for help, poke hints, AI exclusions, and rank protection.
- Configuration-generated commands, selection menus, and fixed commands must
  use the same contract. Passive notices and scheduled jobs are not commands.

The retired central registry is a migration-history concern, not a runtime
bridge. All built-in contributions now come from their own manifest-loaded
plugin packages. The remaining private-extension bootstrap adapter is not the
long-term owner of command semantics, feature policy, help content, or
lifecycle design. Do not create a second parallel manifest merely for the
future target. Each private-extension migration moves one responsibility to
its declarative replacement and deletes it from this adapter in the same work
item.

## Contract Ownership During Migration

Every responsibility has exactly one target authority. A transitional adapter
may temporarily invoke that authority, but it must not redefine or duplicate
its data. New work must extend the target authority in this table rather than
adding fields or side registries to a temporary bootstrap adapter.

| Responsibility | Current bridge | Target authority | Migration completion |
| --- | --- | --- | --- |
| Plugin discovery and loading | Standard TOML loads declared third-party prerequisites and every built-in local package; a temporary bootstrap adapts configured private extensions only | `[tool.nonebot.plugins]` + `nonebot.load_from_toml` with one local package per plugin | No private extension bootstrap adapter remains. |
| Plugin identity and static metadata | `PluginMetadata` in each built-in top-level plugin package | `PluginMetadata` in each top-level plugin package | Private extensions expose equivalent declarative metadata without importing application composition code. |
| Matchers, command contracts, jobs, lifecycle contributions | `MatcherRegistry` + plugin-local `PluginContribution` | `PluginContribution` created in a scoped install context | Contributions are explicit and testable without reflective lookup. |
| Command syntax, help, poke hints, AI command claims | Mixed registry/help constants during transition | `CommandCatalog` + `CommandContract` | Every direct user command is registered once; no parallel keyword lists remain. |
| Feature visibility and audience | Current feature service plus plugin bridge | Feature policy service consumed by contracts | Plugins declare requirements but do not own policy evaluation. |

The first verified migrations are `ironsbot.plugins.onebot.about`,
`ironsbot.plugins.onebot.activity`, `ironsbot.plugins.onebot.bilibili`,
`ironsbot.plugins.onebot.messaging`,
`ironsbot.plugins.onebot.ai` / `.intent`,
`ironsbot.plugins.onebot.operations.server_status`,
`ironsbot.plugins.onebot.operations.docker_update`,
`ironsbot.plugins.onebot.operations.db_sync`,
`ironsbot.plugins.onebot.help` / `.hint`, `ironsbot.plugins.onebot.sendpic`,
`ironsbot.plugins.onebot.fire_manual_ad`, `ironsbot.plugins.onebot.seer.rank_help`,
`ironsbot.plugins.onebot.pet_config`,
`ironsbot.plugins.onebot.seer.query`,
`ironsbot.plugins.onebot.lucky_skin_window`, `ironsbot.plugins.onebot.team_audit`,
`ironsbot.plugins.onebot.team_resource`, and the
`ironsbot.plugins.onebot.startup_notice`,
`ironsbot.plugins.onebot.headless_seer_notice`,
`ironsbot.plugins.onebot.headless_seer_runtime`,
`ironsbot.plugins.onebot.scheduler`, and the messaging `blacklist`, `meeting`,
`red_packet`, and `onebot.scheduled_restart` modules: the manifest loads them
directly, and each package supplies its own metadata and contribution. Seer rank
refresh job registration is application service code in
`services.seer.rank_refresh_scheduler`, not a OneBot event adapter. The standard
manifest directly discovers the required third-party runtime
plugins (`nonebot_plugin_apscheduler`, `nonebot_plugin_localstore`,
`nonebot_plugin_htmlkit`, and `nonebot_plugin_saa`).
`fire_manual_ad` owns its passive feature policy contribution; `onebot.sendpic`,
`meeting`, `rank_help`, and `onebot.team_resource` also own the command descriptors
for the matchers they install.
Every subsequent private-extension migration follows that pattern and removes
its bootstrap adapter responsibility in the same change.

The target system must not retain an adapter merely to keep the old registry
alive. A phase may use a short-lived migration tool, but ordinary runtime must
have one path and one authority after that phase is complete.

## Data, Rendering, And Storage Direction

Persistent data remains organised by lifecycle and access pattern, not by a
desire to minimise the number of SQLite files. Large Seer content databases,
rank facts, player samples, line-up blobs, AI history, and Bilibili history
stay isolated when their contention, retention, or size differs. Small QQ
user/group state belongs to shared state stores with namespaced migrations.

Future data work follows these rules:

- `seerapi` performs data extraction, normalization, schema validation, SWF to
  PNG conversion, and deterministic association building at build time.
- IronsBot reads published facts through repositories; it does not repeat
  expensive association guessing or SWF conversion while replying to users.
- All Seer image reads pass through one asset store: a bounded in-memory LRU,
  integrity-checked disk cache, singleflight request coalescing, bounded
  upstream concurrency, and short-lived negative caching only for 404/410.
  Renderer and query features use the same image port rather than creating
  feature-specific download caches.
- Native HTML rendering passes through one `RenderCoordinator`. It is fixed at
  one native render at a time and has an explicit timeout; callers cannot add
  feature-local HTMLKit semaphores or background render tasks.
- Disposable rendered images use the same atomic, checksum-verified byte-store
  primitive as Seer assets. Their cache key includes the published data version,
  render category and payload, plus a startup fingerprint of the rendering
  implementation and templates; a renderer change therefore cannot reuse a
  stale image from a mounted cache directory.
- Official effect relationships retain provenance and ambiguity records. The
  runtime renderer uses a prepared `PetRenderViewModel` and never tries to
  infer a new association from free text.
- SQLite changes use explicit versions and transactional migrations. Shared
  state databases use namespaced migration records; large independent stores
  may use their own schema version.
- Platform identity migrations are offline, one-time transformations. They use
  independent platform/kind/id/scope columns, a temporary database, a
  timestamped backup, integrity and cardinality checks, then atomic
  replacement. The table-by-table contract is in
  [docs/platform-state-migration.md](docs/platform-state-migration.md).
- A normal runtime repository persists only `ActorRef` or `ConversationRef`
  columns. OneBot integers may be adapted at a transport-facing wrapper while
  Phase 1 is in progress, but they must not be a database column, a primary
  key, or the persistence contract of a core service. Adding a second schema,
  a lazy legacy import, or a dual-read branch is prohibited; use the offline
  migration instead.
- A downloaded data release is validated for schema version and required tables
  before atomic replacement. Incompatible data disables only the affected
  feature and notifies administrators without removing the data-update path.

### Cross-Repository Data Publication Contract

When a user-facing Seer capability depends on extracted official data, its
truth must be produced and versioned by the data repository rather than
reconstructed inside IronsBot. A change that crosses `seerapi`,
`seerapi-models`, and IronsBot follows this fixed order:

1. `seerapi` defines the normalized fact table, source provenance, ambiguity
   record, schema version, and build-time validation.
2. `seerapi-models` exposes the published fact through an ORM/repository
   contract; it must not expose raw extraction tables as a shortcut for
   renderers.
3. A real data release is built and checked for required tables, deterministic
   rows, assets, and integrity before a consumer is allowed to rely on it.
4. IronsBot consumes the published view through `integrations.seer_data` and
   passes a render-ready view model to its renderer.

The consuming repository must not add a second association resolver, raw SWF
conversion fallback, best-effort text guesser, or legacy-table read merely to
cover a missing data release. Missing required facts are a release/schema
failure with observable diagnostics and a recoverable `/更新数据` path. A
one-time migration may transform old local data before deployment, but normal
runtime reads one published schema only.

## Gradual Migration Plan

The following order is directional. A phase starts only when it has a concrete
product need; it must leave the repository cleaner than it found it.

1. **Protect current behaviour.** Add characterization tests, dependency
   checks, and small shared interfaces where a real duplication already exists.
2. **Normalize core values and ports.** Move platform-neutral identities,
   messages, command contracts, and capability checks out of adapter code.
3. **Move business use cases behind services.** Keep plugins thin and inject
   repositories, delivery ports, schedulers, and renderers from composition.
4. **Make OneBot one adapter implementation.** Migrate existing event and
   delivery code without changing ordinary command behaviour.
5. **Prepare data and assets.** Publish deterministic Seer facts and render
   assets before exposing them through a new transport.
6. **Add QQ Official Bot only for a real feature.** Implement its adapter,
   capabilities, policy checks, tests, and observability in the same change.

Each phase must be independently reviewable, have migration/rollback guidance
where persistent data changes, and avoid leaving an old and new runtime path
active indefinitely.

## Work Execution And Progress Reporting

Architecture work is performed as a hierarchy of **program -> phase -> task**.
The tracked plan is the source of execution status, not a substitute for code
or tests. Every active implementation update must report both levels:

```text
Program  [████░░░░░░] 40%  estimated remaining: 6 h
Phase 2  [███░░░░░░░] 30%  estimated remaining: 90 min
Task     [██████░░░░] 60%  estimated remaining: 25 min
```

The percentages are estimates based on completed, verifiable tasks, not a
claim of linear certainty. Re-estimate when investigation changes scope;
state why the estimate changed. Do not hide a blocked task behind a broad
percentage. Report the blocker, the affected phase, what was tried, and the
next safe action.

At the start of each task, record its target contract, touched repositories,
acceptance checks, rollback strategy, and whether it changes public behaviour.
At completion, report the changed files, tests actually run, remaining risks,
and the next task. A task may be committed only when it leaves the branch
coherent and independently testable; unrelated worktree changes remain
unstaged.

The practical checklist and review template live in
[docs/engineering-workflow.md](docs/engineering-workflow.md).

## Target Package Layout

```text
ironsbot/
  __main__.py
  app/
    bootstrap.py
    composition.py
    file_logging.py
    lifecycle.py
  config/
    loader.py
    models/
      settings.py
      ai.py
      activity.py
      messaging.py
      operations.py
      seer.py
  core/
    bilibili.py
    binary.py
    commands.py
    features.py
    help.py
    messaging.py
    selection.py
    tasks.py
    time.py
  integrations/
    db_sync/
    docker/
    headless_seer/
    htmlkit.py
    http/
    onebot/
    scheduler/
    seer_data/
    storage/
  services/
    activity/
    ai/
    bilibili/
    messaging/
    operations/
    seer/
    team/
  plugins/
    about/
    activity/
    ai/
    bilibili/
    help/
    messaging/
    operations/
    seer/
    sendpic/
    team/
  runtime/
    conversations.py
    feature_policy.py
    message_input.py
    matchers.py
    onebot_context.py
    params.py
    permissions.py
    plugins.py
    priority.py
    prompts.py
    replies.py
    rules.py
```

The target package has no `shared`, `utils`, `plugin_catalog`, custom
reflection-based plugin-discovery module, or command cooldown manifest. This
does not prohibit the standard NoneBot TOML plugin manifest, nor the
configuration field that selects one declared manifest profile. The selector is
declarative configuration only: it never becomes a second discovery list or a
runtime registry. Code currently owned by those locations moves to its actual
owner:

- pure values and policy rules belong to `core`;
- application use cases belong to `services`;
- framework, network, filesystem, scheduler, and database code belongs to
  `integrations`;
- NoneBot event adaptation belongs to `plugins`;
- process construction and resource lifetime belong to `app`;
- the internal plugin and matcher contracts belong to `runtime`.

## Dependency Direction

Internal imports follow this graph:

```text
core
  ^
  +---- config
  +---- services
          ^
          +---- integrations
          +---- plugins ---- runtime
                    ^          ^
                    +---- app -+
                         |
                         +---- config
                         +---- integrations
                         +---- services
```

The graph is interpreted as "may depend on":

- `core` imports no other IronsBot layer.
- `config` imports only `core`.
- `services` imports `core` and service modules. A service defines the
  protocols for infrastructure it needs.
- `integrations` imports `core`, configuration value types, and service
  protocols. It never imports plugins or the application composition root.
- `runtime` imports `core` and NoneBot, but no concrete service or integration.
- `plugins` import `core`, `runtime`, and services. They never import config
  loaders or concrete integrations.
- `app` is the composition root and may import every layer.

No module outside `app` loads configuration, resolves a global service, or
creates a process-wide infrastructure client.

## Application Composition

`app.composition.build_application(settings)` is the only composition root.
Standard NoneBot TOML selects and loads the configured plugin profile first;
scoped manifest-loaded built-in contributions are then passed to composition.
The temporary private-extension adapter may add configured external
contributions, but it is not a second discovery path. Composition:

1. creates infrastructure resources;
2. creates repositories and service objects with explicit constructor
   dependencies;
3. validates manifest contributions and freezes the command catalog;
4. builds the application lifecycle;
5. returns one `Application` object.

The `Application` object owns all process-wide mutable resources. In
particular, it owns:

- cached and uncached HTTP clients;
- the headless Seer client;
- the Seer data engine registry;
- the scheduler facade and registered jobs;
- OneBot routing and delivery;
- SQLite repositories;
- command cooldown and outbound rate limit state;
- background tasks and their cancellation.

There are no module-level client, manager, repository, registry, or service
singletons. Pure immutable constants and stateless functions remain valid
module-level values.

## Lifecycle

`app.lifecycle.ApplicationLifecycle` is the only lifecycle owner.

Bootstrap registers exactly these driver hooks:

- `startup`: start resources, migrate stores, start configured services, and
  install scheduled jobs;
- `shutdown`: stop jobs and background tasks, then close resources in reverse
  ownership order;
- `bot_connect`: record the connected OneBot instance, run readiness checks,
  and deliver startup notices once for that connection;
- `bot_disconnect`: remove the disconnected OneBot instance from routing.

Plugins do not call `get_driver()` and do not register driver hooks. Runtime
modules do not keep `{"registered": ...}` dictionaries. Idempotence belongs to
the lifecycle state machine.

Background tasks are created through the lifecycle task owner. Every task has
a name, an owner, cancellation on shutdown, and observable failure logging.

## Temporary Private Extension Bootstrap

`PluginContribution` is the runtime contribution contract. Every built-in
plugin is a top-level manifest-loaded package and contributes itself during the
scoped loading window. `ironsbot.plugins.onebot.bootstrap` is now limited to
adapting configured private extensions; it is not a built-in plugin registry,
command directory, or second discovery mechanism. Do not add built-in feature
ownership, command metadata, help metadata, lifecycle concepts, or plugin
families to this adapter.

The runtime contribution contract is:

```python
@dataclass(frozen=True, slots=True)
class PluginContribution:
    id: str
    features: frozenset[Feature]
    help: HelpEntry | None
    commands: tuple[CommandDescriptor, ...] = ()
    install: Callable[[MatcherRegistry], None] | None = None
    hooks: PluginHooks = PluginHooks()
```

The standard manifest discovers built-in packages directly. The private
bootstrap can append only configured external contributions during the scoped
loading window. It must not become an additional authority over the target
contracts:

- plugin installation order;
- feature ownership;
- legacy help grouping, ordering, and visibility;
- legacy lifecycle contributions.

Those are not permissions to add a second source of truth. The private
extension migration must move each responsibility to the target authority in
the ownership table and then delete this adapter.

The standard NoneBot TOML manifest is the sole built-in plugin discovery
source. A configuration value may select a named, declared manifest profile
such as `full` or `core`, but it cannot list modules itself. There is no
parallel application manifest, help layout map, feature-to-module map, runtime
setup string list, or reflective `module:function` lookup.

Every message matcher is created through `runtime.matchers.MatcherRegistry`.
Creation requires one explicit command policy:

- a stable semantic command id;
- a resolver for a dynamic semantic command id; or
- a documented passive/conversation exemption.

The registry installs command cooldown admission when the matcher is created.
There is no second pass that imports matcher objects by string reference.

## Message Input Routing

`core.message_input.MessageInputContext` is the platform-neutral record of a
newly received message. The current `runtime.message_input` is its OneBot
adapter: it converts current-message IDs and direct member mentions into
`IncomingMessageRef` and `ActorRef` values before applying this fixed routing
order:

1. reply;
2. direct bot mention;
3. direct ordinary-member mention;
4. direct text without a mention.

The quoted message body and its mentions never participate in this decision.
Mentions newly sent after a quote still follow the declared strategy: for
example, a quoted `收集@成员` is a valid `member_target_command`, while an
`@成员` contained in the quoted message itself is ignored.
Matchers declare one input strategy instead of inspecting message segments:

- `explicit_command` accepts direct commands and replies, except a current
  ordinary-member mention;
- `member_target_command` and `member_targets_command` are the only command
  strategies allowed to consume current ordinary-member mentions;
- `bot_mention` is reserved for direct AI and bot-mention-block handling;
- `natural_language` accepts only direct text with no mention.

An anchored prompt keeps the direct owner path and may additionally allow a
different group member to reply to the bot's latest menu message. The prompt
framework identifies that input as a shared menu reply; business code may
derive a new caller-owned conversation from the stored menu target, but never
reassigns or closes the original owner's conversation.

The Phase 2 replacement uses `[tool.nonebot.plugins]` and
`nonebot.load_from_toml`, with one real top-level package per plugin. Every
plugin exposes `PluginMetadata`; plugin-side loading creates a scoped
`PluginInstallContext` only while contributions are registered. It is not a
service locator and must not be read by services or renderers. A
`PluginContribution` explicitly owns matchers, command contracts, lifecycle
callbacks, and scheduled jobs. `CommandCatalog` consumes the contributed
contracts and is the only command-description authority. The replacement
becomes the only authority; the bridge and its reflective discovery are then
deleted instead of being kept as a compatibility path.

## Service Boundaries

A plugin is a transport adapter. It may:

- match a NoneBot event;
- convert the event into typed command input and actor/target context;
- call one service method;
- convert a typed result into OneBot output;
- finish or continue a conversation.

A plugin does not:

- open SQLite;
- perform HTTP requests;
- select notification recipients;
- coordinate caches;
- own retry, refresh, or scheduling policy;
- read the global configuration;
- contain reusable parsing or formatting business rules.

A service owns one use case or cohesive domain capability. Services accept
configuration values and ports explicitly. Services return domain values or
rendered user content without importing NoneBot event, matcher, or driver
types.

Infrastructure implements service ports. It does not decide feature policy,
permissions, notification audience, command text, or user-facing wording.

The principal service groups are:

- `ai`: chat, memory, mention protection, intent/action execution, and AI
  failure reporting;
- `messaging`: notification targeting, subscriptions, delivery policy,
  command cooldown, and outbound limits;
- `seer`: player, team, rank, data query, rendering, and cache coordination;
- `activity`: catalog, reminder planning, and delivery requests;
- `bilibili`: account state, polling, preferences, and delivery requests;
- `team`: team resource subscriptions and team audit workflow;
- `operations`: startup, data refresh, Docker update, restart, and headless
  state reporting.

## Configuration

`config.models.settings.Settings` is the only root configuration model.
`config.loader.load_settings()` is the only loader and is called exactly once
by bootstrap.

The authoritative TOML top-level schema is:

```toml
[bot]
[paths]
[features]
[ai]
[activity]
[bilibili]
[messaging]
[seer]
[operations]
```

Nested models may live in separate files, but they are reachable only through
`Settings`. Every model uses `extra="forbid"`. The TOML loader reports and
ignores unknown fields; invalid known values, unknown features, unknown account
references, incomplete actions, and invalid section names fail startup with
their exact configuration path.

The loader has no cache, cleanup pass, fallback schema, or automatic mutation.
Missing TOML is a deployment concern: the
container entrypoint may copy the authoritative example before startup, but
the loader only reads and validates.

Non-secret behavior and deployment values live in TOML. Environment variables
are limited to the configuration location and secrets:

```text
APP_CONFIG_PATH
ONEBOT_ACCESS_TOKEN
AI_KEY
SEER_PASSWORD_<player_id>
SENDPIC_CNB_TOKEN
GITHUB_WORKFLOW_TOKEN
```

The loader injects `SEER_PASSWORD_<player_id>` for configured Seer accounts
that need a login. No component reads `os.environ`, NoneBot driver config, or
dotenv files after bootstrap. Services and plugins receive credentials only
through `Settings` and the account registry.

`config.example.toml` and `.env.example` are the only tracked configuration
templates. Development and production use the same schema. Docker Compose,
Unraid, README files, and tests use only these names.

## Storage

Services define repository protocols next to the domain that consumes them.
Concrete implementations live in `integrations.storage`.

`integrations.storage.sqlite.SqliteDatabase` is the only SQLite connection and
migration entry point. It owns:

- path creation;
- WAL and synchronous pragmas;
- transaction boundaries;
- row factory policy;
- schema version reads and writes;
- ordered, atomic migrations.

Every persistent SQLite file has a migration plan with monotonically
increasing integer versions. Opening a repository applies pending migrations
once. A migration either commits completely or leaves the prior version
unchanged. Existing unversioned databases are treated as version 0 and are
upgraded by tested migrations.

Repositories are created once by the composition root and injected into
services. No request handler constructs a store or runs `CREATE TABLE`.

The target preserves existing persistent file locations unless a tested
one-time file migration is included. Disposable render and HTTP caches may be
recreated.

## Public Command Contract

The refactor preserves the current user-visible command language and response
semantics for:

- help and about;
- Seer player, binding, shortcut, team, pet, mintmark, equipment, type,
  peak, autocard, rank, cache, and data commands;
- AI chat, mention protection, and intent actions;
- scheduled text, activity, Bilibili, and subscription management;
- team resource and team audit workflows;
- sendpic;
- server status, data refresh, restart, and Docker update operations.

The following behavioral invariants are frozen:

- quoted commands read only newly sent text; direct bot mentions remain
  reserved for AI or bot-mention-block handling;
- a group member can use a shared menu only by exactly replying to the latest
  bot menu anchor, never through a bare selection or an old menu;
- group and private feature policy remains explicit;
- superuser bypass follows the configured policy;
- group owner/admin/superuser checks remain consistent;
- command cooldown uses stable semantic command ids;
- every TOML value denoting a OneBot user, group, or @ target resolves through
  the shared user/group reference service; plugins do not parse those aliases
  independently;
- `blacklist` is an explicit target-policy feature and always suppresses the
  matching conversation before AI, rate controls, menus, or business matchers;
- proactive group messages use the same outbound limit and bot routing as
  replies;
- `admin_notice` targets only superusers and groups explicitly granted the
  `admin_notice` feature;
- AI, headless, startup, Docker, rendering, and data refresh failures never
  leak to ordinary groups;
- user-facing help does not expose internal feature or module names;
- rank position, range, page, player, and score queries retain their current
  command syntax and tie handling.

Changes to configuration names are intentional and have no compatibility
aliases. Changes to public command text require an explicit product decision
and characterization test update; architecture work alone is not such a
decision.

## Phase 0 Baseline Guards

The Phase 0 guards deliberately protect behaviour while identifying the
remaining target-state work:

- `tests/test_layer_import_hygiene.py` enforces the existing dependency
  direction, prohibits framework imports from services, and limits lifecycle,
  task, SQLite, and scheduler ownership.
- `tests/test_plugin_import_hygiene.py` proves plugin installation performs no
  filesystem, network, task, or SQLite side effect.
- `tests/test_structure_size_hygiene.py` enforces the 800-line production
  module limit.
- `tests/test_architecture_target_hygiene.py` forbids renderer persistence
  dependencies and adapter transport imports from `core` and `services`.

The Phase 4 renderer persistence allowlist is empty. A new renderer must
receive a detached view model and its assets; it cannot acquire a new database
or transport exception.

## Current OneBot Behaviour Baseline

This snapshot records what Phase 1 onward must preserve while changing its
implementation. It is deliberately an ownership map, not a second command
reference for users:

- **Ingress and commands:** NoneBot + OneBot v11 events enter through
  `MessageInputContext`; `CommandCatalog` and `CommandDescriptor` currently
  drive help, poke candidates, access checks, and direct-command ownership.
  `MatcherRegistry` constructs the current matchers and records their command
  policy. Prompts and selection menus keep their own anchored session state.
- **Permissions and identity:** the current feature policy resolves configured
  group and user aliases, group/private feature access, group-manager roles,
  and superuser bypass. The OneBot configuration boundary still owns numeric
  QQ values, but policy and new services expose `ActorRef` and
  `ConversationRef`; a second platform must not consume the numeric values.
  Seer player IDs already use a shared resolver for numeric IDs, aliases, one
  direct mention, and the caller's default binding.
- **Replies and proactive delivery:** group and private replies, scheduled
  pushes, activity notices, Bilibili delivery, team-resource notices, startup
  notices, and admin notices use OneBot routing and outbound rate limiting.
  Group cooldown and priority-queue behaviour are frozen by characterization
  tests; a known timing-sensitive priority test is monitored rather than
  hidden.
- **State and subscriptions:** QQ user/group state is consolidated in
  `data/state/qq_state.sqlite`; runtime task state is in
  `data/state/runtime_state.sqlite`. `ironsbot.state_migration` is the
  one-time tool that creates and validates these stores. Bindings, query
  quotas, push preferences, display limits, and subscriptions stay logically
  separate tables even when they share a file.
- **Large content and caches:** Seer data, aliases, player samples, rank facts,
  lineups, Bilibili history, and AI memory remain separate because their size,
  retention, or contention is different. They are not candidates for the
  platform-identity migration.
- **Lifecycle:** `ApplicationLifecycle` owns startup, shutdown, OneBot
  connect/disconnect hooks, scheduler registration, and background-task
  cancellation. Built-in plugins register contributions through the scoped
  manifest-loading context and do not open infrastructure resources at import
  time.

Phase 0 observations to resolve in later phases are also explicit: the
current `pyproject.toml` adapter declaration names OneBot v12 while the runtime
uses OneBot v11; Phase 2 corrects that as part of the standard NoneBot manifest
migration. The completed Phase 4 pet-info path loads a detached snapshot in
`integrations.seer_data`, while the type-matchup path loads shared image assets
there; both prepare immutable render documents in pure presenters before HTML
rendering. Their renderer modules do not perform ORM, SQL, HTTP, filesystem,
or association inference. Existing Bandit findings with no high-severity result
remain tracked rather than silently suppressed.

## Enforcement

The repository must include tests that prove:

- the dependency graph above;
- one settings loader and no global settings access;
- no built-in bootstrap registry or parallel command directory; private
  extension adaptation must not acquire target-contract ownership;
- all internal message matchers have an explicit command policy;
- only bootstrap registers driver lifecycle hooks;
- only `SqliteDatabase` calls `sqlite3.connect`;
- services and integrations do not import NoneBot transport types except where
  an integration explicitly implements a NoneBot adapter;
- plugin import/installation performs no network, filesystem, task, or
  database side effects;
- configuration examples, Compose, Unraid, and documentation validate against
  the target schema.

Acceptance additionally requires the full test suite, Ruff, BasedPyright,
compileall, repository static checks, Bandit, dependency audit, and a real
bootstrap/shutdown smoke test.
