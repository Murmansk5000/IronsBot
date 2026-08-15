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

Current transition items are the OneBot-only configuration compilers and the
renderer data lookups listed in the Phase 0 guard below. They keep the current
OneBot application runnable; they are not the architecture that new
cross-feature work should target. Within Phase 2,
the standard NoneBot manifest discovery and the `MatcherFactory` construction
boundary are verified sub-items; the phase itself remains in progress until
its remaining bridge and ownership conditions are met. `PluginContribution` is
the current plugin-local way to submit explicit runtime contributions; it is
not an application registry or a catch-all authority for every plugin concern.
Phase 4 removes renderer-owned persistence lookups. No new subsystem may be
built on those transition items merely because they already exist.

The authoritative long-term ownership is therefore:

- `PluginMetadata` owns plugin identity and static metadata;
- `PluginContribution` owns a plugin's explicit runtime contributions;
- `core.command_catalog.CommandCatalog` and the target `CommandContract` own direct-command
  semantics;
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
| `core.command_catalog.CommandCatalog` / target `CommandContract` | Direct command syntax, examples, parsing ownership, help, poke candidates, and AI command claims | Passive notices, scheduled jobs, or matcher construction |
| Feature-policy service | Whether an actor or conversation may use a feature | Plugin discovery or command parsing |
| `ApplicationLifecycle` | Process lifecycle, owned tasks, and startup/shutdown ordering | Plugin metadata or user-command semantics |

`PluginDefinition` is a retired historical type. It may be mentioned only when
documenting a completed migration or inspecting old Git history; new code,
interfaces, tests, and diagrams must not introduce it or treat it as a current
contract. When a responsibility needs an authority, name the narrow authority
from the table rather than saying that a plugin, manifest, or contribution
object owns everything.

**Verified baseline (2026-08):** the production Python packages contain no
`PluginDefinition` implementation or import. The name is retained only in
historical/architecture prose and in the architecture guard's retired-name
check. A branch that reintroduces it, or a document that calls it the current
installation contract, is stale and must be resolved toward the contract table
above rather than merged as an alternative design.

### Current Command-Contract Boundary

`core.command_catalog.CommandContract` is the current runtime representation
for every direct command. It is not a second authority and must not grow a
parallel catalog, matcher registry, or AI-only keyword list. `CommandCatalog`
remains the single runtime catalog. New command work must add the smallest
missing contract field or catalog query there, then make help, poke hints and
AI command claims consume the same field.

NoneBot's `PluginMetadata.usage` remains metadata for the framework and plugin
inspection only. It may give a short human-oriented summary, but it is never a
source of command syntax, permission, help detail, poke text, or AI command
ownership. Those user-facing decisions must be derived from `CommandCatalog`.
Changing a metadata `usage` string therefore never changes which messages the
bot can handle.

Direct-input ownership is parser-aware. A descriptor may claim an exact
spelling or declare an explicit input matcher. It must not reserve a broad
natural-language prefix merely to keep AI from responding: parameterized
commands claim only inputs their own parser can accept or reject with a
command-specific validation error.

The type rename does not make the migration complete. Completion still requires
command parsing ownership, access metadata and documentation fields to move out
of matcher-local constants. Plans and reviews must use this precise wording:

| Subject | Correct status | Required wording |
| --- | --- | --- |
| `PluginDefinition` | retired | Historical only; never a current contract. |
| `PluginContribution` | target, currently implemented | Plugin-local runtime contribution only. |
| `CommandContract` | target, currently implemented | The only direct-command representation. |
| `CommandCatalog` | target, currently implemented | The only command metadata/catalog authority. |

Completion requires one explicit command-contract type, every direct command
being registered through it, and deletion of matcher-local duplicate command
metadata. A rename alone is not completion.

Every direct-command domain must expose its contracts from `services.<domain>`
(or `core` for cross-domain contracts). A platform plugin may submit those
contracts to `PluginContribution`, but it must not
redeclare examples, access rules, help text, or input ownership. The current
migration inventory lives in `docs/multiplatform-refactor.md`; update it in the
same commit as every ownership move. This is deliberately stricter than
`PluginMetadata.usage`, which remains non-authoritative framework metadata.

