# SPDX-License-Identifier: MIT
from nonebot.plugin import PluginMetadata

from ironsbot.shared.config.sendpic import enabled_pic_configs

from .config import Config, plugin_config
from .matchers import matcher_group as matcher_group

command_help = [
    config.help_message or f"  {'/'.join(config.command, *config.aliases)}"
    for config in enabled_pic_configs(plugin_config.sendpic_config)
]
usage = """图片相关命令

命令：
""" + "\n\n".join(command_help)

__plugin_meta__ = PluginMetadata(
    name="发图",
    description="随机或是指定输出一张图片，也可以当作表情包插件用",
    usage=usage,
    config=Config,
)
