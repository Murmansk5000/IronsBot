# SPDX-License-Identifier: MIT
# ruff: noqa: TC002
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)
from ironsbot.core.semantic_requests import (
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
)
from ironsbot.core.time import scheduled_clock_time
from ironsbot.integrations.onebot.feature_policy import event_is_feature_allowed
from ironsbot.integrations.onebot.identity import onebot_actor_ref
from ironsbot.integrations.onebot.matchers import (
    CommandPolicy,
    MatcherFactory,
    bind_async,
)
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.prompts import Prompt, PromptItem, enter_prompt
from ironsbot.integrations.onebot.replies import finish_event_reply
from ironsbot.integrations.onebot.rules import BOT_COMMAND_ARG_KEY, explicit_command
from ironsbot.services.help_visibility import feature_help_visible
from ironsbot.services.operations.scheduler import JobRegistry
from ironsbot.services.portable_lucky_skin_commands import (
    build_portable_lucky_skin_operations,
)
from ironsbot.services.seer.lucky_skin_commands import (
    LUCKY_SKIN_QUERY_ACTION,
    LUCKY_SKIN_WATCH_ADD_ACTION,
    LUCKY_SKIN_WATCH_CLEAR_ACTION,
    LUCKY_SKIN_WATCH_CLEAR_COMMANDS,
    LUCKY_SKIN_WATCH_LIST_ACTION,
    LUCKY_SKIN_WATCH_LIST_COMMANDS,
    LUCKY_SKIN_WATCH_REMOVE_ACTION,
    LUCKY_SKIN_WATCH_REMOVE_COMMANDS,
    LUCKY_SKIN_WATCH_RESET_ACTION,
    LUCKY_SKIN_WATCH_RESET_COMMANDS,
    is_lucky_skin_query,
    is_lucky_skin_watch_exact,
    lucky_skin_window_command_contracts,
    parse_lucky_skin_watch_target,
)
from ironsbot.services.seer.lucky_skin_window import (
    LuckySkinWatchItem,
    LuckySkinWindowBindingError,
    LuckySkinWindowNotConfiguredError,
    LuckySkinWindowService,
)

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.core.command_catalog import CommandContext
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.platform import ActorRef
    from ironsbot.services.identity_linking import IdentityLinkingService
    from ironsbot.services.operations.scheduler import Scheduler
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.seer.pet_query import PetQueryService

_JOB_PREFIX = "lucky_skin_window:"

__plugin_meta__ = PluginMetadata(
    name="幸运橱窗",
    description="查询和订阅绑定米米号的每日幸运橱窗皮肤。",
    usage="发送“橱窗”查询；可用“关注橱窗”管理关注皮肤。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def plugin_contribution(  # noqa: PLR0913 - explicit plugin resources
    service: LuckySkinWindowService,
    pet: PetQueryService,
    features: FeatureService,
    scheduler: Scheduler,
    identity_links: IdentityLinkingService,
    sessions: PortableQuerySessions,
) -> PluginContribution:
    return PluginContribution(
        id="lucky_skin_window",
        features=frozenset({Feature.LUCKY_SKIN_WINDOW}),
        help=HelpEntry(
            name="幸运橱窗",
            description="查看绑定米米号当天幸运橱窗刷新的四个皮肤。",
            group="seer",
            order=16,
            visible=partial(_help_visible, service=service, features=features),
            notes=(
                "发送“橱窗”查看；可用“关注橱窗”或“订阅橱窗”管理星标；可在“TD”中退订每日提醒。",
            ),
        ),
        commands=lucky_skin_window_command_contracts(),
        install=partial(
            _install, service=service, pet=pet, features=features,
            identity_links=identity_links, sessions=sessions,
        ),
        hooks=PluginHooks(
            startup=(
                (
                    "lucky_skin_window_schedule",
                    partial(_register_schedule, service, scheduler),
                ),
            ),
        ),
    )


def _help_visible(
    context: CommandContext,
    *,
    service: LuckySkinWindowService,
    features: FeatureService,
) -> bool:
    if not service.is_eligible_actor(context.actor):
        return False
    return feature_help_visible(
        context,
        features=features,
        feature="lucky_skin_window",
    )


async def _matches_query(
    event: MessageEvent,
    state: T_State,
    *,
    features: FeatureService,
) -> bool:
    _ = state
    if not is_lucky_skin_query(event.get_plaintext()):
        return False
    return _watch_feature_allowed(event, features=features)


def _watch_feature_allowed(
    event: MessageEvent,
    *,
    features: FeatureService,
) -> bool:
    return event_is_feature_allowed(features, event, "lucky_skin_window")


