import base64
from pathlib import Path

from nonebot.adapters.onebot.v11 import MessageSegment

DEFAULT_FIXED_IMAGE_DIR = Path(__file__).parent / "image"
FIXED_IMAGE_MISSING_MESSAGE = "图片文件不存在，请检查机器人图片目录。"

FIXED_IMAGE_COMMANDS = {
    "学习力": "学习力表格.png",
    "学习力表": "学习力表格.png",
    "学习力表格": "学习力表格.png",
    "巅峰姬": "巅峰姬.png",
    "必先": "必先.png",
    "技能石": "技能石.png",
}


def build_fixed_image_segment(
    image_dir: Path,
    filename: str,
) -> MessageSegment | None:
    image_path = image_dir / filename
    if not image_path.is_file():
        return None

    image_base64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return MessageSegment.image(f"base64://{image_base64}")
