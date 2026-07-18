# SPDX-License-Identifier: MIT
from anyio import Path as AsyncPath
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.shared.messaging import finish_event_reply
from ironsbot.utils.rule import no_reply

ABOUT_MESSAGE = """
🤖 IronsBot
版本：{version}
项目：https://github.com/Murmansk5000/IronsBot
上游作者：Nattsu39
上游项目：https://github.com/Nattsu39/IronsBot
致敬：本项目原作是 @火火（QQ：1157733847）开发的西塔伦Bot，
谨以此项目向 @火火 致敬。感谢他为赛尔号玩家社区所做的贡献，愿火种永存。

这是一个面向 QQ / OneBot v11 的自定义赛尔号机器人，当前版本以自定义插件为主：
米米号与战队查询、B站动态、活动提醒、榜单、群星牌、
固定图片/文本回复、AI 聊天和 Unraid 友好部署。

感谢原作者 Nattsu39 开源 IronsBot，为本项目提供了核心基础与参考。
""".strip()

VERSION_FILE_PATH = AsyncPath("__version__")


async def handle_about(matcher: Matcher, event: MessageEvent) -> None:
    try:
        version = (await VERSION_FILE_PATH.read_text(encoding="utf-8")).strip()
    except FileNotFoundError:
        version = "未知"

    await finish_event_reply(
        matcher,
        event=event,
        message=ABOUT_MESSAGE.format(version=version),
    )


def install(registry: MatcherRegistry) -> None:
    matcher = registry.on_fullmatch(
        "关于",
        policy=CommandPolicy.command("about"),
        rule=no_reply(),
        priority=registry.priority("about", 0),
        block=True,
    )
    matcher.append_handler(handle_about)
