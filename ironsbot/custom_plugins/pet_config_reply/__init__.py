from nonebot import require
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import Depends
from nonebot.plugin import PluginMetadata, on_message
from seerapi_models import PetORM

from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.rule import no_reply, startswith_or_endswith

require("ironsbot.plugins.seer_data")

from ironsbot.plugins.seer_data.db import GetPetData

__plugin_meta__ = PluginMetadata(
    name="精灵配置提示",
    description="当用户查询精灵配置时提示当前暂不支持该功能",
    usage="精灵名 + 配置",
)

pet_config_matcher = on_message(
    rule=startswith_or_endswith(prefixes=(), suffixes=("配置",)) & no_reply(),
    priority=4,
    block=False,
)


@pet_config_matcher.handle()
async def handle_pet_config_reply(
    matcher: Matcher,
    arg: str = Depends(parse_string_arg),
    pets: tuple[PetORM, ...] = GetPetData(),
) -> None:
    if not arg or not pets:
        raise FinishedException

    await matcher.finish(
        "此机器人暂不支持查询精灵配置。可以发送“帮助”查看目前可用的功能。"
    )
