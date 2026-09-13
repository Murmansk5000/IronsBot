# SPDX-License-Identifier: MIT
# ruff: noqa: TC002
from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.core.commands import parse_confirmation
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
from ironsbot.integrations.onebot.conversations import enter_event_reply_conversation
from ironsbot.integrations.onebot.feature_policy import (
    event_is_feature_allowed,
    event_is_feature_visible_in_help,
)
from ironsbot.integrations.onebot.identity import onebot_actor_ref
from ironsbot.integrations.onebot.matchers import (
    CommandPolicy,
    MatcherFactory,
    bind_async,
)
from ironsbot.integrations.onebot.message_rendering import (
    render_onebot_outbound_message,
)
from ironsbot.integrations.onebot.prompts import Prompt, PromptItem, enter_prompt
from ironsbot.integrations.onebot.replies import finish_event_reply, send_event_reply
from ironsbot.integrations.onebot.rules import BOT_COMMAND_ARG_KEY, explicit_command
from ironsbot.services.operations.scheduler import JobRegistry
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
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
    LuckySkinWindowError,
    LuckySkinWindowNotConfiguredError,
    LuckySkinWindowResult,
    LuckySkinWindowService,
)

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.platform import ActorRef
    from ironsbot.services.operations.scheduler import Scheduler
    from ironsbot.services.seer.pet_query import PetImageSelection, PetQueryService

_JOB_PREFIX = "lucky_skin_window:"
_LOGIN_CONFIRMATION_NAMESPACE = "lucky_skin_window_login"
logger = logging.getLogger(__name__)

__plugin_meta__ = PluginMetadata(
    name="幸运橱窗",
    description="查询和订阅绑定米米号的每日幸运橱窗皮肤。",
    usage="发送“橱窗”查询；可用“关注橱窗”管理关注皮肤。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def plugin_contribution(
    service: LuckySkinWindowService,
    pet: PetQueryService,
    features: FeatureService,
    scheduler: Scheduler,
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
        install=partial(_install, service=service, pet=pet, features=features),
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
    event: Event,
    *,
    service: LuckySkinWindowService,
    features: FeatureService,
) -> bool:
    if not isinstance(event, (GroupMessageEvent, PrivateMessageEvent)):
        return False
    if not service.is_eligible_actor(_actor_from_event(event)):
        return False
    return event_is_feature_visible_in_help(features, event, "lucky_skin_window")


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


async def _handle_query(
    service: LuckySkinWindowService,
    pet: PetQueryService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    try:
        actor = _actor_from_event(event)
        cached = service.cached_for_actor(actor)
    except LuckySkinWindowNotConfiguredError:
        await finish_event_reply(matcher, event, "❌ 当前 QQ 未配置幸运橱窗账号。")
        return
    except LuckySkinWindowBindingError as error:
        await finish_event_reply(
            matcher,
            event,
            f"❌ 请先绑定 TOML 指定的米米号 {error.args[0]} 后再查询。",
        )
        return

    if cached is not None:
        await _enter_result_prompt(service, pet, matcher, event, cached)
        return

    account = service.account_for_actor(actor)
    if account is None:
        await finish_event_reply(matcher, event, "❌ 当前 QQ 未配置幸运橱窗账号。")
        return

    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=_LOGIN_CONFIRMATION_NAMESPACE,
        handlers=[bind_async(_handle_login_confirmation, service, pet)],
        reply_check=lambda reply_event: (
            parse_confirmation(reply_event.get_plaintext()) is not None
        ),
        prompt=(
            "今日幸运橱窗尚未获取，需要登录查询。\n"
            "是否继续？\n"
            "回复“是”或“y”确认，回复“否”或“n”取消。"
        ),
    )


async def _handle_login_confirmation(
    service: LuckySkinWindowService,
    pet: PetQueryService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    confirmed = parse_confirmation(event.get_plaintext())
    if confirmed is not True:
        await finish_event_reply(matcher, event, "已取消幸运橱窗查询。")
        return
    await _query_and_reply(service, pet, matcher, event)


async def _query_and_reply(
    service: LuckySkinWindowService,
    pet: PetQueryService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    actor = _actor_from_event(event)
    try:
        result = await service.check_for_actor(actor)
    except LuckySkinWindowNotConfiguredError:
        await finish_event_reply(matcher, event, "❌ 当前 QQ 未配置幸运橱窗账号。")
        return
    except LuckySkinWindowBindingError as error:
        await finish_event_reply(
            matcher,
            event,
            f"❌ 请先绑定 TOML 指定的米米号 {error.args[0]} 后再查询。",
        )
        return
    except TimeoutError:
        await finish_event_reply(matcher, event, "❌ 幸运橱窗查询超时，请稍后再试。")
        return
    except LuckySkinWindowError as error:
        logger.warning(
            "lucky skin window query unavailable: actor=%s error=%s",
            actor,
            error,
        )
        await finish_event_reply(
            matcher,
            event,
            "❌ 幸运橱窗数据暂时不可用，请稍后再试。",
        )
        return
    except Exception:  # noqa: BLE001 - the game protocol must not leak errors
        await finish_event_reply(matcher, event, "❌ 幸运橱窗查询失败，请稍后再试。")
        return
    await _enter_result_prompt(service, pet, matcher, event, result)


async def _enter_result_prompt(
    service: LuckySkinWindowService,
    pet: PetQueryService,
    matcher: Matcher,
    event: MessageEvent,
    result: LuckySkinWindowResult,
) -> None:
    choices = service.detail_choices(result)
    await enter_prompt(
        matcher,
        event,
        matcher.state,
        Prompt(
            title="幸运橱窗",
            action=LUCKY_SKIN_QUERY_ACTION,
            items=[
                PromptItem(
                    choice.name,
                    choice.description,
                    choice.value,
                    semantic_target=choice.semantic_target,
                )
                for choice in choices
            ],
        ),
        partial(_handle_result_selection, pet),
        prompt_message=_render_result_message(
            service,
            result,
            _actor_from_event(event),
        ),
    )


async def _render_result_message(
    service: LuckySkinWindowService,
    result: LuckySkinWindowResult,
    actor: ActorRef,
) -> Message:
    return render_onebot_outbound_message(
        await service.result_message(result, actor=actor)
    )


async def _handle_result_selection(
    pet: PetQueryService,
    item: PromptItem[PetImageSelection],
    matcher: Matcher,
    event: Event,
) -> None:
    if not isinstance(event, MessageEvent):
        return
    try:
        selected = await pet.select_image(item.value)
    except DataUnavailableError:
        await send_event_reply(matcher, event, DATABASE_UNAVAILABLE_MESSAGE)
        return
    if selected.message:
        await send_event_reply(matcher, event, selected.message)
    elif selected.reply is not None:
        await send_event_reply(
            matcher,
            event,
            render_onebot_outbound_message(selected.reply.to_outbound()),
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

def _install(
    registry: MatcherFactory,
    *,
    service: LuckySkinWindowService,
    pet: PetQueryService,
    features: FeatureService,
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
    matcher.append_handler(bind_async(_handle_query, service, pet))

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
        ),
    )
