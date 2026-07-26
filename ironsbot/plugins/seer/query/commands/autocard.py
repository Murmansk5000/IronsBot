# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment
from nonebot.adapters.onebot.v11.exception import ActionFailed
from nonebot.exception import FinishedException
from nonebot.log import logger
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
from ironsbot.runtime.rules import no_reply, startswith_or_endswith
from ironsbot.services.seer.autocard import (
    AUTOCARD_QUERY_PREFIXES,
    AUTOCARD_QUERY_SUFFIXES,
    AutocardEntry,
    AutocardPromptValue,
    AutocardService,
)
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE

from ..group import SeerMatcherGroup, seer_feature_rule
from .query_rules import not_rank_query

if TYPE_CHECKING:
    from collections.abc import Sequence

AUTOCARD_PROMPT_NAMESPACE = "autocard"
AUTOCARD_PROMPT_STATE_KEY = "_autocard_prompt_values"


def _is_autocard_prompt_reply(event: MessageEvent) -> bool:
    return event.get_plaintext().strip().isdigit()


def _invalidate_autocard_prompt(
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    get_prompt_session_manager(matcher).invalidate(
        event_conversation_session_id(AUTOCARD_PROMPT_NAMESPACE, event)
    )


def _build_autocard_reply(entry: AutocardEntry, *, image: bool) -> Message:
    message = Message()
    if image and entry.image_url:
        message += MessageSegment.image(entry.image_url)
    message += MessageSegment.text(entry.text)
    return message


async def _reply_with_image_fallback(
    matcher: Matcher,
    event: MessageEvent,
    entry: AutocardEntry,
    *,
    finish: bool,
) -> None:
    reply = finish_event_reply if finish else send_event_reply
    try:
        await reply(matcher, event, _build_autocard_reply(entry, image=True))
    except ActionFailed as error:
        logger.warning(
            "autocard image reply failed, falling back to text: "
            "kind={} id={} name={} error={}",
            entry.kind,
            entry.item_id,
            entry.name,
            error,
        )
        await reply(matcher, event, _build_autocard_reply(entry, image=False))


async def _enter_autocard_prompt(
    service: AutocardService,
    matcher: Matcher,
    event: MessageEvent,
    values: Sequence[AutocardPromptValue],
    prompt: str | None,
) -> None:
    matcher.state[AUTOCARD_PROMPT_STATE_KEY] = tuple(values)
    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=AUTOCARD_PROMPT_NAMESPACE,
        handlers=[bind_async(_handle_autocard_prompt_reply, service)],
        reply_check=_is_autocard_prompt_reply,
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
        else f"❌ 群星牌公开配置获取失败：{error}"
    )
    await finish_event_reply(matcher, event, message)


async def _handle_autocard_prompt_reply(
    service: AutocardService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    key_text = event.get_plaintext().strip()
    if key_text == "0":
        await finish_event_reply(matcher, event, "❌ 已退出群星牌选择")

    values = tuple(state.get(AUTOCARD_PROMPT_STATE_KEY) or ())
    if not values:
        raise FinishedException
    index = int(key_text)
    if index < 1 or index > len(values):
        await finish_event_reply(
            matcher,
            event,
            "⚠️ 序号超出范围，已退出群星牌选择",
        )

    try:
        entry = service.select(values[index - 1])
    except (DataUnavailableError, RuntimeError) as error:
        await _finish_service_error(matcher, event, error)
        return
    if entry is None:
        await finish_event_reply(
            matcher,
            event,
            "❌ 未找到该群星牌资料，这可能是数据库数据已更新或缺失。",
        )
        return

    await _reply_with_image_fallback(
        matcher,
        event,
        entry,
        finish=False,
    )
    await _enter_autocard_prompt(service, matcher, event, values, prompt=None)


async def handle_autocard_query(
    service: AutocardService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    _invalidate_autocard_prompt(matcher, event)
    try:
        result = service.search(parse_string_arg(state))
    except (DataUnavailableError, RuntimeError) as error:
        await _finish_service_error(matcher, event, error)
        return

    if result.entry is not None:
        await _reply_with_image_fallback(
            matcher,
            event,
            result.entry,
            finish=True,
        )
    if result.message:
        await finish_event_reply(matcher, event, result.message)
    if not result.prompt_values:
        raise FinishedException
    await _enter_autocard_prompt(
        service,
        matcher,
        event,
        result.prompt_values,
        prompt=result.prompt_text,
    )


def install(group: SeerMatcherGroup) -> None:
    matcher = group.on_message(
        policy=CommandPolicy.command("seer_autocard_query"),
        rule=seer_feature_rule(group.features, "seer_autocard")
        & startswith_or_endswith(
            prefixes=AUTOCARD_QUERY_PREFIXES,
            suffixes=AUTOCARD_QUERY_SUFFIXES,
        )
        & not_rank_query
        & no_reply(),
        priority=group.matcher_priority("seer_autocard"),
    )
    matcher.append_handler(
        bind_async(handle_autocard_query, group.resources.autocard)
    )
