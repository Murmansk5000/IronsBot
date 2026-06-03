from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.plugin import on_message
from nonebot.adapters.onebot.v11 import MessageEvent

from ironsbot.custom_plugins.message_actions import finish_event_reply
from ironsbot.utils.rule import no_reply, startswith_or_endswith

pet_config_matcher = on_message(
    rule=startswith_or_endswith(prefixes=(), suffixes=("配置",)) & no_reply(),
    priority=4,
    block=False,
)


@pet_config_matcher.handle()
async def handle_pet_config_reply(
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    text = event.get_plaintext().strip()
    if len(text) <= len("配置"):
        raise FinishedException

    await finish_event_reply(
        matcher,
        event,
        "此机器人暂不支持查询精灵配置。可以发送“帮助”查看目前可用的功能。",
    )
