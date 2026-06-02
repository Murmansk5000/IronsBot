from nonebot import require
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import Depends
from nonebot.plugin import on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from seerapi_models import PetORM

from ironsbot.custom_plugins.message_actions import finish_event_reply
from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.rule import no_reply, startswith_or_endswith

require("ironsbot.plugins.seer_data")

from ironsbot.plugins.seer_data.db import GetPetData

pet_config_matcher = on_message(
    rule=startswith_or_endswith(prefixes=(), suffixes=("配置",)) & no_reply(),
    priority=4,
    block=False,
)


@pet_config_matcher.handle()
async def handle_pet_config_reply(
    matcher: Matcher,
    event: MessageEvent,
    arg: str = Depends(parse_string_arg),
    pets: tuple[PetORM, ...] = GetPetData(),
) -> None:
    if not arg or not pets:
        raise FinishedException

    await finish_event_reply(
        matcher,
        event,
        "此机器人暂不支持查询精灵配置。可以发送“帮助”查看目前可用的功能。"
    )
