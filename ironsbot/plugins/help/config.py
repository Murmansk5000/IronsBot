# SPDX-License-Identifier: MIT
from nonebot import get_plugin_config
from pydantic import BaseModel


class Config(BaseModel):
    help_ignored_plugins: list[str] = []
    """需要忽略的插件名称列表"""


plugin_config = get_plugin_config(Config)
