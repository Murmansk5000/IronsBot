# SPDX-License-Identifier: MIT
from anyio import Path as AsyncPath
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.runtime.replies import finish_event_reply
from ironsbot.runtime.rules import explicit_command

ABOUT_MESSAGE = """
🤖 IronsBot
版本：{version}
项目：https://github.com/Murmansk5000/IronsBot
上游作者：Nattsu39
上游项目：https://github.com/Nattsu39/IronsBot

这是一个面向 QQ / OneBot v11 的自定义赛尔号机器人，当前版本以自定义插件为主：
米米号与战队查询、B站动态、活动提醒、榜单、群星牌、
固定图片/文本回复、AI 聊天和 Unraid 友好部署。

鸣谢：
- Nattsu39：IronsBot 上游项目。
- 火火（GitHub：Yogurt114514）：西塔伦Bot 的作者与本项目早期来源。
- SeerAPI 开源团队：数据模型、构建工具与基础数据链路。
- HurryWang（GitHub：WhY15w）：Unity 配置解析与下周预告图提取工具。
- SeerRadar：Sequ 数据参考；oldml：saixiaoxi 无头登录参考。

完整项目与工具鸣谢：https://github.com/Murmansk5000/IronsBot#%E9%B8%A3%E8%B0%A2
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
        policy=CommandPolicy.command("about", help_ids=("about",)),
        rule=explicit_command(),
        priority=registry.priority("about"),
        block=True,
    )
    matcher.append_handler(handle_about)
