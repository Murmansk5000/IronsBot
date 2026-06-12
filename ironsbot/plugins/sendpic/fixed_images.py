from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.plugin import on_fullmatch
from nonebot.rule import Rule

from ironsbot.shared.features import is_event_feature_allowed
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.rule import no_reply

from .fixed_image_service import (
    DEFAULT_FIXED_IMAGE_DIR,
    FIXED_IMAGE_COMMANDS,
    FIXED_IMAGE_MISSING_MESSAGE,
    build_fixed_image_segment,
)

IMAGE_DIR = DEFAULT_FIXED_IMAGE_DIR
IMAGE_COMMANDS = FIXED_IMAGE_COMMANDS
FIXED_IMAGE_PLUGIN_NAME = "sendpic_fixed_image"


class FixedImagePlugin:
    name = FIXED_IMAGE_PLUGIN_NAME
    feature = "image"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        from ironsbot.plugins.messaging import finish_event_reply

        filename = str(context.data["filename"])
        image_segment = build_fixed_image_segment(IMAGE_DIR, filename)
        matcher = context.matcher
        if matcher is None:
            return

        if image_segment is None:
            await finish_event_reply(
                matcher,
                event,
                FIXED_IMAGE_MISSING_MESSAGE,
            )

        await finish_event_reply(
            matcher,
            event,
            image_segment,
        )


register_plugin(FixedImagePlugin())


for command, filename in IMAGE_COMMANDS.items():
    matcher = on_fullmatch(
        command,
        rule=Rule(lambda event: is_event_feature_allowed(event, "image")) & no_reply(),
        priority=1,
        block=True,
    )

    @matcher.handle()
    async def _handle(
        matcher: Matcher,
        event: MessageEvent,
        filename: str = filename,
    ) -> None:
        await dispatch_plugin(
            plugin_name=FIXED_IMAGE_PLUGIN_NAME,
            event=event,
            matcher=matcher,
            filename=filename,
        )
