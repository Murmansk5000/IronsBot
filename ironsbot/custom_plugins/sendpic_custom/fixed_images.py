import base64
from pathlib import Path

from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot.matcher import Matcher
from nonebot.plugin import on_fullmatch

from ironsbot.custom_plugins.message_actions import finish_event_reply
from ironsbot.utils.rule import no_reply

IMAGE_DIR = Path(__file__).parent / "image"

IMAGE_COMMANDS = {
    "学习力": "学习力表格.png",
    "学习力表": "学习力表格.png",
    "学习力表格": "学习力表格.png",
    "巅峰姬": "巅峰姬.png",
    "必先": "必先.png",
    "技能石": "技能石.png",
}


for command, filename in IMAGE_COMMANDS.items():
    matcher = on_fullmatch(command, rule=no_reply(), priority=1, block=True)

    @matcher.handle()
    async def _handle(
        matcher: Matcher,
        event: MessageEvent,
        filename: str = filename,
    ) -> None:
        image_path = IMAGE_DIR / filename
        if not image_path.is_file():
            await finish_event_reply(
                matcher,
                event,
                "图片文件不存在，请检查机器人图片目录。",
            )

        image_base64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        await finish_event_reply(
            matcher,
            event,
            MessageSegment.image(f"base64://{image_base64}"),
        )