### Plugin Profiles

The bundled NoneBot manifests are intentionally different deployment profiles:

| Profile | Purpose | Included user-facing scope |
| --- | --- | --- |
| `full` | Normal production deployment | Every bundled OneBot plugin. |
| `core` | Compact or platform-porting baseline | Seer queries, rank help, help, and about; plus only the runtime dependencies those plugins need. |

`core` is a strict subset of `full`, not an alias. During application assembly,
the feature-policy service reports the atomic features actually enabled by
TOML. The application then verifies that the selected manifest has a
contribution owning every configured built-in feature. A compact profile must
therefore fail at startup when its policy enables an omitted feature; it must
never silently advertise a command that was not loaded. Superuser bypass is
an authorization rule and does not make an unloaded plugin part of a profile.

### Architecture Documentation Merge Rule

Architecture-document merge conflicts are resolved by responsibility, not by
choosing whichever wording is easiest to merge. A conflict is not evidence
that both designs must survive in the running application.

### Normative Source Map

The following documents have deliberately different authority. A later edit
must not silently use a deployment guide or an old progress note to redefine a
target contract:

| Question | Authoritative source | How to resolve a disagreement |
| --- | --- | --- |
| What code, schema, or test is true **now**? | Verified implementation and its focused tests | Correct stale prose to match the verified implementation. |
| What a new cross-feature design must move toward | This document's target contracts and transition inventory | Keep the target; label the current implementation as `transition` until it is removed. |
| How work is scoped, reported, verified, and handed off | `docs/engineering-workflow.md` | Follow its process without creating a second technical authority. |
| How a deployer configures or uses the current release | `README.md` and `config.example.toml` | Update after the implementation changes; neither document may redefine an architecture target. |

Different branches, plans, or revisions may have been written by the same
person or assistant. That does not make their assertions automatically
compatible: a statement about an earlier implementation can still be stale,
and a future plan can still be unimplemented. Resolve the responsibility first
and then rewrite the result as one verified `current`, `transition`, or
`target` statement. Never retain two competing statements merely because both
were previously generated.

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
not establish an architectural conflict. Conversely, cleanly merged prose can
still contain a responsibility conflict. The verified code state and this
document's target authority decide the resolution in both cases.

