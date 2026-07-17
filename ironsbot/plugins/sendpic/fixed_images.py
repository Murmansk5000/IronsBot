from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.plugin import on_fullmatch
from nonebot.rule import Rule

from ironsbot.services.sendpic_fixed_image import (
    DEFAULT_FIXED_IMAGE_DIR,
    FIXED_IMAGE_COMMANDS,
    FIXED_IMAGE_MISSING_MESSAGE,
    build_fixed_image_segment,
)
from ironsbot.shared.features import is_event_feature_allowed
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import finish_event_reply, register_command_matcher
from ironsbot.utils.rule import no_reply

for command, filename in FIXED_IMAGE_COMMANDS.items():
    matcher = on_fullmatch(
        command,
        rule=Rule(lambda event: is_event_feature_allowed(event, "image")) & no_reply(),
        priority=get_matcher_priority("sendpic", 1),
        block=True,
    )
    register_command_matcher(matcher, f"sendpic_fixed.{command}")

    @matcher.handle()
    async def _handle(
        matcher: Matcher,
        event: MessageEvent,
        filename: str = filename,
    ) -> None:
        image_segment = build_fixed_image_segment(DEFAULT_FIXED_IMAGE_DIR, filename)
        if image_segment is None:
            await finish_event_reply(matcher, event, FIXED_IMAGE_MISSING_MESSAGE)
            return

        await finish_event_reply(matcher, event, image_segment)
