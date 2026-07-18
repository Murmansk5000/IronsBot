from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.services.ai.mention_guard import should_guard_non_ai_group_mention
from ironsbot.services.ai.resources import AiResources
from ironsbot.services.help_hint import HelpHintService
from ironsbot.shared.help_hints import (
    DIRECT_COMMAND_HELP_HINT_TEXT,
    PET_CONFIG_UNAVAILABLE_TEXT,
)
from ironsbot.shared.messaging import finish_event_reply


def _build_guard_message(event: MessageEvent) -> str:
    message = DIRECT_COMMAND_HELP_HINT_TEXT
    if "配置" in event.get_plaintext():
        message += f"\n{PET_CONFIG_UNAVAILABLE_TEXT}"
    return message


def install(
    registry: MatcherRegistry,
    help_hint: HelpHintService,
    resources: AiResources,
) -> None:
    async def handle_non_ai_group_at_bot(
        matcher: Matcher,
        event: GroupMessageEvent,
    ) -> None:
        if not help_hint.can_send(event.group_id):
            return

        await finish_event_reply(
            matcher,
            event,
            _build_guard_message(event),
            mention_sender=False,
        )

    matcher = registry.on_message(
        policy=CommandPolicy.command("ai_mention_guard"),
        rule=Rule(
            lambda event: should_guard_non_ai_group_mention(resources, event)
        ),
        priority=registry.pre_command_priority("ai_mention_guard"),
        block=True,
    )
    matcher.append_handler(handle_non_ai_group_at_bot)
