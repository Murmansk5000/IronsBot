# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    MessageEvent,  # noqa: TC002 - NoneBot resolves it at runtime
)
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.runtime.conversations import (
    enter_event_reply_conversation,
    event_conversation_session_id,
)
from ironsbot.runtime.matchers import (
    CommandPolicy,
    bind_async,
    get_prompt_session_manager,
)
from ironsbot.runtime.params import parse_string_arg
from ironsbot.runtime.replies import finish_event_reply, send_event_reply
from ironsbot.runtime.rules import explicit_command, startswith_or_endswith
from ironsbot.services.seer.autocard_sanctuary import (
    SANCTUARY_QUERY_PREFIXES,
    AutocardSanctuaryService,
    SanctuaryPromptValue,
    format_sanctuary_overview,
)
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE

from ..group import SeerMatcherGroup, seer_feature_rule

if TYPE_CHECKING:
    from collections.abc import Sequence


SANCTUARY_PROMPT_NAMESPACE = "autocard_sanctuary"
SANCTUARY_PROMPT_STATE_KEY = "_autocard_sanctuary_prompt_values"


def _is_sanctuary_prompt_reply(event: MessageEvent) -> bool:
    return event.get_plaintext().strip().isdigit()


def _invalidate_sanctuary_prompt(
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    get_prompt_session_manager(matcher).invalidate(
        event_conversation_session_id(SANCTUARY_PROMPT_NAMESPACE, event)
    )


async def _enter_sanctuary_prompt(
    service: AutocardSanctuaryService,
    matcher: Matcher,
    event: MessageEvent,
    values: Sequence[SanctuaryPromptValue],
    prompt: str | None,
) -> None:
    matcher.state[SANCTUARY_PROMPT_STATE_KEY] = tuple(values)
    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=SANCTUARY_PROMPT_NAMESPACE,
        handlers=[bind_async(_handle_sanctuary_prompt_reply, service)],
        reply_check=_is_sanctuary_prompt_reply,
        prompt=prompt,
    )


async def _finish_service_error(
    matcher: Matcher,
    event: MessageEvent,
    error: Exception,
) -> None:
    message = (
        DATABASE_UNAVAILABLE_MESSAGE
        if isinstance(error, DataUnavailableError)
        else f"❌ 群星牌场地公开配置获取失败：{error}"
    )
    await finish_event_reply(matcher, event, message)


async def _handle_sanctuary_prompt_reply(
    service: AutocardSanctuaryService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    key_text = event.get_plaintext().strip()
    if key_text == "0":
        await finish_event_reply(matcher, event, "❌ 已退出群星牌场地选择")

    values = tuple(state.get(SANCTUARY_PROMPT_STATE_KEY) or ())
    if not values:
        raise FinishedException
    index = int(key_text)
    if index < 1 or index > len(values):
        await finish_event_reply(
            matcher,
            event,
            "⚠️ 序号超出范围，已退出群星牌场地选择",
        )

    try:
        result = service.select(values[index - 1])
    except (DataUnavailableError, RuntimeError) as error:
        await _finish_service_error(matcher, event, error)
        return
    if result.message:
        await finish_event_reply(matcher, event, result.message)
    if result.sanctuary is not None:
        overview_values, overview_text = format_sanctuary_overview(result.sanctuary)
        await _enter_sanctuary_prompt(
            service,
            matcher,
            event,
            overview_values,
            overview_text,
        )
        return
    if result.effect is None:
        await finish_event_reply(
            matcher,
            event,
            "❌ 未找到该场地效果，这可能是数据库数据已更新或缺失。",
        )
        return

    await send_event_reply(matcher, event, result.effect.text)
    await _enter_sanctuary_prompt(service, matcher, event, values, prompt=None)


async def handle_autocard_sanctuary_query(
    service: AutocardSanctuaryService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    _invalidate_sanctuary_prompt(matcher, event)
    try:
        result = service.search(parse_string_arg(state))
    except (DataUnavailableError, RuntimeError) as error:
        await _finish_service_error(matcher, event, error)
        return

    if result.message:
        await finish_event_reply(matcher, event, result.message)
    if result.sanctuary is not None:
        values, overview = format_sanctuary_overview(result.sanctuary)
        await _enter_sanctuary_prompt(service, matcher, event, values, overview)
        return
    if result.effect is not None:
        await finish_event_reply(matcher, event, result.effect.text)
    if not result.prompt_values:
        raise FinishedException
    await _enter_sanctuary_prompt(
        service,
        matcher,
        event,
        result.prompt_values,
        result.prompt_text,
    )


def install(group: SeerMatcherGroup) -> None:
    matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_autocard_sanctuary_query",
            help_ids=("seer.autocard.sanctuary",),
        ),
        rule=seer_feature_rule(group.features, "seer_autocard")
        & startswith_or_endswith(prefixes=SANCTUARY_QUERY_PREFIXES, suffixes=())
        & explicit_command(),
        priority=group.matcher_priority("seer_autocard"),
    )
    matcher.append_handler(
        bind_async(handle_autocard_sanctuary_query, group.resources.autocard_sanctuary)
    )