A semantic documentation merge is incomplete until the phase ledger records
the result: update the affected phase's verified sub-items, remaining gate and
status only from evidence in the merged code and tests. Accepting text from a
branch is not evidence that its phase is complete. The merge commit must name
the responsibility resolved and the surviving target authority, so later work
does not have to reconstruct the decision from competing prose.

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
| Feature-policy decisions for inbound messages | target | `FeatureService.is_feature_allowed(actor, conversation, feature)`, `conversation_has_feature(conversation, feature)` and `is_message_blocked(actor, conversation)` | Plugins, services and integrations pass typed identities. `config.models.features.build_onebot_feature_service()` is the only OneBot TOML compiler and must finish alias and bundle expansion before constructing the service. |
| Command-context identity and access checks | target | `CommandContext(actor, conversation, group_role)` plus typed feature-policy methods | `CommandCatalog`, help, poke candidates and AI command claims must not receive native user/group integers. OneBot event and poke adapters use `integrations.onebot.identity` to construct the typed context at the edge. |
| Team-audit reminders | target reference | `TeamAuditService` plus a OneBot adapter | Reuse this shape for event-triggered delivery. |
| Proactive text delivery | target | `ProactiveMessageDelivery` plus `OutboundMessenger` | All new non-rich proactive text sends use typed conversations, subscription filtering, promotion text, daily hints and failure summaries here. |
| Administrator notices | target reference | `AdminNoticeService` plus `OutboundAdminNoticeSender` | Resolve administrators as `ActorRef` values and send through `ProactiveMessageDelivery`; no OneBot delivery object is exposed to the service. |
| Activity reminders | target reference | `ActivityService` plus `ActivityReminderOutboundSender` | Build typed recipients and a text message, then delegate subscription and rate-limit semantics to proactive delivery. |
| OneBot outbound delivery | target adapter | `integrations.onebot.outbound_messenger.OneBotOutboundMessenger` | Convert typed messages to OneBot only after `ConversationRef` routing. Numeric batch targets and `OneBotDelivery` are deleted and must not return. |
| OneBot reference resolution and numeric QQ configuration | target adapter | `config.onebot_references.OneBotReferenceResolver` plus OneBot integration config compilers | Convert aliases and numeric QQ values to opaque refs or typed recipient snapshots before a service is constructed; a service must not receive the resolver itself. |
| Push-preference repositories | target with OneBot configuration bridge | `PushSubscriptionRepository` and Bilibili preference storage accept `ConversationRef`; their SQLite rows use the same platform, kind and opaque ID identity | Keep native numeric QQ conversion at TOML/composition and OneBot-delivery boundaries. Do not reintroduce `target_type` / `target_id` as a service or repository contract. |
| OneBot poke hints | target, OneBot-only capability | `integrations.onebot.help_hint.OneBotHelpHintService` plus the passive help plugin | Keep QQ numeric IDs, configured aliases and poke-event semantics inside the OneBot adapter; future platforms may expose a separate capability rather than reusing this service. |
| Lucky-skin-window delivery | target reference | `LuckySkinWindowService` plus `LuckySkinWindowOutboundSender` | Reuse typed actor ownership and the shared outbound messenger; persist domain-specific daily state in the lucky-skin service. |
| Team-resource subscription delivery | target reference | `TeamResourceService` plus `TeamResourceOutboundSender` | Compile numeric QQ configuration and mention parts at the OneBot boundary, then deliver through the shared outbound messenger. |
| Seer request-scheduler requester attribution | target | `PlayerRequestProtectionService` accepts `ActorRef` for priority, pause bypass, workflow telemetry and semantic tracing | The feature policy adapts platform actors to configured superuser state; Seer and queue services must not accept platform user integers. |
| Player-detail extension actions | target | `PlayerDetailActionRequest(player_id, actor, conversation)` | Public and private extensions receive one validated request; they must not accept separate QQ user IDs, group IDs, or adapter events. |
| Headless-operation actor/conversation diagnostics | target | `HeadlessOperationTracker` stores typed `ActorRef` / `ConversationRef` in operation traces | New requests pass opaque platform references through services; adapters own native IDs and platform-specific notification rendering. |
| AI chat, intent, and memory identity | target | `AiService` and `AiMemoryStore` accept typed `ActorRef` / `ConversationRef` | OneBot adapters convert events once; session isolation, feature checks, and persisted memory never receive native QQ IDs. |
| Bilibili interactive query identity | target with configuration bridge | `BilibiliService` and `BiliTargetService` accept typed `ActorRef` / `ConversationRef` | Existing OneBot TOML alias maps are read only at the target-configuration boundary. Bilibili accounts and push targets have no built-in source: every monitored account must be declared in TOML. The separate rich-media delivery adapter is defined in the next row. |
| Bilibili rich-media push delivery | target reference | `BilibiliMonitorService` invokes its `DynamicPushSender` port; `services.bilibili.outbound_delivery.BilibiliDynamicOutboundSender` creates portable parts and delegates routing, retries, rate limits and subscription hints to the shared outbound path | Keep future platform-specific media rendering in platform adapters, never in the Bilibili service. |
| Configured Seer account aliases | target | `services.identity.PlayerAccountRegistry` resolves configured account names and scoped aliases | Configuration constructs the registry; plugins and Seer services depend on the identity service, never on a `config.*` registry module. |
| Renderer-owned data lookup and association guessing | transition | Existing renderer code only for correctness fixes | Move data preparation to repositories/build facts, then make renderers consume view models. Raw-package omissions that change display use a SeerAPI `pet_soulmark_display_addition` fact with provenance; no presenter may branch on a pet ID. |
| Private-extension loading | target | Verified private `[tool.nonebot.plugins]` manifest plus a scoped `PluginInstallContext` | The public bootstrap only validates the package and calls `nonebot.load_from_toml`; modules receive narrow declared extension contexts, never composition internals. |

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

