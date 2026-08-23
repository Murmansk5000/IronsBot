# SPDX-License-Identifier: MIT
# ruff: noqa: TC002
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.core.features import Feature
from ironsbot.core.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
)
from ironsbot.core.time import ScheduledClockTime, scheduled_clock_time
from ironsbot.plugins.seer.lucky_skin_window_query import (
    handle_lucky_skin_window_query,
)
from ironsbot.plugins.seer.query.commands.player_target import (
    PlayerTargetResolution,
    resolve_event_player_target,
)
from ironsbot.runtime.commands import CommandDescriptor
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry, bind_async
from ironsbot.runtime.plugins import HelpEntry, PluginDefinition, PluginHooks
from ironsbot.runtime.prompts import Prompt, PromptItem, enter_prompt
from ironsbot.runtime.replies import finish_event_reply, send_event_reply
from ironsbot.runtime.rules import (
    BOT_COMMAND_ARG_KEY,
    explicit_command,
    member_target_command,
)
from ironsbot.services.operations.scheduler import JobRegistry
from ironsbot.services.seer.lucky_skin_window import (
    LuckySkinWatchItem,
    LuckySkinWindowBindingError,
    LuckySkinWindowNotConfiguredError,
    LuckySkinWindowResult,
    LuckySkinWindowService,
)
from ironsbot.services.seer.pet_query import PetImageSelection

if TYPE_CHECKING:
    from ironsbot.core.features import FeatureService
    from ironsbot.services.messaging.delivery import MessageDelivery
    from ironsbot.services.operations.scheduler import Scheduler
    from ironsbot.services.seer.pet_query import PetQueryService

_COMMANDS = ("幸运橱窗", "橱窗")
_WATCH_LIST_COMMANDS = ("关注橱窗", "订阅橱窗", "橱窗关注", "橱窗订阅")
_WATCH_REMOVE_COMMANDS = (
    "取消关注橱窗",
    "取消订阅橱窗",
    "取消橱窗关注",
    "取消橱窗订阅",
    "退订橱窗",
    "橱窗退订",
)
_WATCH_CLEAR_COMMANDS = (
    "清空关注橱窗",
    "清空订阅橱窗",
    "清空橱窗关注",
    "清空橱窗订阅",
)
_WATCH_RESET_COMMANDS = (
    "重置关注橱窗",
    "重置订阅橱窗",
    "重置橱窗关注",
    "重置橱窗订阅",
)
_ACTION = ActionDefinition("seer.lucky_skin_window.query", "幸运橱窗")
_WATCH_LIST_ACTION = ActionDefinition(
    "seer.lucky_skin_window.watch.list",
    "查看橱窗关注",
)
_WATCH_ADD_ACTION = ActionDefinition(
    "seer.lucky_skin_window.watch.add",
    "新增橱窗关注",
)
_WATCH_REMOVE_ACTION = ActionDefinition(
    "seer.lucky_skin_window.watch.remove",
    "取消橱窗关注",
)
_WATCH_CLEAR_ACTION = ActionDefinition(
    "seer.lucky_skin_window.watch.clear",
    "清空橱窗关注",
)
_WATCH_RESET_ACTION = ActionDefinition(
    "seer.lucky_skin_window.watch.reset",
    "重置橱窗关注",
)
_JOB_PREFIX = "lucky_skin_window:"
_QUERY_TARGET_KEY = "_lucky_skin_window_target"
_QUERY_REFERENCE_KEY = "_lucky_skin_window_reference"


