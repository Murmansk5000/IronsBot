from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.core.commands import normalize_command_text
from ironsbot.core.help import DIRECT_COMMAND_HELP_HINT_TEXT
from ironsbot.runtime.feature_policy import event_is_feature_allowed
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry, bind
from ironsbot.runtime.onebot_context import build_notice_source, mentions_bot
from ironsbot.runtime.replies import finish_event_reply, send_event_reply

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.core.features import FeatureService
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.messaging.mention_guard import MentionGuardService

AI_CHAT_PROMPT_KEY = "_ai_chat_prompt"
RESERVED_PRIVATE_COMMANDS = {
    "help",
    "帮助",
    "动态",
    "动态刷新",
    "动态更新",
    "刷新动态",
    "更新动态",
    "数据版本",
    "数据更新",
    "更新数据",
    "服务器状态",
    "签到",
    "活动",
    "链接",
}


def _group_id(event: MessageEvent) -> int | None:
    return int(event.group_id) if isinstance(event, GroupMessageEvent) else None


def _is_reserved_private_command(event: MessageEvent, prompt: str) -> bool:
    return (
        not isinstance(event, GroupMessageEvent)
        and normalize_command_text(prompt).lstrip("/") in RESERVED_PRIVATE_COMMANDS
    )


def _should_guard_non_ai_group_mention(
    features: FeatureService,
    event: MessageEvent,
) -> bool:
    return (
        isinstance(event, GroupMessageEvent)
        and mentions_bot(event)
        and not event_is_feature_allowed(features, event, "ai_chat")
    )


def _build_guard_message(event: MessageEvent) -> str:
    del event
    return DIRECT_COMMAND_HELP_HINT_TEXT


def _capture_ai_prompt(
    event: MessageEvent,
    state: T_State,
    features: FeatureService,
) -> bool:
    if (
        getattr(event, "reply", None) is not None
        or not event_is_feature_allowed(features, event, "ai_chat")
        or (
            isinstance(event, GroupMessageEvent)
            and not mentions_bot(event)
        )
    ):
        return False

    prompt = event.get_plaintext().strip()
    if _is_reserved_private_command(event, prompt):
        return False
    state[AI_CHAT_PROMPT_KEY] = prompt
    return True


def _capture_group_ai_prompt(
    event: GroupMessageEvent,
    state: T_State,
    features: FeatureService,
) -> bool:
    return _capture_ai_prompt(event, state, features)


def install(
    registry: MatcherRegistry,
    service: AiService,
    features: FeatureService,
    group_aliases: Mapping[str, int],
    mention_guard_service: MentionGuardService,
) -> None:
    async def run_ai_chat(
        matcher: Matcher,
        bot: Bot,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        prompt = state.get(AI_CHAT_PROMPT_KEY, "").strip()
        if not prompt:
            await finish_event_reply(
                matcher,
                event,
                "你想聊什么？可以 @我 后面直接写问题。",
            )

        if service.waiting_notice:
            await send_event_reply(matcher, event, "处理中...")

        reply = await service.chat_reply(
            user_id=int(event.user_id),
            group_id=_group_id(event),
            prompt=prompt,
            source_context=await build_notice_source(
                event,
                prompt,
                group_aliases,
                bot=bot,
            ),
        )
        if reply is None:
            raise FinishedException
        await finish_event_reply(matcher, event, reply)

    direct_matcher = registry.on_message(
        policy=CommandPolicy.command("ai_chat"),
        rule=Rule(bind(_capture_ai_prompt, features=features)),
        priority=registry.priority("ai_chat"),
        block=True,
    )
    direct_matcher.append_handler(run_ai_chat)

    group_at_matcher = registry.on_message(
        policy=CommandPolicy.command("ai_chat"),
        rule=Rule(bind(_capture_group_ai_prompt, features=features)),
        priority=registry.pre_command_priority("ai_group_at"),
        block=True,
    )
    group_at_matcher.append_handler(run_ai_chat)

    async def handle_non_ai_group_at_bot(
        matcher: Matcher,
        event: GroupMessageEvent,
    ) -> None:
        decision = mention_guard_service.admit(event.user_id)
        if decision.should_send_help:
            message = _build_guard_message(event)
        elif decision.reply is not None:
            message = decision.reply
        else:
            raise FinishedException
        await finish_event_reply(matcher, event, message)

    mention_guard_matcher = registry.on_message(
        policy=CommandPolicy.exempt("non-AI direct mention guard"),
        rule=Rule(
            lambda event: _should_guard_non_ai_group_mention(features, event)
        ),
        priority=registry.pre_command_priority("ai_mention_guard"),
        block=True,
    )
    mention_guard_matcher.append_handler(handle_non_ai_group_at_bot)