def _actor_from_event(event: MessageEvent) -> ActorRef:
    """Adapt the OneBot event identity before calling the domain service."""

    return onebot_actor_ref(event.user_id)


async def _matches_watch_exact(
    event: MessageEvent,
    state: T_State,
    *,
    commands: tuple[str, ...],
    features: FeatureService,
) -> bool:
    _ = state
    return is_lucky_skin_watch_exact(
        event.get_plaintext(), commands=commands
    ) and _watch_feature_allowed(event, features=features)


async def _matches_watch_change(
    event: MessageEvent,
    state: T_State,
    *,
    commands: tuple[str, ...],
    features: FeatureService,
) -> bool:
    arg = parse_lucky_skin_watch_target(event.get_plaintext(), commands=commands)
    if arg is None or not _watch_feature_allowed(event, features=features):
        return False
    state[BOT_COMMAND_ARG_KEY] = arg
    return True


def _semantic_request(
    service: LuckySkinWindowService,
    event: MessageEvent,
    state: T_State,
) -> SemanticRequest:
    _ = state
    account = service.account_for_actor(_actor_from_event(event))
    target_key = str(account.player_id) if account is not None else str(event.user_id)
    return SemanticRequest(
        action=LUCKY_SKIN_QUERY_ACTION,
        target=SemanticTarget(target_key, f"{target_key} 幸运橱窗"),
        source=SemanticRequestSource.DIRECT,
    )


async def _finish_watch_access_error(
    matcher: Matcher,
    event: MessageEvent,
    error: LuckySkinWindowNotConfiguredError | LuckySkinWindowBindingError,
) -> None:
    if isinstance(error, LuckySkinWindowNotConfiguredError):
        await finish_event_reply(matcher, event, "❌ 当前 QQ 未配置幸运橱窗账号。")
        return
    await finish_event_reply(
        matcher,
        event,
        f"❌ 请先绑定 TOML 指定的米米号 {error.args[0]} 后再管理橱窗关注。",
    )




