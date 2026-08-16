# SPDX-License-Identifier: MIT
"""Player-target query workflow for the lucky skin window plugin."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.typing import T_State

from ironsbot.core.commands import parse_confirmation
from ironsbot.plugins.seer.query.commands.player_target import PlayerTargetResolution
from ironsbot.plugins.seer.query.commands.player_target_selection import (
    enter_player_target_selection,
)
from ironsbot.runtime.conversations import enter_event_reply_conversation
from ironsbot.runtime.matchers import bind_async
from ironsbot.runtime.replies import finish_event_reply
from ironsbot.services.seer.lucky_skin_window import (
    LuckySkinWindowBindingError,
    LuckySkinWindowError,
    LuckySkinWindowNotConfiguredError,
    LuckySkinWindowResult,
    LuckySkinWindowService,
)

if TYPE_CHECKING:
    from ironsbot.core.features import FeatureService
    from ironsbot.services.seer.pet_query import PetQueryService

ResultPrompt = Callable[
    [
        "PetQueryService",
        Matcher,
        MessageEvent,
        T_State,
        LuckySkinWindowService,
        LuckySkinWindowResult,
    ],
    Awaitable[None],
]

logger = logging.getLogger(__name__)


async def _enter_target_selection(  # noqa: PLR0913 - explicit query dependencies
    service: LuckySkinWindowService,
    pet_query: PetQueryService,
    features: FeatureService | None,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    target: PlayerTargetResolution,
    *,
    target_key: str,
    reference_key: str,
    login_namespace: str,
    enter_result_prompt: ResultPrompt,
) -> None:
    async def select_player_target(
        player_id: int,
        selection_matcher: Matcher,
        selection_event: MessageEvent,
    ) -> None:
        selection_state = selection_matcher.state
        selection_state[target_key] = PlayerTargetResolution(
            player_id,
            offer_binding=True,
        )
        selection_state[reference_key] = str(player_id)
        await handle_lucky_skin_window_query(
            service,
            pet_query,
            features,
            selection_matcher,
            selection_event,
            selection_state,
            target_key=target_key,
            reference_key=reference_key,
            login_namespace=login_namespace,
            enter_result_prompt=enter_result_prompt,
        )

    await enter_player_target_selection(
        matcher,
        event,
        state,
        target,
        select_player_target,
    )


async def handle_lucky_skin_window_query(  # noqa: PLR0911, PLR0913
    service: LuckySkinWindowService,
    pet_query: PetQueryService,
    features: FeatureService | None,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    target_key: str,
    reference_key: str,
    login_namespace: str,
    enter_result_prompt: ResultPrompt,
) -> None:
    target = state.get(target_key)
    if not isinstance(target, PlayerTargetResolution):
        target = PlayerTargetResolution(None, offer_binding=False)
    if target.error is not None:
        await finish_event_reply(matcher, event, target.error)
        return
    if target.choices:
        await _enter_target_selection(
            service,
            pet_query,
            features,
            matcher,
            event,
            state,
            target,
            target_key=target_key,
            reference_key=reference_key,
            login_namespace=login_namespace,
            enter_result_prompt=enter_result_prompt,
        )
        return

    target_player_id = target.player_id
    if target_player_id is None:
        await _handle_own_query(
            service,
            pet_query,
            matcher,
            event,
            state,
            login_namespace=login_namespace,
            enter_result_prompt=enter_result_prompt,
        )
        return

    account = service.account_for_player_id(target_player_id)
    if account is None:
        await finish_event_reply(
            matcher,
            event,
            f"❌ 米米号 {target_player_id} 未配置幸运橱窗登录账号。",
        )
        return
    is_superuser = bool(features and features.is_superuser(event.user_id))
    if is_superuser:
        cached = service.cached_for_account(target_player_id)
    else:
        own_account = service.account_for_user(event.user_id)
        if own_account is None or own_account.player_id != target_player_id:
            await finish_event_reply(
                matcher,
                event,
                "❌ 只能查询你本人已配置的幸运橱窗账号。",
            )
            return
        try:
            cached = service.cached_for_user(event.user_id)
        except (
            LuckySkinWindowNotConfiguredError,
            LuckySkinWindowBindingError,
        ) as error:
            await _finish_query_access_error(matcher, event, error)
            return

    if cached is not None:
        await enter_result_prompt(pet_query, matcher, event, state, service, cached)
        return
    await _enter_login_confirmation(
        service,
        pet_query,
        matcher,
        event,
        target_player_id=target_player_id,
        target_reference=str(state.get(reference_key, "")),
        login_namespace=login_namespace,
        enter_result_prompt=enter_result_prompt,
    )


async def handle_lucky_skin_window_confirmation(  # noqa: PLR0913
    service: LuckySkinWindowService,
    pet_query: PetQueryService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    enter_result_prompt: ResultPrompt,
    target_player_id: int | None = None,
) -> None:
    if parse_confirmation(event.get_plaintext()) is not True:
        await finish_event_reply(matcher, event, "已取消幸运橱窗查询。")
        return
    await _query_and_reply(
        service,
        pet_query,
        matcher,
        event,
        state,
        target_player_id=target_player_id,
        enter_result_prompt=enter_result_prompt,
    )


async def _handle_own_query(  # noqa: PLR0913
    service: LuckySkinWindowService,
    pet_query: PetQueryService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    login_namespace: str,
    enter_result_prompt: ResultPrompt,
) -> None:
    try:
        cached = service.cached_for_user(event.user_id)
    except (LuckySkinWindowNotConfiguredError, LuckySkinWindowBindingError) as error:
        await _finish_query_access_error(matcher, event, error)
        return

    if cached is not None:
        await enter_result_prompt(pet_query, matcher, event, state, service, cached)
        return
    account = service.account_for_user(event.user_id)
    if account is None:
        await finish_event_reply(matcher, event, "❌ 当前 QQ 未配置幸运橱窗账号。")
        return
    await _enter_login_confirmation(
        service,
        pet_query,
        matcher,
        event,
        target_player_id=account.player_id,
        target_reference="",
        login_namespace=login_namespace,
        enter_result_prompt=enter_result_prompt,
    )


async def _enter_login_confirmation(  # noqa: PLR0913
    service: LuckySkinWindowService,
    pet_query: PetQueryService,
    matcher: Matcher,
    event: MessageEvent,
    *,
    target_player_id: int,
    target_reference: str,
    login_namespace: str,
    enter_result_prompt: ResultPrompt,
) -> None:
    suffix = "" if not target_reference else f"（米米号 {target_player_id}）"
    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=login_namespace,
        handlers=[
            bind_async(
                partial(
                    handle_lucky_skin_window_confirmation,
                    service,
                    pet_query,
                    enter_result_prompt=enter_result_prompt,
                    target_player_id=target_player_id,
                )
            )
        ],
        reply_check=lambda reply_event: parse_confirmation(reply_event.get_plaintext())
        is not None,
        prompt=(
            f"今日幸运橱窗{suffix}尚未获取，需要登录查询。\n"
            "是否继续？\n"
            "回复“是”或“y”确认，回复“否”或“n”取消。"
        ),
    )


async def _query_and_reply(  # noqa: PLR0913
    service: LuckySkinWindowService,
    pet_query: PetQueryService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    target_player_id: int | None,
    enter_result_prompt: ResultPrompt,
) -> None:
    try:
        result = (
            await service.check_for_user(event.user_id)
            if target_player_id is None
            else await service.check_for_account(target_player_id)
        )
    except (LuckySkinWindowNotConfiguredError, LuckySkinWindowBindingError) as error:
        await _finish_query_access_error(matcher, event, error)
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
    await enter_result_prompt(pet_query, matcher, event, state, service, result)


async def _finish_query_access_error(
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
        f"❌ 请先绑定 TOML 指定的米米号 {error.args[0]} 后再查询。",
    )