`config.models.settings` is the single narrow exception to the normal
configuration-layer direction: it may construct
`services.identity.PlayerAccountRegistry` from validated TOML entries. The
registry is a framework-free value/lookup service, and this exception must not
be broadened to another `services.*` module without adding a new inventory row
and an AST guard.

The following rules are mandatory:

- Plugins adapt transport events and send results. They do not own reusable
  parsing, persistence, HTTP calls, scheduling, retries, or business policy.
- Public feature-policy calls in plugins and services receive `ActorRef` and
  `ConversationRef`. `FeatureService` contains no numeric group/user helpers;
  `config.models.features.build_onebot_feature_service()` owns the one-time
  TOML alias and feature-bundle compilation. All callers use
  `is_feature_allowed`, `conversation_has_feature`, or a typed domain
  predicate such as `is_message_blocked`.
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

### Spec-Driven Delivery

For any change that crosses a module boundary, changes a public command,
configuration, persistence, rendering contract, or another repository, create
a feature spec from [docs/specs/TEMPLATE.md](docs/specs/TEMPLATE.md) before
editing production code. The spec is the executable agreement for that change:
it records the target behaviour, semantic owner, accepted inputs and outputs,
non-goals, migration and rollback, and acceptance evidence. It is not a second
architecture document.

Use [docs/specs/README.md](docs/specs/README.md) for the lifecycle and naming
rules. `ARCHITECTURE.md` remains the authority for durable ownership and target
contracts; `docs/engineering-workflow.md` remains the authority for how work is
reviewed and reported; `docs/multiplatform-refactor.md` remains the migration
ledger. A feature spec links to those documents instead of duplicating them.

Small, local correctness fixes may use a short design note in the commit or
task instead of a separate spec only when they do not alter a user contract,
schema, configuration, command syntax, or ownership boundary. If investigation
widens such a fix, stop and promote it to a spec before adding another patch.

Each implementation step must trace to one acceptance criterion in its spec.
When facts change, update the spec before changing the implementation; do not
preserve an obsolete plan through compatibility code. A spec is complete only
when its verified evidence, remaining risks, and rollback state are recorded.

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

Platform identity is deliberately distinct from Seer domain identity. A
`player_id`, rank-table `user_id`, or headless-game account ID is a numeric
米米号 and remains an integer where the Seer protocol or its facts require one;
it must never be migrated into `ActorRef`. Conversely, a QQ user/group/member
identity is always an `ActorRef` or `ConversationRef` outside the OneBot
boundary, even when its source happened to be numeric. Storage audits and
migrations classify IDs by table ownership and protocol meaning, not by a
column name such as `user_id` or `group_id`.

Extension callbacks follow the same boundary. A player-detail extension
receives `PlayerDetailActionRequest(player_id, actor, conversation)`, not a
tuple of numeric player, QQ-user and group IDs. The public player-command
adapter resolves the player target and platform message once; quota checks,
request scheduling and operation tracing then use the request's typed actor
and conversation. An extension that needs a platform-native value must expose
a narrow platform integration port rather than widening this callback.

Separately distributed extensions import their permitted dependencies from an
explicit public contract in `ironsbot.extensions.contracts`, never from
`ironsbot.app.composition`, `ironsbot.app.private_extensions`, or a public
plugin implementation. Each extension receives only the smallest context its
declared responsibility needs; the application's larger runtime object stays
an internal composition detail.

An external extension may additionally import a documented core command
contract (for example `core.command_catalog.CommandContract` and
`core.player_reference_commands.player_reference_input_matcher`) when it
declares a direct command, and the narrowly scoped `core.plugin_install` install
API needed to submit its own `PluginContribution`. These are public semantic
contracts, not plugin implementation details. It must not import historical
`runtime.commands` or `runtime.player_reference_commands` paths. When such a
core contract moves, update the external package in the same cross-repository
phase; do not restore a deleted runtime module as a compatibility shim. An
extension that still imports a removed path is an unvalidated dependency, even
if the bundled application tests do not install it.

