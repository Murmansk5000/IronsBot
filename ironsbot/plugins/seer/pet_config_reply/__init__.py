from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import Depends
from nonebot.plugin import on_message
from nonebot.rule import Rule
from seerapi_models import PetORM

from ironsbot.custom_plugins.message_actions import finish_event_reply
from ironsbot.plugins.seer_data.db import GetPetData
from ironsbot.shared.features import is_event_feature_allowed
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from .service import PET_CONFIG_UNSUPPORTED_MESSAGE, should_reply_pet_config

PET_CONFIG_PLUGIN_NAME = "pet_config_reply"

pet_config_matcher = on_message(
    rule=(
        Rule(lambda event: is_event_feature_allowed(event, "seer"))
        & startswith_or_endswith(prefixes=(), suffixes=("配置",))
        & no_reply()
    ),
    priority=4,
    block=False,
)


class PetConfigReplyPlugin:
    name = PET_CONFIG_PLUGIN_NAME
    feature = "seer"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        arg = str(context.data.get("arg", ""))
        pets = tuple(context.data.get("pets", ()))
        if not should_reply_pet_config(arg, pets):
            raise FinishedException

        await finish_event_reply(
            context.matcher or pet_config_matcher,
            event,
            PET_CONFIG_UNSUPPORTED_MESSAGE,
        )


register_plugin(PetConfigReplyPlugin())


@pet_config_matcher.handle()
async def handle_pet_config_reply(
    matcher: Matcher,
    event: MessageEvent,
    arg: str = Depends(parse_string_arg),
    pets: tuple[PetORM, ...] = GetPetData(),
) -> None:
    await dispatch_plugin(
        plugin_name=PET_CONFIG_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        arg=arg,
        pets=pets,
    )
