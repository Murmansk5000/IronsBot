# SPDX-License-Identifier: MIT
from anyio import Path as AsyncPath
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata, on_fullmatch

from ironsbot.custom_plugins.message_actions import finish_event_reply
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.rule import no_reply

__plugin_meta__ = PluginMetadata(
    name="关于",
    description="IronsBot 项目信息与当前版本",
    usage="发送“关于”查看 IronsBot 当前版本、项目地址和主要能力。",
    supported_adapters={"~onebot.v11"},
)

ABOUT_MESSAGE = """
🤖 IronsBot
版本：{version}
项目：https://github.com/Murmansk5000/IronsBot
上游作者：Nattsu39
上游项目：https://github.com/Nattsu39/IronsBot

这是一个面向 QQ / OneBot v11 的自定义赛尔号机器人，当前版本以自定义插件为主：
米米号与战队查询、B站动态、活动提醒、榜单、群星牌、
固定图片/文本回复、AI 聊天和 Unraid 友好部署。

感谢原作者 Nattsu39 开源 IronsBot，为本项目提供了核心基础与参考。
""".strip()

VERSION_FILE_PATH = AsyncPath("__version__")
ABOUT_PLUGIN_NAME = "custom_about"

matcher = on_fullmatch("关于", rule=no_reply(), priority=0, block=True)


class CustomAboutPlugin:
    name = ABOUT_PLUGIN_NAME
    feature = "about"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        try:
            version = (await VERSION_FILE_PATH.read_text(encoding="utf-8")).strip()
        except FileNotFoundError:
            version = "未知"

        await finish_event_reply(
            context.matcher or matcher,
            event,
            ABOUT_MESSAGE.format(version=version),
        )


register_plugin(CustomAboutPlugin())


@matcher.handle()
async def handle_about(matcher: Matcher, event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=ABOUT_PLUGIN_NAME,
        event=event,
        matcher=matcher,
    )
