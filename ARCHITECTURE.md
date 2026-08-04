# IronsBot 程序设计要求与演进目标

Status: current engineering requirements and long-term target

This document defines the architectural rules that new code must follow and
the direction in which existing code will be migrated. It is not permission to
rewrite unrelated code in one change: every migration must be a small,
independently verifiable change that preserves current OneBot behaviour unless
an explicit product decision says otherwise.

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
    user_id: str

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

The current `PluginDefinition` registry remains the OneBot-era installation
contract until a tested migration replaces it. Do not create a second parallel
manifest merely for the future target; when migration begins, the new manifest
must become the one authority for the responsibilities it owns.

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
- Official effect relationships retain provenance and ambiguity records. The
  runtime renderer uses a prepared `PetRenderViewModel` and never tries to
  infer a new association from free text.
- SQLite changes use explicit versions and transactional migrations. Shared
  state databases use namespaced migration records; large independent stores
  may use their own schema version.
- A downloaded data release is validated for schema version and required tables
  before atomic replacement. Incompatible data disables only the affected
  feature and notifies administrators without removing the data-update path.

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

## Package Layout

```text
ironsbot/
  __main__.py
  app/
    bootstrap.py
    composition.py
    file_logging.py
    lifecycle.py
    registry.py
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

The final package has no `shared`, `utils`, `plugin_catalog`,
`plugin_manifest`, or command cooldown manifest. Code currently owned by those
locations moves to its actual owner:

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

`app.composition.build_application(settings)` is the only composition root. It:

1. creates infrastructure resources;
2. creates repositories and service objects with explicit constructor
   dependencies;
3. builds the immutable plugin registry;
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

## Plugin Contract

All internal plugins use one contract:

```python
@dataclass(frozen=True, slots=True)
class PluginDefinition:
    id: str
    features: frozenset[Feature]
    help: HelpEntry | None
    install: Callable[[MatcherRegistry], None] | None = None
    hooks: PluginHooks = PluginHooks()
```

`app.registry.build_plugin_registry(...)` returns one ordered tuple of
`PluginDefinition` values. The tuple is the authority for:

- plugin installation order;
- feature ownership;
- help grouping, ordering, and visibility;
- lifecycle contributions.

There is no parallel module manifest, help layout map, feature-to-module map,
runtime setup string list, or reflective `module:function` lookup.

Every message matcher is created through `runtime.matchers.MatcherRegistry`.
Creation requires one explicit command policy:

- a stable semantic command id;
- a resolver for a dynamic semantic command id; or
- a documented passive/conversation exemption.

The registry installs command cooldown admission when the matcher is created.
There is no second pass that imports matcher objects by string reference.

## Message Input Routing

`runtime.message_input.MessageInputContext` is the only interpreter for a
newly received OneBot message. It records the new text, reply metadata, a bot
mention, and ordinary member mentions once, then classifies the message in
this fixed order:

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

External NoneBot dependencies are represented by definitions in the same
ordered registry. Their `install` callable may delegate to NoneBot's external
plugin loader, but no other code loads plugins. Lifecycle-only definitions
leave `install` unset instead of using a no-op callable.

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

## Enforcement

The repository must include tests that prove:

- the dependency graph above;
- one settings loader and no global settings access;
- one plugin registry and no reflective internal plugin/runtime references;
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
