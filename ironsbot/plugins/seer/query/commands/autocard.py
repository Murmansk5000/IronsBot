# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment
from nonebot.adapters.onebot.v11.exception import ActionFailed
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.params import Depends
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.integrations.seer_data.sessions import SeerAPISession
from ironsbot.services.seer.autocard import (
    AUTOCARD_PROMPT_MAX_ITEMS,
    AUTOCARD_QUERY_PREFIXES,
    AUTOCARD_QUERY_SUFFIXES,
    AutocardDataset,
    AutocardPromptValue,
    autocard_image_url,
    build_autocard_prompt_text,
    build_autocard_prompt_values,
    extract_autocard_query_arg,
    find_autocard_card_by_id,
    find_autocard_role_by_id,
    format_autocard_entry,
    format_autocard_public_info,
    is_autocard_help_query,
    load_autocard_dataset,
    search_autocard_items,
)
from ironsbot.services.seer.query_guards import is_rank_query_text
from ironsbot.shared.messaging import (
    enter_event_reply_conversation,
    finish_event_reply,
    send_event_reply,
)
from ironsbot.shared.messaging.conversations import event_conversation_session_id
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.matcher import prompt_session_manager
from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..group import matcher_group, seer_feature_priority, seer_feature_rule

AUTOCARD_PROMPT_NAMESPACE = "autocard"
AUTOCARD_PROMPT_STATE_KEY = "_autocard_prompt_values"
AUTOCARD_PLUGIN_NAME = "seer_autocard"


async def _is_not_rank_query(event: MessageEvent) -> bool:
    return not is_rank_query_text(event.get_plaintext())


autocard_matcher = matcher_group.on_message(
    rule=seer_feature_rule("seer_autocard")
    & startswith_or_endswith(
        prefixes=AUTOCARD_QUERY_PREFIXES,
        suffixes=AUTOCARD_QUERY_SUFFIXES,
    )
    & Rule(_is_not_rank_query)
    & no_reply(),
    priority=seer_feature_priority("seer_autocard"),
)


def _is_autocard_prompt_reply(event: MessageEvent) -> bool:
    return event.get_plaintext().strip().isdigit()


def _invalidate_autocard_prompt(event: MessageEvent) -> None:
    prompt_session_manager.invalidate(
        event_conversation_session_id(AUTOCARD_PROMPT_NAMESPACE, event)
    )


def _build_autocard_reply(
    dataset: AutocardDataset,
    kind: str,
    item: dict[str, object],
) -> Message:
    message = Message()
    if image_url := autocard_image_url(kind, item):
        message += MessageSegment.image(image_url)
    message += MessageSegment.text(format_autocard_entry(dataset, kind, item))
    return message


def _build_autocard_text_reply(
    dataset: AutocardDataset,
    kind: str,
    item: dict[str, object],
) -> Message:
    return Message(format_autocard_entry(dataset, kind, item))


async def _send_autocard_reply(
    matcher: Matcher,
    event: MessageEvent,
    dataset: AutocardDataset,
    kind: str,
    item: dict[str, object],
) -> None:
    try:
        await send_event_reply(
            matcher,
            event,
            _build_autocard_reply(dataset, kind, item),
        )
    except ActionFailed as e:
        logger.warning(
            "autocard image reply failed, falling back to text: "
            "kind={} id={} name={} error={}",
            kind,
            item.get("id"),
            item.get("name"),
            e,
        )
        await send_event_reply(
            matcher,
            event,
            _build_autocard_text_reply(dataset, kind, item),
        )


async def _finish_autocard_reply(
    matcher: Matcher,
    event: MessageEvent,
    dataset: AutocardDataset,
    kind: str,
    item: dict[str, object],
) -> None:
    try:
        await finish_event_reply(
            matcher,
            event,
            _build_autocard_reply(dataset, kind, item),
        )
    except ActionFailed as e:
        logger.warning(
            "autocard image finish failed, falling back to text: "
            "kind={} id={} name={} error={}",
            kind,
            item.get("id"),
            item.get("name"),
            e,
        )
        await finish_event_reply(
            matcher,
            event,
            _build_autocard_text_reply(dataset, kind, item),
        )


async def _enter_autocard_prompt(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    values: tuple[AutocardPromptValue, ...],
    prompt: str | None,
) -> None:
    state[AUTOCARD_PROMPT_STATE_KEY] = values
    matcher.state[AUTOCARD_PROMPT_STATE_KEY] = values
    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=AUTOCARD_PROMPT_NAMESPACE,
        handlers=[_handle_autocard_prompt_reply],
        reply_check=_is_autocard_prompt_reply,
        prompt=prompt,
    )


async def _handle_autocard_prompt_reply(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    session: SeerAPISession,
) -> None:
    await dispatch_plugin(
        plugin_name=AUTOCARD_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="prompt_reply",
        session=session,
    )


class AutocardPlugin:
    name = AUTOCARD_PLUGIN_NAME
    feature = "seer_autocard"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        matcher = context.matcher
        if matcher is None:
            return

        state = context.state if context.state is not None else {}
        session: SeerAPISession = context.data["session"]
        if context.action == "prompt_reply":
            await self._handle_prompt_reply(matcher, event, state, session)
            return
        if context.action == "query":
            arg = str(context.data.get("arg", ""))
            await self._handle_query(matcher, event, state, session, arg)

    async def _handle_prompt_reply(
        self,
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
        session: SeerAPISession,
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

        value = values[index - 1]
        dataset = load_autocard_dataset(session)
        if value.kind == "role":
            data = find_autocard_role_by_id(dataset, value.item_id)
        else:
            data = find_autocard_card_by_id(dataset, value.item_id)

        if data is None:
            await finish_event_reply(
                matcher,
                event,
                "❌ 未找到该群星牌资料，这可能是数据库数据已更新或缺失。",
            )
            return

        await _send_autocard_reply(matcher, event, dataset, value.kind, data)
        await _enter_autocard_prompt(matcher, event, state, values, prompt=None)

    async def _handle_query(
        self,
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
        session: SeerAPISession,
        arg: str,
    ) -> None:
        _invalidate_autocard_prompt(event)

        query = extract_autocard_query_arg(arg)
        if is_autocard_help_query(query):
            await finish_event_reply(matcher, event, format_autocard_public_info())

        try:
            dataset = load_autocard_dataset(session)
        except Exception as e:  # noqa: BLE001
            await finish_event_reply(
                matcher,
                event,
                f"❌ 群星牌公开配置获取失败：{e}",
            )
            return

        matches = search_autocard_items(dataset, query)
        if not matches:
            raise FinishedException

        if len(matches) == 1:
            kind, item = matches[0]
            await _finish_autocard_reply(matcher, event, dataset, kind, item)

        if len(matches) > AUTOCARD_PROMPT_MAX_ITEMS:
            message = (
                f"❌ 群星牌匹配超过 {AUTOCARD_PROMPT_MAX_ITEMS} 个，"
                "请换更精确的关键词。"
            )
            await finish_event_reply(
                matcher,
                event,
                message,
            )

        await _enter_autocard_prompt(
            matcher,
            event,
            state,
            build_autocard_prompt_values(matches),
            prompt=build_autocard_prompt_text(dataset, matches),
        )


register_plugin(AutocardPlugin())


@autocard_matcher.handle()
async def handle_autocard_query(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    session: SeerAPISession,
    arg: str = Depends(parse_string_arg),
) -> None:
    await dispatch_plugin(
        plugin_name=AUTOCARD_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="query",
        session=session,
        arg=arg,
    )
