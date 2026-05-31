from nonebot.plugin import PluginMetadata

from .config import Config, filter_enabled_configs
from . import fixed_images as fixed_images
from .matchers import matcher_group as matcher_group

command_help = [
    config.help_message or f"  {'/'.join(config.command, *config.aliases)}"
    for config in filter_enabled_configs()
]
usage = """图片相关命令

命令：
""" + "\n\n".join(command_help)

__plugin_meta__ = PluginMetadata(
    name="sendpic_custom",
    description="本地自定义图片回复插件",
    usage=usage,
    config=Config,
)