Phase 1 begins with `core.platform` and `core.outbound`: `ActorRef`,
`ConversationRef`, `IncomingMessageRef`, message parts, `OutboundMessage`,
`ReplyContext`, `SendResult`, `DeliveryCapabilities`, and
`OutboundMessenger`. They use opaque nonempty string IDs.
`integrations.onebot.outbound_messenger.OneBotOutboundMessenger` is the OneBot
edge adapter for the port: it translates text, images, mentions and reply
contexts only after a `ConversationRef` has been routed to a OneBot bot. Numeric
target types and the former `OneBotDelivery` batch bridge were removed in Phase 3;
new services use the platform-neutral port directly.

`services.team.audit.TeamAuditService` is the first complete reference use
case for this boundary. Its workflow, reminder store, scheduler jobs, and
outbound messages use `ConversationRef`, `ActorRef`, and `OutboundMessenger`.
The OneBot plugin converts notice events at the edge, while
`integrations.onebot.team_audit` owns configured feature policy, bot routing,
and group-member probes. Future transport migrations should follow this shape
rather than passing numeric IDs or adapter bot instances into a service.

`services.messaging.proactive_delivery.ProactiveMessageDelivery` is the target
reference for proactive **text** delivery. It accepts typed conversations and
`OutboundMessage` values, applies feature/subscription checks, promotions,
daily subscription hints, scatter timing and failure summaries, then delegates
only final transport to `OutboundMessenger`. `OneBotOutboundMessenger` is the
current edge adapter. Any new non-rich scheduled, administrative or service
notification must use this service or a narrower domain port that delegates to
it; it must not import `OneBotMessageTarget`, `OneBotDelivery`, a NoneBot
`Bot`, or CQ message types.

`services.messaging.admin_notice.AdminNoticeService` and
`services.activity.ActivityService` are reference consumers. Their senders
resolve `ActorRef` and `ConversationRef` recipients, create typed messages,
and invoke proactive delivery without receiving a OneBot object. Scheduled
messages, lucky-skin notices and team-resource notices use the same route.
Configuration composition and the OneBot edge are the only layers allowed to
convert native QQ numbers or create OneBot mention parts. Push-preference
SQLite rows retain platform, conversation kind and opaque conversation ID
columns, so a second transport never has to pretend that its identifiers are
QQ integers.

Monitored Bilibili dynamics now use the same route: the Bilibili domain renders
portable text and remote-image parts, while the shared delivery service keeps
subscription, promotion, queue and failure behaviour. The OneBot-only renderer
that remains under `integrations.onebot` is for an incoming user's immediate
query reply, not a monitored push. Numeric batch delivery and its test fixtures
are deleted; no replacement may be passed through `ApplicationResources`, stored
in a service, or used by a new sender.

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
  `messaging.sendpic.configs` is the sole command declaration shape for both
  packaged single images and configured indexed galleries. A single-image
  command uses `mode = "single"` and `image_file`; an indexed gallery uses
  `mode = "indexed"`, `image_dir`, and `image_filename_template`.
  Packaged image commands are typed default configs and may be overridden or
  disabled by `id`; there is no parallel fixed-image command map.
  Command-conflict guards consume the active image command set from the
  service, never a second static list.

The retired central registry is a migration-history concern, not a runtime
bridge. All built-in and private contributions now come from manifest-loaded
plugin packages. Private package validation may supply a temporary Python
import path only while NoneBot loads the package's own manifest; it must never
become a second module discovery mechanism, command directory, or lifecycle
authority.

## Contract Ownership During Migration

Every responsibility has exactly one target authority. A transitional adapter
may temporarily invoke that authority, but it must not redefine or duplicate
its data. New work must extend the target authority in this table rather than
adding fields or side registries to a temporary bootstrap adapter.

