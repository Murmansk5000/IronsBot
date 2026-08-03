# SPDX-License-Identifier: MIT
# ruff: noqa: TC002
from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
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
from ironsbot.core.time import daily_time_parts
from ironsbot.runtime.commands import CommandDescriptor
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry, bind_async
from ironsbot.runtime.plugins import HelpEntry, PluginDefinition, PluginHooks
from ironsbot.runtime.replies import finish_event_reply
from ironsbot.runtime.rules import explicit_command
from ironsbot.services.operations.scheduler import JobRegistry
from ironsbot.services.seer.lucky_skin_window import (
    LuckySkinWindowBindingError,
    LuckySkinWindowError,
    LuckySkinWindowNotConfiguredError,
    LuckySkinWindowService,
)

if TYPE_CHECKING:
    from ironsbot.core.features import FeatureService
    from ironsbot.services.messaging.delivery import MessageDelivery
    from ironsbot.services.operations.scheduler import Scheduler

_COMMANDS = ("幸运橱窗", "橱窗")
_ACTION = ActionDefinition("seer.lucky_skin_window.query", "幸运橱窗")
_JOB_PREFIX = "lucky_skin_window:"
logger = logging.getLogger(__name__)


def plugin_definition(
    service: LuckySkinWindowService,
    features: FeatureService,
    delivery: MessageDelivery,
    scheduler: Scheduler,
) -> PluginDefinition:
    return PluginDefinition(
        id="lucky_skin_window",
        features=frozenset({Feature.LUCKY_SKIN_WINDOW}),
        help=HelpEntry(
            name="幸运橱窗",
            description="查看绑定米米号当天幸运橱窗刷新的四个皮肤。",
            group="seer",
            order=16,
            visible=partial(_help_visible, service=service, features=features),
            notes=("发送“橱窗”查看；可在“TD”中退订每日提醒。",),
        ),
        commands=(
            CommandDescriptor(
                id=_ACTION.id,
                plugin_id="lucky_skin_window",
                section="幸运橱窗",
                examples=("橱窗",),
                description="查看绑定米米号当天刷新出的四个皮肤",
                features_any=("lucky_skin_window",),
                show_in_poke=True,
            ),
        ),
        install=partial(_install, service=service, features=features),
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
    _ = state
    if "".join(event.get_plaintext().split()) not in _COMMANDS:
        return False
    if service.account_for_user(event.user_id) is None:
        return False
    if isinstance(event, GroupMessageEvent):
        return features.is_group_feature_allowed(
            event.user_id,
            event.group_id,
            "lucky_skin_window",
        )
    return isinstance(event, PrivateMessageEvent) and (
        features.is_private_feature_allowed(
            event.user_id,
            "lucky_skin_window",
        )
    )


def _semantic_request(
    service: LuckySkinWindowService,
    event: MessageEvent,
    state: T_State,
) -> SemanticRequest:
    _ = state
    account = service.account_for_user(event.user_id)
    target_key = str(account.player_id) if account is not None else str(event.user_id)
    return SemanticRequest(
        action=_ACTION,
        target=SemanticTarget(target_key, f"{target_key} 幸运橱窗"),
        source=SemanticRequestSource.DIRECT,
    )


async def _handle_query(
    service: LuckySkinWindowService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    try:
        result = await service.check_for_user(event.user_id)
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
            "lucky skin window query unavailable: user_id=%s error=%s",
            event.user_id,
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
    await finish_event_reply(
        matcher,
        event,
        service.format_result(result, user_id=event.user_id),
    )


def _install(
    registry: MatcherRegistry,
    *,
    service: LuckySkinWindowService,
    features: FeatureService,
) -> None:
    matcher = registry.on_message(
        policy=CommandPolicy.command(
            _ACTION.id,
            help_ids=(_ACTION.id,),
            semantic_request=partial(_semantic_request, service),
        ),
        rule=Rule(bind_async(_matches_query, service=service, features=features))
        & explicit_command(),
        priority=registry.priority("seer_query"),
        block=True,
    )
    matcher.append_handler(bind_async(_handle_query, service))


def _register_schedule(
    service: LuckySkinWindowService,
    delivery: MessageDelivery,
    scheduler: Scheduler,
) -> None:
    if not service.enabled:
        return
    config = service.config
    daily_hour, daily_minute = daily_time_parts(config.time)
    JobRegistry(scheduler, prefix=_JOB_PREFIX).add(
        service.clear_previous_days,
        "cron",
        job_id="cache_cleanup",
        hour=0,
        minute=0,
        second=0,
        timezone=config.timezone,
    )
    JobRegistry(scheduler, prefix=_JOB_PREFIX).add(
        partial(service.send_daily_notifications, delivery),
        "cron",
        job_id="daily",
        hour=daily_hour,
        minute=daily_minute,
        second=0,
        timezone=config.timezone,
    )
