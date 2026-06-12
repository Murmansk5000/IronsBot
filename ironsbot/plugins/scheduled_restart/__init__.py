from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="定时重启",
    description="按环境变量配置每日固定时间重启机器人容器。",
    usage=(
        "设置 runtime.restart.enabled=true 后启用。\n"
        "runtime.restart.times 配置为 04:30,16:10 "
        "时每天在这些时间点重启。"
    ),
    config=Config,
)