def plugin_definition(
    service: LuckySkinWindowService,
    pet_query: PetQueryService,
    features: FeatureService,
    delivery: MessageDelivery,
    scheduler: Scheduler,
) -> PluginDefinition:
    return PluginDefinition(
        id="lucky_skin_window",
        features=frozenset({Feature.LUCKY_SKIN_WINDOW}),
        help=HelpEntry(
            name="幸运橱窗",
            description="查看绑定米米号当天幸运橱窗刷新的四个皮肤。超级管理员可查询已配置专用登录账号。",
            group="seer",
            order=16,
            visible=partial(_help_visible, service=service, features=features),
            notes=(
                (
                    "发送“橱窗”查看；超级管理员可用“橱窗米米号 / 橱窗别名 / "
                    "橱窗@成员”查询已配置专用账号；可用“关注橱窗”或“订阅橱窗”"
                    "管理星标；可在“TD”中退订每日提醒。"
                ),
            ),
        ),
        commands=(
            CommandDescriptor(
                id=_ACTION.id,
                plugin_id="lucky_skin_window",
                section="幸运橱窗",
                examples=("橱窗", "橱窗123456 / 橱窗别名 / 橱窗@成员（仅超级管理员）"),
                description="查看当天刷新出的四个皮肤；跨查目标必须配置专用橱窗登录账号",
                features_any=("lucky_skin_window",),
                show_in_poke=True,
            ),
            CommandDescriptor(
                id=_WATCH_LIST_ACTION.id,
                plugin_id="lucky_skin_window",
                section="橱窗关注",
                examples=("关注橱窗 / 订阅橱窗", "橱窗关注 / 橱窗订阅"),
                description="查看当前 QQ 的幸运橱窗关注列表",
                features_any=("lucky_skin_window",),
                show_in_poke=True,
            ),
            CommandDescriptor(
                id=_WATCH_ADD_ACTION.id,
                plugin_id="lucky_skin_window",
                section="橱窗关注",
                examples=("关注橱窗1400538 / 订阅橱窗1400538", "橱窗订阅名称"),
                description="按皮肤 ID、资源 ID 或名称新增橱窗关注",
                features_any=("lucky_skin_window",),
            ),
            CommandDescriptor(
                id=_WATCH_REMOVE_ACTION.id,
                plugin_id="lucky_skin_window",
                section="橱窗关注",
                examples=("取消关注橱窗1400538 / 退订橱窗1400538", "橱窗退订名称"),
                description="取消指定皮肤的橱窗关注",
                features_any=("lucky_skin_window",),
            ),
            CommandDescriptor(
                id=_WATCH_CLEAR_ACTION.id,
                plugin_id="lucky_skin_window",
                section="橱窗关注",
                examples=("清空关注橱窗 / 清空订阅橱窗",),
                description="清空当前 QQ 的幸运橱窗关注列表",
                features_any=("lucky_skin_window",),
            ),
            CommandDescriptor(
                id=_WATCH_RESET_ACTION.id,
                plugin_id="lucky_skin_window",
                section="橱窗关注",
                examples=("重置关注橱窗 / 重置订阅橱窗",),
                description="恢复 TOML 中配置的初始幸运橱窗关注列表",
                features_any=("lucky_skin_window",),
            ),
        ),
        install=partial(
            _install,
            service=service,
            pet_query=pet_query,
            features=features,
        ),
        hooks=PluginHooks(
            startup=(
                (
                    "lucky_skin_window_schedule",
                    partial(_register_schedule, service, delivery, scheduler),
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
    if not service.is_eligible_user(event.user_id):
        return False
    if isinstance(event, GroupMessageEvent):
        return features.group_has_feature(event.group_id, "lucky_skin_window")
    return features.is_private_feature_allowed(event.user_id, "lucky_skin_window")


async def _matches_query(
    event: MessageEvent,
    state: T_State,
    *,
    service: LuckySkinWindowService,
    features: FeatureService,
) -> bool:
    reference = _query_reference(event.get_plaintext())
    if reference is None:
        return False
    if not _watch_feature_allowed(event, features=features):
        return False
    target = resolve_event_player_target(
        service.player_accounts,
        event,
        reference or None,
        binding_for_user=service.default_player_id,
        allow_private=features.is_superuser(event.user_id),
        allow_partial_reference=True,
    )
    if not target.recognized:
        return False
    state[_QUERY_TARGET_KEY] = target
    state[_QUERY_REFERENCE_KEY] = reference
    return True


def _query_reference(text: str) -> str | None:
    normalized = "".join(text.split())
    if any(
        normalized.startswith(command)
        for command in (
            *_WATCH_LIST_COMMANDS,
            *_WATCH_REMOVE_COMMANDS,
            *_WATCH_CLEAR_COMMANDS,
            *_WATCH_RESET_COMMANDS,
        )
    ):
        return None
    for command in sorted(_COMMANDS, key=len, reverse=True):
        if normalized.startswith(command):
            return normalized[len(command) :]
    return None


def _watch_feature_allowed(
    event: MessageEvent,
    *,
    features: FeatureService,
) -> bool:
    if isinstance(event, GroupMessageEvent):
        return features.is_group_feature_allowed(
            event.user_id,
            event.group_id,
            "lucky_skin_window",
        )
    return isinstance(event, PrivateMessageEvent) and (
        features.is_private_feature_allowed(event.user_id, "lucky_skin_window")
    )


async def _matches_watch_exact(
    event: MessageEvent,
    state: T_State,
    *,
    commands: tuple[str, ...],
    features: FeatureService,
) -> bool:
    _ = state
    return (
        event.get_plaintext().strip() in commands
        and _watch_feature_allowed(event, features=features)
    )


async def _matches_watch_change(
    event: MessageEvent,
    state: T_State,
    *,
    commands: tuple[str, ...],
    features: FeatureService,
) -> bool:
    text = event.get_plaintext().strip()
    for command in sorted(commands, key=len, reverse=True):
        if not text.startswith(command):
            continue
        arg = text[len(command) :].strip()
        if not arg:
            return False
        if _watch_feature_allowed(event, features=features):
            state[BOT_COMMAND_ARG_KEY] = arg
            return True
        return False
    return False


def _semantic_request(
    _service: LuckySkinWindowService,
    event: MessageEvent,
    state: T_State,
) -> SemanticRequest:
    target = state.get(_QUERY_TARGET_KEY)
    target_key = (
        str(target.player_id)
        if isinstance(target, PlayerTargetResolution)
        and target.player_id is not None
        else str(event.user_id)
    )
    return SemanticRequest(
        action=_ACTION,
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


async def _result_message(
    service: LuckySkinWindowService,
    result: LuckySkinWindowResult,
    *,
    user_id: int,
) -> str | Message:
    image = await service.render_result(result, user_id=user_id)
    if image is not None:
        return Message(MessageSegment.image(image))
    return service.format_result(result, user_id=user_id)


async def _enter_result_prompt(  # noqa: PLR0913 - menu activation context is explicit
    pet_query: PetQueryService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    service: LuckySkinWindowService,
    result: LuckySkinWindowResult,
) -> None:
    prompt = Prompt(
        title="幸运橱窗",
        action=_ACTION,
        items=[
            PromptItem(
                offer.name,
                str(offer.skin_id),
                PetImageSelection(offer.resource_id, offer.name, offer.skin_id),
                semantic_target=SemanticTarget(
                    str(offer.skin_id),
                    offer.name,
                ),
            )
            for offer in result.offers
        ],
    )
    await enter_prompt(
        matcher,
        event,
        state,
        prompt,
        partial(_handle_skin_selection, pet_query),
        prompt_message=_result_message(service, result, user_id=event.user_id),
    )


async def _handle_skin_selection(
    pet_query: PetQueryService,
    item: PromptItem[PetImageSelection],
    matcher: Matcher,
    event: Event,
) -> None:
    result = await pet_query.select_image(item.value)
    if result.message:
        await matcher.finish(result.message)
        return
    if result.reply is not None and isinstance(event, MessageEvent):
        await send_event_reply(
            matcher,
            event,
            _query_reply_message(result.reply),
        )


def _query_reply_message(reply: object) -> str | Message:
    leading_text = str(getattr(reply, "leading_text", ""))
    text = str(getattr(reply, "text", ""))
    image = getattr(reply, "image", None)
    image_error = str(getattr(reply, "image_error", ""))
    if image is None:
        return f"{leading_text}{text or image_error}"
    message = Message()
    if leading_text:
        message += MessageSegment.text(leading_text)
    message += MessageSegment.image(image)
    if text:
        message += MessageSegment.text(text)
    return message


async def _handle_watch_list(
    service: LuckySkinWindowService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    try:
        items = service.watched_skins(event.user_id)
    except (LuckySkinWindowNotConfiguredError, LuckySkinWindowBindingError) as error:
        await _finish_watch_access_error(matcher, event, error)
        return
    await finish_event_reply(
        matcher,
        event,
        _format_watch_list(items),
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
        candidates = service.resolve_watch_candidates(event.user_id, arg)
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
            _apply_watch_change(service, event.user_id, operation, candidates[0]),
        )
        return
    await enter_prompt(
        matcher,
        event,
        state,
        Prompt(
            title="请问你想管理的皮肤是……",
            action=(
                _WATCH_ADD_ACTION if operation == "add" else _WATCH_REMOVE_ACTION
            ),
            items=[
                PromptItem(
                    item.name,
                    _watch_item_ids(item),
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
        _apply_watch_change(service, event.user_id, operation, item.value),
    )


async def _handle_watch_clear(
    service: LuckySkinWindowService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    try:
        changed = service.clear_watched_skins(event.user_id)
    except (LuckySkinWindowNotConfiguredError, LuckySkinWindowBindingError) as error:
        await _finish_watch_access_error(matcher, event, error)
        return
    message = "已清空关注皮肤。" if changed else "当前没有关注皮肤。"
    await finish_event_reply(matcher, event, message)


async def _handle_watch_reset(
    service: LuckySkinWindowService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    try:
        items = service.reset_watched_skins(event.user_id)
    except (LuckySkinWindowNotConfiguredError, LuckySkinWindowBindingError) as error:
        await _finish_watch_access_error(matcher, event, error)
        return
    await finish_event_reply(
        matcher,
        event,
        "已恢复 TOML 初始关注列表。\n" + _format_watch_list(items),
    )


def _apply_watch_change(
    service: LuckySkinWindowService,
    user_id: int,
    operation: str,
    item: LuckySkinWatchItem,
) -> str:
    label = f"{item.name}（{_watch_item_ids(item)}）"
    if operation == "add":
        if service.add_watched_skin(user_id, item.skin_id):
            return f"已关注：{label}"
        return f"已经关注：{label}"
    if service.remove_watched_skin(user_id, item.skin_id):
        return f"已取消关注：{label}"
    return f"尚未关注：{label}"


def _format_watch_list(items: tuple[LuckySkinWatchItem, ...]) -> str:
    lines = ["【幸运橱窗关注】"]
    if not items:
        lines.append("暂无关注皮肤。")
    else:
        lines.extend(
            f"{index}. {item.name}（{_watch_item_ids(item)}）"
            for index, item in enumerate(items, start=1)
        )
    lines.extend(
        (
            "发送“关注橱窗 / 订阅橱窗 + ID或名称”新增，",
            "发送“取消关注橱窗 / 退订橱窗 + ID或名称”取消。",
        )
    )
    return "\n".join(lines)


def _watch_item_ids(item: LuckySkinWatchItem) -> str:
    if item.resource_id > 0 and item.resource_id != item.skin_id:
        return f"皮肤ID：{item.skin_id}，资源ID：{item.resource_id}"
    return f"皮肤ID：{item.skin_id}"


def _install(
    registry: MatcherRegistry,
    *,
    service: LuckySkinWindowService,
    pet_query: PetQueryService,
    features: FeatureService,
) -> None:
    priority = registry.priority("lucky_skin_window")
    matcher = registry.on_message(
        policy=CommandPolicy.command(
            _ACTION.id,
            help_ids=(_ACTION.id,),
            semantic_request=partial(_semantic_request, service),
        ),
        rule=Rule(
            bind_async(_matches_query, service=service, features=features)
        )
        & member_target_command(),
        priority=priority,
        block=True,
    )
    matcher.append_handler(
        bind_async(
            partial(
                handle_lucky_skin_window_query,
                service,
                pet_query,
                features,
                target_key=_QUERY_TARGET_KEY,
                reference_key=_QUERY_REFERENCE_KEY,
                login_namespace="lucky_skin_window_login",
                enter_result_prompt=_enter_result_prompt,
            )
        )
    )

    watch_list = registry.on_message(
        policy=CommandPolicy.command(
            _WATCH_LIST_ACTION.id,
            help_ids=(_WATCH_LIST_ACTION.id,),
        ),
        rule=Rule(
            bind_async(
                _matches_watch_exact,
                commands=_WATCH_LIST_COMMANDS,
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
            _WATCH_ADD_ACTION.id,
            help_ids=(_WATCH_ADD_ACTION.id,),
        ),
        rule=Rule(
            bind_async(
                _matches_watch_change,
                commands=_WATCH_LIST_COMMANDS,
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
            _WATCH_REMOVE_ACTION.id,
            help_ids=(_WATCH_REMOVE_ACTION.id,),
        ),
        rule=Rule(
            bind_async(
                _matches_watch_change,
                commands=_WATCH_REMOVE_COMMANDS,
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
        (_WATCH_CLEAR_ACTION, _WATCH_CLEAR_COMMANDS, _handle_watch_clear),
        (_WATCH_RESET_ACTION, _WATCH_RESET_COMMANDS, _handle_watch_reset),
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
    delivery: MessageDelivery,
    scheduler: Scheduler,
) -> None:
    if not service.enabled:
        return
    config = service.config
    registry = JobRegistry(scheduler, prefix=_JOB_PREFIX)
    registry.add_daily(
        service.clear_previous_days,
        job_id="cache_cleanup",
        clock_time=ScheduledClockTime(0, 0, 0),
        timezone=config.timezone,
    )
    registry.add_daily(
        partial(
            service.send_daily_notifications,
            delivery,
            format_message=partial(_result_message, service),
        ),
        job_id="daily",
        clock_time=scheduled_clock_time(
            config.time,
            error_message="seer.lucky_skin_window.time must use HH:MM:SS",
        ),
        timezone=config.timezone,
    )
