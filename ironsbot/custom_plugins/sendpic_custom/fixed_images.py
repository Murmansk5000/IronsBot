from pathlib import Path

from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.matcher import Matcher
from nonebot.plugin import on_fullmatch

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
    matcher = on_fullmatch(command, rule=no_reply(), priority=5, block=True)

    @matcher.handle()
    async def _handle(matcher: Matcher, filename: str = filename) -> None:
        image_path = IMAGE_DIR / filename
        await matcher.finish(MessageSegment.image(image_path))