| Responsibility | Current bridge | Target authority | Migration completion |
| --- | --- | --- | --- |
| Plugin discovery and loading | Standard TOML loads declared third-party prerequisites, built-in packages, and verified private packages | `[tool.nonebot.plugins]` + `nonebot.load_from_toml` with one local package per plugin | No reflective module importer, plugin registry, or second manifest format remains. |
| Plugin identity and static metadata | `PluginMetadata` in each built-in top-level plugin package | `PluginMetadata` in each top-level plugin package | Private extensions expose equivalent declarative metadata without importing application composition code. |
| Matchers, command contracts, jobs, lifecycle contributions | `MatcherFactory` + plugin-local `PluginContribution` | `PluginContribution` created in a scoped install context | Contributions are explicit and testable without reflective lookup. |
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
`meeting`, `rank_help`, and `onebot.team_resource` also own the command contracts
for the matchers they install.
Every subsequent private extension follows the same manifest and narrow-context
pattern.

The target system must not retain an adapter merely to keep the old registry
alive. A phase may use a short-lived migration tool, but ordinary runtime must
have one path and one authority after that phase is complete.

## Data, Rendering, And Storage Direction

Persistent data remains organised by lifecycle and access pattern, not by a
desire to minimise the number of SQLite files. Large Seer content databases,
rank facts, player samples, line-up blobs, AI history, and Bilibili history
stay isolated when their contention, retention, or size differs. Small QQ
user/group state belongs to shared state stores with namespaced migrations.

### Renderer Boundary

**Target contract.** Every image renderer follows one direction only:

```text
repository -> immutable snapshot -> presenter -> RenderDocument -> renderer
                                      ^                ^              ^
                                      |                |              |
                               prepared assets     final cache    HTML/native port
```

- A repository obtains and detaches domain data while its database session is
  open. A snapshot is complete enough to survive after that session closes.
- Render value objects belong to the owning domain, not the renderer package.
  For pet information, `services.seer.pet_info_views` is shared by the data
  repository, asset adapter, presenter and document renderer; a repository
  must never import a presentation or renderer module merely to construct a
  snapshot.
- An integration loads reusable image assets through the shared `SeerImageSource`
  and `SeerAssetStore`, then combines the snapshot and assets in a pure
  presenter.
- A presenter returns an immutable `RenderDocument`. It performs no ORM, SQL,
  HTTP, filesystem access, current-time lookup, association inference, cache
  lookup, or transport operation.
- A renderer receives only the document and an HTML/native render port. Native
  work passes through the single `RenderCoordinator`; feature modules must not
  create their own semaphore, task, or timeout policy.
- The integration owns final-image cache lookup and write. It first builds an
  immutable `RenderRequestKey` from the requested render category and input,
  the published data revision, the declared asset-manifest revision, and the
  renderer/template fingerprint. An L3 hit by that key returns before any SQL,
  HTTP, asset loading, presenter invocation, or native rendering. It is never
  merely an entity-ID cache: every value that can change pixels must be part of
  the request key through a published data or asset revision.
- On an L3 miss, the integration loads the detached snapshot and required
  assets, then produces an immutable `RenderDocument`. The shared
  `render_document_cache_key()` hashes the completed document and is stored as
  integrity metadata beside the request-keyed bytes. It proves that the miss
  path's document, including actual asset bytes, matches the cache entry; it
  is not the normal lookup key. Missing asset-manifest data is a release
  contract failure, not permission to fetch assets before every L3 lookup.
- `seerapi` must publish that manifest as deterministic facts keyed by
  `(asset_kind, asset_key)`, with a content SHA-256 and release revision.
  A global database timestamp or a few feature-specific asset checks do not
  satisfy this contract. A consumer validates the manifest schema before it
  enables request-keyed final-image caching; it never probes mutable HTTP
  resources merely to decide whether an L3 entry is safe to use.

The current Phase 4 transition has the snapshot/presenter direction for
published pet info, type matchup, peak-pool, peak-vote, peak-pet-rank, and the
private player-lineup image. The new-content menu follows the same split: its
Seer-data adapter prepares details and images, while the renderer consumes an
immutable menu document. Published pet info, type matchup, peak-pool,
peak-vote, peak-pet-rank and new-content now calculate their request key before
asset materialization, and reject a release lacking an asset-manifest revision.
Those paths, plus private lineup via `PlayerLineupRenderPort`, calculate their
request key before data/asset preparation. The private lineup keeps its own
presentation module, but its adapter alone owns asset loading, final-cache
access, and the HTML render port. The remaining Phase 4 gate is complete,
scope-aware SeerAPI asset-manifest validation, not another runtime cache order.
Rank and any later renderer paths remain **transition** work. They may receive
narrow correctness fixes, but new rendering features must start from the target
pipeline above instead of copying their older data-loading patterns.

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