async def _handle_watch_list(
    service: LuckySkinWindowService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    try:
        message = service.watch_list_message(_actor_from_event(event))
    except (LuckySkinWindowNotConfiguredError, LuckySkinWindowBindingError) as error:
        await _finish_watch_access_error(matcher, event, error)
        return
    await finish_event_reply(
        matcher,
        event,
        message,
    )


async def _handle_watch_change(
    service: LuckySkinWindowService,
    operation: str,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    arg = str(state.get(BOT_COMMAND_ARG_KEY, "")).strip()
    try:
        candidates = service.resolve_watch_candidates(_actor_from_event(event), arg)
    except (LuckySkinWindowNotConfiguredError, LuckySkinWindowBindingError) as error:
        await _finish_watch_access_error(matcher, event, error)
        return
    if not candidates:
        await finish_event_reply(matcher, event, f"❌ 未找到皮肤：{arg}")
        return
    if len(candidates) == 1:
        await finish_event_reply(
            matcher,
            event,
            service.watch_change_message(
                _actor_from_event(event),
                candidates[0],
                watched=operation == "add",
            ),
        )
        return
    await enter_prompt(
        matcher,
        event,
        state,
        Prompt(
            title="请问你想管理的皮肤是……",
            action=(
                LUCKY_SKIN_WATCH_ADD_ACTION
                if operation == "add"
                else LUCKY_SKIN_WATCH_REMOVE_ACTION
            ),
            items=[
                PromptItem(
                    item.name,
                    item.identifiers,
                    item,
                )
                for item in candidates
            ],
        ),
        partial(_handle_watch_selection, service, operation),
    )


async def _handle_watch_selection(
    service: LuckySkinWindowService,
    operation: str,
    item: PromptItem[LuckySkinWatchItem],
    matcher: Matcher,
    event: Event,
) -> None:
    if not isinstance(event, MessageEvent):
        return
    await finish_event_reply(
        matcher,
        event,
        service.watch_change_message(
            _actor_from_event(event),
            item.value,
            watched=operation == "add",
        ),
    )


async def _handle_watch_clear(
    service: LuckySkinWindowService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    try:
        message = service.watch_clear_message(_actor_from_event(event))
    except (LuckySkinWindowNotConfiguredError, LuckySkinWindowBindingError) as error:
        await _finish_watch_access_error(matcher, event, error)
        return
    await finish_event_reply(matcher, event, message)


async def _handle_watch_reset(
    service: LuckySkinWindowService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    try:
        message = service.watch_reset_message(_actor_from_event(event))
    except (LuckySkinWindowNotConfiguredError, LuckySkinWindowBindingError) as error:
        await _finish_watch_access_error(matcher, event, error)
        return
    await finish_event_reply(
        matcher,
        event,
        message,
    )

def _install(  # noqa: PLR0913 - explicit plugin resources
    registry: MatcherFactory,
    *,
    service: LuckySkinWindowService,
    pet: PetQueryService,
    features: FeatureService,
    identity_links: IdentityLinkingService,
    sessions: PortableQuerySessions,
) -> None:
    priority = registry.priority("lucky_skin_window")
    matcher = registry.on_message(
        policy=CommandPolicy.command(
            LUCKY_SKIN_QUERY_ACTION.id,
            help_ids=(LUCKY_SKIN_QUERY_ACTION.id,),
            semantic_request=partial(_semantic_request, service),
        ),
        rule=Rule(bind_async(_matches_query, features=features)) & explicit_command(),
        priority=priority,
        block=True,
    )
    matcher.append_handler(
        make_portable_query_handler(
            build_portable_lucky_skin_operations(
                service, pet, identity_links, sessions,
            )[LUCKY_SKIN_QUERY_ACTION.id],
            sessions,
        )
    )

    watch_list = registry.on_message(
        policy=CommandPolicy.command(
            LUCKY_SKIN_WATCH_LIST_ACTION.id,
            help_ids=(LUCKY_SKIN_WATCH_LIST_ACTION.id,),
        ),
        rule=Rule(
            bind_async(
                _matches_watch_exact,
                commands=LUCKY_SKIN_WATCH_LIST_COMMANDS,
                features=features,
            )
        )
        & explicit_command(),
        priority=priority,
        block=True,
    )
    watch_list.append_handler(bind_async(_handle_watch_list, service))

    watch_add = registry.on_message(
        policy=CommandPolicy.command(
            LUCKY_SKIN_WATCH_ADD_ACTION.id,
            help_ids=(LUCKY_SKIN_WATCH_ADD_ACTION.id,),
        ),
        rule=Rule(
            bind_async(
                _matches_watch_change,
                commands=LUCKY_SKIN_WATCH_LIST_COMMANDS,
                features=features,
            )
        )
        & explicit_command(),
        priority=priority,
        block=True,
    )
    watch_add.append_handler(
        bind_async(
            _handle_watch_change,
            service,
            "add",
        )
    )

    watch_remove = registry.on_message(
        policy=CommandPolicy.command(
            LUCKY_SKIN_WATCH_REMOVE_ACTION.id,
            help_ids=(LUCKY_SKIN_WATCH_REMOVE_ACTION.id,),
        ),
        rule=Rule(
            bind_async(
                _matches_watch_change,
                commands=LUCKY_SKIN_WATCH_REMOVE_COMMANDS,
                features=features,
            )
        )
        & explicit_command(),
        priority=priority,
        block=True,
    )
    watch_remove.append_handler(
        bind_async(
            _handle_watch_change,
            service,
            "remove",
        )
    )

    for action, commands, handler in (
        (
            LUCKY_SKIN_WATCH_CLEAR_ACTION,
            LUCKY_SKIN_WATCH_CLEAR_COMMANDS,
            _handle_watch_clear,
        ),
        (
            LUCKY_SKIN_WATCH_RESET_ACTION,
            LUCKY_SKIN_WATCH_RESET_COMMANDS,
            _handle_watch_reset,
        ),
    ):
        watch_action = registry.on_message(
            policy=CommandPolicy.command(action.id, help_ids=(action.id,)),
            rule=Rule(
                bind_async(
                    _matches_watch_exact,
                    commands=commands,
                    features=features,
                )
            )
            & explicit_command(),
            priority=priority,
            block=True,
        )
        watch_action.append_handler(bind_async(handler, service))


def _register_schedule(
    service: LuckySkinWindowService,
    scheduler: Scheduler,
) -> None:
    if not service.enabled:
        return
    config = service.config
    daily_time = scheduled_clock_time(
        config.time,
        error_message="invalid lucky skin window time",
    )
    JobRegistry(scheduler, prefix=_JOB_PREFIX).add(
        service.clear_previous_days,
        "cron",
        job_id="cache_cleanup",
        hour=0,
        minute=0,
        second=0,
        timezone=config.timezone,
    )
    JobRegistry(scheduler, prefix=_JOB_PREFIX).add_daily(
        service.send_daily_notifications,
        clock_time=daily_time,
        job_id="daily",
        timezone=config.timezone,
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            context.resources.lucky_skin_window,
            context.resources.seer.pet_query,
            context.resources.features,
            context.scheduler,
            context.resources.identity_links.service,
            context.resources.query_sessions,
        ),
    )
