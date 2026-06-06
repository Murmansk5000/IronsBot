# SPDX-License-Identifier: MIT
from typing import NoReturn

from anyio import Path
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata, on_fullmatch

from ironsbot.custom_plugins.message_actions import finish_event_reply
from ironsbot.utils.rule import no_reply

__plugin_meta__ = PluginMetadata(
    name="关于",
    description="只是一些机器人基础信息",
    usage="提供机器人基础信息",
)

matcher = on_fullmatch("关于", rule=no_reply())

ABOUT_MESSAGE = """
🔥这是一个基于 NoneBot2 和 SeerAPI 的开源赛尔号信息查询机器人🤖
版本：{version}
项目链接：https://github.com/Nattsu39/IronsBot
本项目原作是 @火火 开发的西塔伦Bot，谨以此项目向 @火火 致敬。
""".strip()

VERSION_FILE_PATH = Path() / "__version__"


@matcher.handle()
async def handle_about(matcher: Matcher, event: MessageEvent) -> NoReturn:
    try:
        version = (await VERSION_FILE_PATH.read_text(encoding="utf-8")).strip()
    except FileNotFoundError:
        version = "❌未知版本（这是一个bug，请反馈给开发者）"

    await finish_event_reply(matcher, event, ABOUT_MESSAGE.format(version=version))