The executable phase order, cross-repository dependencies, and acceptance
checklists live in [docs/multiplatform-refactor.md](docs/multiplatform-refactor.md).
That document is a work-breakdown record, not a second architectural authority:
it must point back to the target contracts and transition inventory above. Keep
long-lived responsibility rules here; keep phase-local progress, estimates and
verified evidence in the work-breakdown record or task report.

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
next safe action. A phase may be marked `completed` only after its target
contract, deletion conditions, and verification evidence are recorded in the
work-breakdown ledger; later phases must treat that path as the only normal
route instead of reintroducing a compatibility registry or duplicate loader.

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
- `services` imports `core` and service modules. It may import the narrow,
  read-only published-data repositories under `integrations.seer_data`; it
  must not import transport, scheduler, generic storage, platform adapters,
  plugins, or the application composition root. A service defines protocols
  for all other infrastructure it needs.
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

The root coordinates domain builders; it must not become the implementation
site for a feature's infrastructure graph. Builders are grouped by stable
responsibility (`common`, `seer`, `messaging`, and `operations`) and return
small typed component bundles. `app.operations_composition.OperationsComponents`
is the first extracted builder: it owns data synchronization, the headless
client/session factory, server status, restart services, and the Seer database
gateway. A builder may depend on configuration and concrete integrations, but
neither a service nor a plugin may import an application builder.

`app.common_composition.CommonComponents` is the current host-bound boundary
for feature policy, prompt sessions, routing, push subscriptions, outbound
limits, proactive delivery, promotions, and administrator notices. It owns
the explicit OneBot edge wiring needed to construct the platform-neutral
outbound port, so domain builders receive typed dependencies instead of
constructing platform objects themselves. The common layer remains host-bound
composition code; only the port it supplies is platform-neutral.

`app.messaging_composition.MessagingComponents` owns configuration-backed
message schedules, fixed-image delivery, and team-audit notification assembly.
It accepts delivery, routing, rate-limit, subscription, and feature ports from
`CommonComponents`; it must not recreate them or reach into the composition
root. Other domain builders follow the same dependency direction.

`app.seer_composition.SeerComponents` owns player lookup, rank caches and
refresh, team resources, lucky-skin state, data query services, and render
dependencies. It returns the existing public service objects and immutable
render dependencies, not a broad service locator. Its OneBot account and
mention compilers remain explicit composition adapters: they create typed
identity and recipient values before a service is constructed. Notifications
already cross the platform-neutral outbound port rather than leaking platform
objects back into plugins or individual Seer services.

`app.bilibili_composition.BilibiliComponents` compiles configured OneBot
targets and creates Bilibili query, history, and login services before the
messaging builder consumes its subscription options. This keeps the composition
root as an ordering coordinator instead of a second place that knows Bilibili
storage and HTTP construction details.

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

## Private Extension Loading

`PluginContribution` is the current plugin-local runtime contribution carrier.
Every built-in plugin is a top-level manifest-loaded package and submits its
own contribution during the scoped loading window. `PluginContribution` is not
the semantic authority for commands, permissions, help layout, or lifecycle
policy; it carries the local installation callback, declared command
descriptors and hooks to their respective owners. The public bootstrap validates
the private package's standard NoneBot TOML and invokes `nonebot.load_from_toml`
inside the same scoped install window as built-in plugins. It is not a plugin
registry, command directory, or second discovery mechanism. Do not add built-in
feature ownership, command metadata, help metadata, lifecycle concepts, or
plugin families to this loading boundary.

The runtime contribution contract is:

