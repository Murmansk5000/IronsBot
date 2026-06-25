from nonebot.plugin import PluginMetadata

from . import runtime as runtime
from .config import Config
from .policies import setup_messaging_delivery_policies

setup_messaging_delivery_policies()

__plugin_meta__ = PluginMetadata(
    name="文本发送",
    description="按配置回复固定文本/链接，也可定时向群或私聊发送文本",
    usage=(
        "【文本发送】\n"
        "按 message 配置组中的关键词回复固定文本。\n"
        "按 message 配置组中的定时任务推送文本。\n"
        "常用场景：签到链接、活动链接、信息聚合页、群公告等。\n"
        "信息聚合页示例：xm / xrym / 雷小伊 / 重聚 -> https://seerinfo.yuyuqaq.cn/"
    ),
    config=Config,
)

__all__ = [
    "runtime",
]