```python
@dataclass(frozen=True, slots=True)
class PluginContribution:
    id: str
    features: frozenset[Feature]
    help: HelpEntry | None
    commands: tuple[CommandContract, ...] = ()
    install: PluginInstall | None = None
    hooks: PluginHooks = PluginHooks()
```

`PluginInstall` is an opaque platform-install callback. The current application
composition passes the OneBot `MatcherFactory`; individual plugin installers
may therefore retain the concrete factory type they actually require. The
generic contribution boundary must not force every installer or bot lifecycle
hook to accept `object`, and it must not leak a concrete adapter type into
platform-neutral services.

The standard manifests discover built-in and private packages directly. Private
modules can append only configured external contributions during the scoped
loading window. The package loader must not become an additional authority over
the target contracts:

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

Every message matcher is created through `runtime.matchers.MatcherFactory`.
Creation requires one explicit command policy:

- a stable semantic command id;
- a resolver for a dynamic semantic command id; or
- a documented passive/conversation exemption.

The factory installs command cooldown admission when the matcher is created.
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
`PluginContribution` carries a plugin-local matcher installer, command
descriptors, lifecycle hooks and scheduled-job contributions during the
current installation bridge. `CommandCatalog` consumes the command contracts
and remains the only command-description authority; `ApplicationLifecycle`
owns lifecycle policy and task lifetime. The replacement becomes the only
authority; the bridge and its reflective discovery are then deleted instead of
being kept as a compatibility path.

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

An enabled action that delivers to a deployment-specific account, group, link,
or invitation must declare its complete delivery content in TOML. It may have
a reusable classifier and feature key in code, but it has no built-in
recipient, URL, group number, or message fallback. Examples use non-production
values only.

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
  `MessageInputContext`; `CommandCatalog` and `CommandContract` currently
  drive help, poke candidates, access checks, and direct-command ownership.
  `MatcherFactory` constructs the current matchers and records their command
  policy. Prompts and selection menus keep their own anchored session state.
- **Permissions and identity:** the OneBot feature-config compiler resolves
  configured group and user aliases before constructing the typed feature
  policy. The policy handles group/private feature access, group-manager
  roles, and superuser bypass. The OneBot configuration boundary owns numeric
  QQ values, while policy and new services expose `ActorRef` and
  `ConversationRef`; a second platform must not consume the numeric values.
  Seer player IDs use a shared resolver for numeric IDs, aliases, one direct
  mention, and the caller's default binding. The OneBot player-query and
  binding adapters, global-rank player queries, and shortcut/detail-extension
  commands forward their raw reference through that resolver with a scoped
  alias-lookup port. Matcher admission retains the one resolution result for
  its handler; it does not resolve an alias once to decide admission and a
  second time to execute the service command.
- **Replies and proactive delivery:** group and private replies, scheduled
  pushes, activity notices, Bilibili delivery, team-resource notices, startup
  notices, and admin notices use OneBot routing and outbound rate limiting.
  Group cooldown and priority-queue behaviour are frozen by characterization
  tests; a known timing-sensitive priority test is monitored rather than
  hidden.
- **State and subscriptions:** QQ user/group state is consolidated in
  `data/state/qq_state.sqlite`; runtime task state is in
  `data/state/runtime_state.sqlite`. `ironsbot.state_migration` is the
  one-time CLI entry point; `ironsbot.state_migration_cli` owns argument
  parsing and process output while the migration service owns state copying
  and validation. Bindings, query
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
migration. The Phase 4 pet-info, type-matchup, peak-pool, peak-vote,
peak-pet-rank, and private player-lineup paths use detached snapshots, shared
image assets, immutable render documents, and pure HTML rendering. The
new-content adapter similarly prepares its data before rendering an immutable
menu document. Their renderer modules do not perform ORM, SQL, HTTP,
filesystem, or association inference. Remaining render paths are explicitly
transitional, not alternative patterns to copy. Existing Bandit findings with
no high-severity result remain tracked rather than silently suppressed.

## Enforcement

The repository must include tests that prove:

- the dependency graph above;
- one settings loader and no global settings access;
- no reflective plugin importer, bootstrap registry, or parallel command
  directory; private loading must not acquire target-contract ownership;
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
